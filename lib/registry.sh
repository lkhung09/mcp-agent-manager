#!/usr/bin/env bash
# lib/registry.sh — agent registry operations

REGISTRY_DIR="${HOME}/.config/mcp-agent-manager"
REGISTRY_FILE="${REGISTRY_DIR}/registry.json"
DEFERRED_FILE="${REGISTRY_DIR}/deferred.json"
STATE_FILE="${REGISTRY_DIR}/managed-state.json"

_registry_ensure_dir() {
  mkdir -p "$REGISTRY_DIR"
  chmod 700 "$REGISTRY_DIR"
  mkdir -p "${REGISTRY_DIR}/backups"
  chmod 700 "${REGISTRY_DIR}/backups"
}

# ---------------------------------------------------------------------------
# Bootstrap — delegates to Python3 (bash 3.2 compat, tomllib available)
# ---------------------------------------------------------------------------

registry_bootstrap() {
  local apply=0 force=0
  for arg in "$@"; do
    case "$arg" in
      --apply) apply=1 ;;
      --force) force=1 ;;
    esac
  done

  _registry_ensure_dir

  if [[ -f "$REGISTRY_FILE" && $force -eq 0 && $apply -eq 1 ]]; then
    log_warn "registry.json already exists. Use --force to overwrite."
    return 1
  fi

  local codex_config="${HOME}/.codex/config.toml"
  local claude_config="${HOME}/.claude.json"

  if [[ $apply -eq 1 ]]; then
    backup_file "$codex_config"
    backup_file "$claude_config"
  fi

  python_toml - \
    "$codex_config" \
    "$claude_config" \
    "$REGISTRY_FILE" \
    "$DEFERRED_FILE" \
    "$STATE_FILE" \
    "$apply" \
    "$force" \
    <<'PYEOF'
import sys, json, os, stat, tomllib

codex_toml, claude_json, reg_file, def_file, state_file, apply_flag, force_flag = sys.argv[1:]
apply = apply_flag == "1"

# Preserve exclusions across bootstrap --force. These MCPs stay owned by
# another project and must not be rendered or removed from parent configs.
unmanaged = []
if os.path.exists(reg_file):
    with open(reg_file) as f:
        unmanaged = json.load(f).get("unmanaged_mcp_servers", [])

# ---- parse Codex config.toml ----
codex_servers = {}
if os.path.exists(codex_toml):
    with open(codex_toml, "rb") as f:
        cfg = tomllib.load(f)
    for name, val in cfg.get("mcp_servers", {}).items():
        if not isinstance(val, dict):
            continue
        codex_servers[name] = {
            "command": val.get("command", ""),
            "args": val.get("args", []),
            "enabled": val.get("enabled", True),
            "url": val.get("url", ""),
            "env": val.get("env", {}),
            "env_http_headers": val.get("env_http_headers", {}),
        }

# ---- parse Claude .claude.json ----
claude_servers = {}
if os.path.exists(claude_json):
    with open(claude_json) as f:
        data = json.load(f)
    for name, val in data.get("mcpServers", {}).items():
        claude_servers[name] = {
            "command": val.get("command", ""),
            "args": val.get("args", []),
            "enabled": True,
            "url": "",
            "env": val.get("env", {}),
        }

# ---- merge ----
all_names = sorted(set(list(codex_servers) + list(claude_servers)))
registry = {}
deferred = {}
preview_reg = []
preview_def = []

