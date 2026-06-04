#!/usr/bin/env bash
# lib/utils.sh — shared helpers for mcp-agent-manager

log_info() {
  printf '[INFO] %s\n' "$*"
}

log_warn() {
  printf '[WARN] %s\n' "$*"
}

log_error() {
  printf '[ERROR] %s\n' "$*" >&2
}

# require_cmd <name> [<explicit-path>]
# Hard-fails if the command is not found.
require_cmd() {
  local name="${1:?require_cmd: missing command name}"
  local explicit_path="${2:-}"
  if [[ -n "$explicit_path" ]]; then
    if [[ ! -x "$explicit_path" ]]; then
      log_error "Required command '${name}' not found at ${explicit_path}"
      exit 1
    fi
  else
    if ! command -v "$name" &>/dev/null; then
      log_error "Required command '${name}' not found in PATH"
      exit 1
    fi
  fi
}

# python_toml <args...>
# Run a Python interpreter with stdlib tomllib support. macOS ships an older
# /usr/bin/python3, so do not assume the first Python in PATH can parse TOML.
python_toml() {
  local candidate
  for candidate in \
    "${MCP_AGENT_MANAGER_PYTHON:-}" \
    "$(command -v python3 2>/dev/null || true)" \
    /opt/homebrew/bin/python3 \
    /usr/local/bin/python3
  do
    [[ -n "$candidate" && -x "$candidate" ]] || continue
    if "$candidate" -c 'import tomllib' &>/dev/null; then
      "$candidate" "$@"
      return $?
    fi
  done
  log_error "Python 3.11+ with stdlib tomllib is required for TOML operations"
  return 1
}

# semver_lt <ver_a> <ver_b>
# Returns 0 (true) if ver_a < ver_b, 1 otherwise.
# Supports X.Y.Z format; ignores leading 'v'.
semver_lt() {
  local a="${1#v}"
  local b="${2#v}"

  local IFS='.'
  read -r -a a_parts <<< "$a"
  read -r -a b_parts <<< "$b"

  local i
  for i in 0 1 2; do
    local ap="${a_parts[$i]:-0}"
    local bp="${b_parts[$i]:-0}"
    if (( ap < bp )); then return 0; fi
    if (( ap > bp )); then return 1; fi
  done
  return 1  # equal, not less
}

# backup_file <path>
# Copies file to ~/.config/mcp-agent-manager/backups/<timestamp>/<basename>
backup_file() {
  local src="${1:?backup_file: missing file path}"
  if [[ ! -e "$src" ]]; then
    log_info "Backup skipped; file not found: ${src}"
    return 0
  fi
  local ts
  ts="$(date +%Y%m%dT%H%M%S)-$$"
  local dest_dir="${HOME}/.config/mcp-agent-manager/backups/${ts}"
  mkdir -p "${HOME}/.config/mcp-agent-manager/backups"
  chmod 700 "${HOME}/.config/mcp-agent-manager" "${HOME}/.config/mcp-agent-manager/backups"
  while [[ -e "$dest_dir" ]]; do
    dest_dir="${HOME}/.config/mcp-agent-manager/backups/${ts}-${RANDOM:-0}"
  done
  mkdir -p "$dest_dir"
  chmod 700 "$dest_dir"
  cp "$src" "${dest_dir}/$(basename "$src")"
  chmod 600 "${dest_dir}/$(basename "$src")"
  log_info "Backed up $(basename "$src") → ${dest_dir}/"
}

jq_bin() {
  if [[ -n "${MCP_AGENT_MANAGER_JQ:-}" ]]; then
    if [[ -x "$MCP_AGENT_MANAGER_JQ" ]]; then
      printf '%s\n' "$MCP_AGENT_MANAGER_JQ"
      return 0
    fi
    return 1
  fi
  command -v jq 2>/dev/null
}

require_jq() {
  local jq_path
  if ! jq_path="$(jq_bin)"; then
    log_error "jq not found in PATH"
    return 1
  fi
  printf '%s\n' "$jq_path"
}
