#!/usr/bin/env bash
# lib/runner.sh — run <name>: load safe secrets.env exports then exec STDIO MCP command

_SECRETS_ENV="${REGISTRY_DIR}/secrets.env"

# cmd_run <name>
# Load simple secrets.env exports (0600) then exec the STDIO command for <name>.
# This is the wrapper agents call to start an MCP server process.
cmd_run() {
  local name="${1:-}"
  if [[ -z "$name" ]]; then
    log_error "run: missing name. Usage: mcp-agent-manager run <name>"
    return 1
  fi

  if [[ ! -f "$REGISTRY_FILE" ]]; then
    log_error "registry.json not found. Run: mcp-agent-manager bootstrap"
    return 1
  fi

  local jq
  jq="$(require_jq)" || return 1

  # Look up entry
  local entry_json
  entry_json=$("$jq" --arg s "$name" '.personal_mcp_servers[$s] // empty' "$REGISTRY_FILE")
  if [[ -z "$entry_json" ]]; then
    log_error "run: name '${name}' not found in registry"
    return 1
  fi

  # Check enabled
  local enabled
  enabled=$(printf '%s' "$entry_json" | "$jq" -r '.enabled')
  if [[ "$enabled" != "true" ]]; then
    log_error "run: name '${name}' is disabled in registry"
    return 1
  fi

  # Check transport
  local transport
  transport=$(printf '%s' "$entry_json" | "$jq" -r '.transport')
  if [[ "$transport" != "stdio" ]]; then
    log_error "run: name '${name}' transport='${transport}' — only stdio supported by run"
    return 1
  fi

  # Source secrets.env if present (mode 0600 enforced)
  if [[ -f "$_SECRETS_ENV" ]]; then
    local perms
    # macOS stat -f "%OLp" returns "0600"; Linux stat -c "%a" returns "600"
    # Strip leading zeros for consistent comparison
    perms=$(stat -f "%OLp" "$_SECRETS_ENV" 2>/dev/null || stat -c "%a" "$_SECRETS_ENV" 2>/dev/null)
    perms="${perms#0}"  # strip single leading 0 (e.g. "0600" → "600")
    if [[ "$perms" != "600" ]]; then
      log_error "run: secrets.env has unsafe permissions (0${perms}). Fix: chmod 600 ${_SECRETS_ENV}"
      return 1
    fi
    _load_safe_secrets_env "$_SECRETS_ENV" || return 1
  fi

  # Extract command and args
  local command
  command=$(printf '%s' "$entry_json" | "$jq" -r '.command')

  # Read args into array safely (bash 3.2 compat: no mapfile).
  # Track count separately: bash 3.2 + set -u rejects empty-array expansion.
  local args=()
  local arg_count=0
  while IFS= read -r arg; do
    args+=("$arg")
    arg_count=$((arg_count+1))
  done < <(printf '%s' "$entry_json" | "$jq" -r '.args[]')

  # Export env vars from entry. Exact ${VAR} values reference secrets.env;
  # all other values remain literals. Never eval registry content.
  while IFS= read -r pair; do
    local ev_key="${pair%%=*}"
    local ev_val="${pair#*=}"
    if [[ "$ev_val" =~ ^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$ ]]; then
      local source_key="${BASH_REMATCH[1]}"
      if [[ -z "${!source_key+x}" ]]; then
        log_error "run: env reference '${ev_val}' for '${ev_key}' is not set"
        return 1
      fi
      ev_val="${!source_key}"
    fi
    printf -v "$ev_key" '%s' "$ev_val"
    export "$ev_key"
  done < <(printf '%s' "$entry_json" | "$jq" -r '.env | to_entries[] | "\(.key)=\(.value)"')

  # exec — replace shell process with MCP server
  if [[ $arg_count -eq 0 ]]; then
    exec "$command"
  fi
  exec "$command" "${args[@]}"
}

_trim_ws() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

_load_safe_secrets_env() {
  local path="$1"
  local raw line key value first last
  while IFS= read -r raw || [[ -n "$raw" ]]; do
    line="$(_trim_ws "$raw")"
    [[ -z "$line" || "$line" == \#* ]] && continue
    if [[ ! "$line" =~ ^export[[:space:]]+([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
      log_warn "run: ignoring unsupported secrets.env line"
      continue
    fi
    key="${BASH_REMATCH[1]}"
    value="$(_trim_ws "${BASH_REMATCH[2]}")"
    first="${value:0:1}"
    last="${value: -1}"
    if [[ ${#value} -ge 2 && ( ( "$first" == '"' && "$last" == '"' ) || ( "$first" == "'" && "$last" == "'" ) ) ]]; then
      value="${value:1:${#value}-2}"
    fi
    export "$key=$value"
  done < "$path"
}

# ensure_secrets_env — create secrets.env with mode 0600 if not present
ensure_secrets_env() {
  if [[ -f "$_SECRETS_ENV" ]]; then
    local perms
    perms=$(stat -f "%OLp" "$_SECRETS_ENV" 2>/dev/null || stat -c "%a" "$_SECRETS_ENV" 2>/dev/null)
    perms="${perms#0}"  # strip leading 0 for consistent comparison
    if [[ "$perms" != "600" ]]; then
      chmod 600 "$_SECRETS_ENV"
      log_info "Fixed secrets.env permissions → 0600"
    fi
    return 0
  fi

  mkdir -p "$REGISTRY_DIR"
  cat > "$_SECRETS_ENV" <<'ENVEOF'
# mcp-agent-manager secrets.env
# Mode: 0600 — DO NOT commit or share this file
#
# Add env var exports here for MCP servers that need secrets at runtime.
# Reference these in registry.json env fields as explicit ${VAR} values.
#
# Examples:
#   export MY_API_KEY="actual-secret-value"
#   export LITELLM_API_KEY="sk-..."
#   export TELEPORT_TOKEN="..."
ENVEOF
  chmod 600 "$_SECRETS_ENV"
  log_info "Created secrets.env at: ${_SECRETS_ENV}"
}