for name in all_names:
    if name in unmanaged:
        continue
    codex = codex_servers.get(name)
    claude = claude_servers.get(name)

    # HTTP transport → deferred (redact credentials)
    # Bug 9: preserve original env keys, do NOT hardcode provider-specific headers
    url = (codex or {}).get("url", "")
    if url:
        original_env = (codex or {}).get("env", {})
        original_headers = (codex or {}).get("env_http_headers", {})
        # Redact values but preserve key names from actual config.
        redacted_env = {k: "[REDACTED]" for k in original_env}
        redacted_headers = {k: "[REDACTED]" for k in original_headers}
        original_config = {"url": url}
        if redacted_env:
            original_config["env_redacted"] = redacted_env
        if redacted_headers:
            original_config["env_http_headers_redacted"] = redacted_headers
        deferred[name] = {
            "reason": "http-transport",
            "original_config": original_config,
        }
        preview_def.append(f"  + {name} (reason=http-transport, credentials redacted)")
        continue

    # target
    if codex and claude:
        target = "all"
    elif codex:
        target = "codex"
    else:
        target = "claude"

    # enabled: false if codex disabled (MCP_DOCKER merge rule)
    enabled = True
    if codex and codex.get("enabled") is False:
        enabled = False

    src = codex if codex else claude
    command = src["command"]
    args = src["args"]
    env = src.get("env", {})

    # description heuristic
    if "tsh" in command:
        desc = "Use for authorized Teleport MCP operations."
    elif command == "docker":
        desc = "Use for Docker MCP gateway operations."
    else:
        desc = f"Use for {name} MCP operations."

    registry[name] = {
        "enabled": enabled,
        "description": desc,
        "transport": "stdio",
        "command": command,
        "args": args,
        "env": env,
        "target": target,
    }
    preview_reg.append(f"  + {name} (enabled={str(enabled).lower()}, target={target})")

reg_count = len(registry)
def_count = len(deferred)

if not apply:
    print(f"[bootstrap] Would write registry.json ({reg_count} entries)")
    for line in preview_reg:
        print(line)
    print(f"[bootstrap] Would write deferred.json ({def_count} entries)")
    for line in preview_def:
        print(line)
    print("[bootstrap] Pass --apply to write files.")
    sys.exit(0)

# ---- write files ----
def write_secure(path, data):
    content = json.dumps(data, indent=2) + "\n"
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600

write_secure(reg_file, {"version": 1, "unmanaged_mcp_servers": unmanaged, "personal_mcp_servers": registry})
write_secure(def_file, {"version": 1, "deferred": deferred})
write_secure(state_file, {"version": 1, "generated_files": []})

# validate registry parses cleanly
with open(reg_file) as f:
    json.load(f)

print(f"[bootstrap] registry.json written ({reg_count} entries)")
for line in preview_reg:
    print(line)
print(f"[bootstrap] deferred.json written ({def_count} entries)")
for line in preview_def:
    print(line)
print("[bootstrap] managed-state.json initialized")
print("[bootstrap] DONE")
PYEOF
}

# ---------------------------------------------------------------------------
# List / Get
# ---------------------------------------------------------------------------

registry_list() {
  local show_all=0
  for arg in "$@"; do
    case "$arg" in
      --all) show_all=1 ;;
      *) log_error "list: unknown option: $arg"; return 1 ;;
    esac
  done

  if [[ ! -f "$REGISTRY_FILE" ]]; then
    log_warn "registry.json not found. Run: mcp-agent-manager bootstrap"
    return 1
  fi
  local jq
  jq="$(require_jq)" || return 1
  printf '%-45s %-8s %-12s %-8s %s\n' "SLUG" "ENABLED" "STATUS" "TARGET" "DESCRIPTION"
  printf '%-45s %-8s %-12s %-8s %s\n' "----" "-------" "------" "------" "-----------"
  "$jq" -r --argjson show_all "$show_all" '
    .personal_mcp_servers
    | to_entries[]
    | select($show_all == 1 or .value.enabled == true)
    | [
        .key,
        (.value.enabled|tostring),
        (if .value._health.status == "quarantined" then "quarantined"
         elif .value._health.status == "healthy" then "healthy"
         elif .value.enabled == true then "active"
         else "disabled"
         end),
        .value.target,
        .value.description
      ]
    | @tsv' "$REGISTRY_FILE" \
  | while IFS='	' read -r name enabled status target desc; do
      printf '%-45s %-8s %-12s %-8s %s\n' "$name" "$enabled" "$status" "$target" "$desc"
    done
}

registry_get() {
  local name="${1:-}"
  if [[ -z "$name" ]]; then
    log_error "registry_get: missing name"; return 1
  fi
  if [[ ! -f "$REGISTRY_FILE" ]]; then
    log_warn "registry.json not found."; return 1
  fi
  local jq
  jq="$(require_jq)" || return 1
  "$jq" --arg name "$name" '.personal_mcp_servers[$name] // empty' "$REGISTRY_FILE"
}

registry_add() {
  # Bug 10: exit non-zero so callers can detect unimplemented
  printf '[registry] registry_add: not implemented\n' >&2; return 1
}

_registry_crud_backup() {
  local backup_dir="$1"
  mkdir -p "${REGISTRY_DIR}/backups" "$backup_dir"
  chmod 700 "$REGISTRY_DIR" "${REGISTRY_DIR}/backups" "$backup_dir"
  for f in "$REGISTRY_FILE" "$STATE_FILE"; do
    if [[ -f "$f" ]]; then
      cp "$f" "$backup_dir/"
      chmod 600 "${backup_dir}/$(basename "$f")"
    fi
  done
  if [[ -d "${REGISTRY_DIR}/tool-cache" ]]; then
    cp -R "${REGISTRY_DIR}/tool-cache" "${backup_dir}/tool-cache"
  else
    : > "${backup_dir}/tool-cache.absent"
  fi
  _apply_backup_generated "$backup_dir"
}

_registry_crud_restore() {
  local backup_dir="$1"
  _restore_one_file "${backup_dir}/registry.json" "$REGISTRY_FILE" || true
  _apply_restore_generated "$backup_dir"
  _restore_one_file "${backup_dir}/managed-state.json" "$STATE_FILE" || true
  rm -rf "${REGISTRY_DIR}/tool-cache"
  if [[ -d "${backup_dir}/tool-cache" ]]; then
    cp -R "${backup_dir}/tool-cache" "${REGISTRY_DIR}/tool-cache"
    chmod 700 "${REGISTRY_DIR}/tool-cache"
    find "${REGISTRY_DIR}/tool-cache" -type f -exec chmod 600 {} \;
  fi
}

registry_mutate_personal() {
  local action="$1"
  shift

  local apply=0 name=""
  for arg in "$@"; do
    case "$arg" in
      --apply) apply=1 ;;
      --*) log_error "${action}: unknown option: ${arg}"; return 1 ;;
      *)
        if [[ -n "$name" ]]; then
          log_error "${action}: expected one name"; return 1
        fi
        name="$arg"
        ;;
    esac
  done

  if [[ -z "$name" ]]; then
    log_error "${action}: missing name"
    return 1
  fi
  if [[ ! -f "$REGISTRY_FILE" ]]; then
    log_error "registry.json not found. Run: mcp-agent-manager bootstrap"
    return 1
  fi

  local jq
  jq="$(require_jq)" || return 1

  if ! "$jq" -e --arg name "$name" '.personal_mcp_servers | has($name)' "$REGISTRY_FILE" >/dev/null; then
    log_error "${action}: name not found: ${name}"
    return 1
  fi

  local source
  source=$("$jq" -r --arg name "$name" '
    .personal_mcp_servers[$name]
    | if has("_source") then ._source else empty end
  ' "$REGISTRY_FILE")
  if [[ -n "$source" ]]; then
    log_error "${action}: ${name} is managed by ${source}; use: mcp-agent-manager sync --apply"
    return 1
  fi

  local enabled
  enabled=$("$jq" -r --arg name "$name" '.personal_mcp_servers[$name].enabled == true' "$REGISTRY_FILE")
  if [[ "$action" == "enable" && "$enabled" == "true" ]]; then
    printf '[registry] NOOP: %s already enabled\n' "$name"
    return 0
  fi
  if [[ "$action" == "disable" && "$enabled" != "true" ]]; then
    printf '[registry] NOOP: %s already disabled\n' "$name"
    return 0
  fi

  local backup_dir=""
  if [[ $apply -eq 1 ]]; then
    backup_dir="${REGISTRY_DIR}/backups/$(date +%s)-crud-$$"
    _registry_crud_backup "$backup_dir" || return 1
  fi

  local rc=0
  python3 - "$REGISTRY_FILE" "$action" "$name" "$apply" <<'PYEOF' || rc=$?
import json
import os
import stat
import sys
import tempfile

reg_file, action, name, apply_flag = sys.argv[1:]
apply = apply_flag == "1"

with open(reg_file) as f:
    registry = json.load(f)

servers = registry.get("personal_mcp_servers", {})
entry = servers.get(name)
if entry is None:
    print(f"[ERROR] {action}: name not found: {name}", file=sys.stderr)
    sys.exit(1)
if "_source" in entry:
    print(
        f"[ERROR] {action}: {name} is managed by {entry.get('_source')}; "
        "use: mcp-agent-manager sync --apply",
        file=sys.stderr,
    )
    sys.exit(1)

current = bool(entry.get("enabled", False))
target = entry.get("target", "all")
agent_paths = []
if target in ("all", "claude"):
    agent_paths.append(os.path.expanduser(f"~/.claude/agents/mcp-managed-{name}.md"))
if target in ("all", "codex"):
    agent_paths.append(os.path.expanduser(f"~/.codex/agents/mcp-managed-{name}.toml"))
if action == "enable":
    if current:
        print(f"[registry] NOOP: {name} already enabled")
        sys.exit(3)
    entry["enabled"] = True
    change = "false -> true"
    impact = "add generated agent files"
elif action == "disable":
    if not current:
        print(f"[registry] NOOP: {name} already disabled")
        sys.exit(3)
    entry["enabled"] = False
    change = "true -> false"
    impact = "remove generated agent files"
elif action == "remove":
    del servers[name]
    change = "present -> removed"
    impact = "remove generated agent files" if current else "no active agent files"
else:
    print(f"[ERROR] unsupported registry mutation: {action}", file=sys.stderr)
    sys.exit(1)

print(f"[registry] {action.upper()}: {name} ({change})")
print(f"[registry] Agent impact: {impact}")
if action == "enable" or current:
    for path in agent_paths:
        print(f"  {'+' if action == 'enable' else '-'} {path}")
if not apply:
    print(f"[registry] Preview only. Run: mcp-agent-manager {action} {name} --apply")
    sys.exit(0)

content = json.dumps(registry, indent=2) + "\n"
json.loads(content)
reg_dir = os.path.dirname(os.path.abspath(reg_file))
fd, tmp_path = tempfile.mkstemp(dir=reg_dir, prefix=".registry_", suffix=".tmp")
try:
    os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.rename(tmp_path, reg_file)
except Exception:
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)
    raise
PYEOF

  if [[ $rc -eq 3 ]]; then
    return 0
  fi
  if [[ $rc -ne 0 ]]; then
    return "$rc"
  fi
  if [[ $apply -eq 0 ]]; then
    return 0
  fi

  log_info "[registry] Rendering generated agents..."
  if ! render_claude --preflight \
    || ! render_codex --preflight \
    || ! render_claude --apply \
    || ! render_codex --apply \
    || ! validate_claude \
    || ! validate_codex
  then
    log_error "[registry] Render or validation failed. Restoring scoped backup: ${backup_dir}"
    _registry_crud_restore "$backup_dir"
    return 1
  fi

  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  if ! python3 - "$script_dir/libexec" "$action" "$name" <<'PYEOF'
import sys

libexec_dir, action, name = sys.argv[1:]
sys.path.insert(0, libexec_dir)
from mcp_tool_cache import delete_cache, mark_stale

if action == "disable":
    mark_stale(name, "disabled")
elif action == "remove":
    delete_cache(name)
PYEOF
  then
    log_error "[registry] Tool cache update failed. Restoring scoped backup: ${backup_dir}"
    _registry_crud_restore "$backup_dir"
    return 1
  fi
  log_info "[registry] DONE: ${action} ${name}"
}

registry_enable() {
  registry_mutate_personal enable "$@"
}

registry_disable() {
  registry_mutate_personal disable "$@"
}

registry_remove() {
  registry_mutate_personal remove "$@"
}
