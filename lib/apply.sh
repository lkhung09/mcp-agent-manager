#!/usr/bin/env bash
# lib/apply.sh — full 7-step apply flow
#
# Steps:
#  1. Backup parent configs + state + generated files (mode 0600/0700)
#  2. Render registry → specialized agent files
#  3. Validate JSON/TOML/frontmatter/permissions
#  4. Smoke test active STDIO wrappers
#  5. Remove MCP global entries from ~/.codex/config.toml and ~/.claude.json
#  6. Verify parent configs parse clean
#  7. Auto restore backup if any step fails

_APPLY_CODEX_CONFIG="${HOME}/.codex/config.toml"
_APPLY_CLAUDE_CONFIG="${HOME}/.claude.json"

# cmd_apply [--apply]
# Full apply flow. Preview by default; mutate parent configs only with --apply.
cmd_apply() {
  local apply=0 allow_smoke_warn=0
  for arg in "$@"; do
    [[ "$arg" == "--apply" ]] && apply=1
    [[ "$arg" == "--allow-smoke-warn" ]] && allow_smoke_warn=1
  done

  if [[ ! -f "$REGISTRY_FILE" ]]; then
    log_error "registry.json not found. Run: mcp-agent-manager bootstrap"
    return 1
  fi

  if [[ $apply -eq 0 ]]; then
    log_info "[apply] Preview mode — pass --apply to execute full flow"
    _apply_preview
    return $?
  fi

  log_info "[apply] Starting full apply flow..."

  # Track backup dir for auto-restore
  local backup_ts
  backup_ts="$(date +%s)-$$"
  local backup_dir="${REGISTRY_DIR}/backups/${backup_ts}"
  while [[ -e "$backup_dir" ]]; do
    backup_dir="${REGISTRY_DIR}/backups/${backup_ts}-${RANDOM:-0}"
  done

  # Wrap entire flow — auto-restore on any failure
  if ! _apply_run "$backup_dir" "$allow_smoke_warn"; then
    log_error "[apply] Step failed. Restoring backups from: ${backup_dir}"
    _apply_restore "$backup_dir"
    return 1
  fi

  log_info "[apply] DONE — all 7 steps completed successfully."
}

# ---------------------------------------------------------------------------
# Preview — dry-run, no mutations
# ---------------------------------------------------------------------------

_apply_preview() {
  log_info "[apply:preview] Step 1: Backup parent configs"
  for f in "$_APPLY_CODEX_CONFIG" "$_APPLY_CLAUDE_CONFIG" "$REGISTRY_FILE" "$STATE_FILE"; do
    [[ -f "$f" ]] && log_info "  would backup: $f"
  done
  log_info "  would snapshot all managed generated files"

  log_info "[apply:preview] Step 2: Render agent files"
  render_claude
  render_codex

  log_info "[apply:preview] Step 3: Validate (dry-run)"
  validate_claude || true
  validate_codex || true

  log_info "[apply:preview] Step 4: Smoke test (preview — not run)"
  _apply_list_smoke_targets

  log_info "[apply:preview] Steps 5-6: Remove globals from parent configs (preview)"
  _apply_preview_removals

  log_info "[apply:preview] Pass --apply to execute."
}

_apply_list_smoke_targets() {
  local jq
  jq="$(require_jq)" || return 1
  "$jq" -r '
    .personal_mcp_servers
    | to_entries[]
    | select(.value.enabled == true and .value.transport == "stdio")
    | "  would smoke-test: \(.key)"
  ' "$REGISTRY_FILE"
}

_apply_preview_removals() {
  python_toml - "$_APPLY_CODEX_CONFIG" "$_APPLY_CLAUDE_CONFIG" "$REGISTRY_FILE" "$DEFERRED_FILE" <<'PYEOF'
import sys, json, os

codex_toml, claude_json, reg_file, def_file = sys.argv[1:]

with open(reg_file) as f:
    reg = json.load(f)

# Bug 7: union registry + deferred names
managed = set(reg.get("personal_mcp_servers", {}).keys())
managed |= {
    entry["_renamed_from"]
    for entry in reg.get("personal_mcp_servers", {}).values()
    if entry.get("_renamed_from")
}
managed -= set(reg.get("unmanaged_mcp_servers", []))
if os.path.exists(def_file):
    with open(def_file) as f:
        def_data = json.load(f)
    managed |= set(def_data.get("deferred", {}).keys())

# Show what would be removed from claude.json
if os.path.exists(claude_json):
    with open(claude_json) as f:
        data = json.load(f)
    in_claude = set(data.get("mcpServers", {}).keys())
    for name in sorted(managed & in_claude):
        print(f"  would remove from claude.json: {name}")
else:
    print(f"  {claude_json}: not found (skip)")

# Show what would be removed from codex config.toml
if os.path.exists(codex_toml):
    try:
        import tomllib
        with open(codex_toml, "rb") as f:
            cfg = tomllib.load(f)
        in_codex = set(cfg.get("mcp_servers", {}).keys())
        for name in sorted(managed & in_codex):
            print(f"  would remove from config.toml: {name}")
    except Exception as e:
        print(f"  [warn] Could not parse {codex_toml}: {e}")
else:
    print(f"  {codex_toml}: not found (skip)")
PYEOF
}

# ---------------------------------------------------------------------------
# Full apply run
# ---------------------------------------------------------------------------

_apply_run() {
  local backup_dir="$1"
  local allow_smoke_warn="${2:-0}"

  # Step 1 — Backup parent configs + state + generated files
  log_info "[apply:1/7] Backing up parent configs and state..."
  mkdir -p "${REGISTRY_DIR}/backups"
  chmod 700 "$REGISTRY_DIR" "${REGISTRY_DIR}/backups"
  mkdir -p "$backup_dir"
  chmod 700 "$backup_dir"
  for f in "$_APPLY_CODEX_CONFIG" "$_APPLY_CLAUDE_CONFIG" "$REGISTRY_FILE" "$STATE_FILE"; do
    if [[ -f "$f" ]]; then
      cp "$f" "$backup_dir/"
      chmod 600 "${backup_dir}/$(basename "$f")"
      log_info "  backed up: $f"
    fi
  done
  # Bug 6: snapshot all managed generated files before render
  _apply_backup_generated "$backup_dir" || return 1

  # Step 2 — Render agent files
  log_info "[apply:2/7] Rendering agent files..."
  render_claude --preflight || return 1
  render_codex --preflight || return 1
  render_claude --apply || return 1
  render_codex --apply || return 1

  # Step 3 — Validate generated files
  log_info "[apply:3/7] Validating generated files..."
  validate_claude || return 1
  validate_codex || return 1
  log_info "  validation passed"

  # Step 4 — Smoke test active STDIO wrappers
  log_info "[apply:4/7] Smoke testing STDIO wrappers..."
  _apply_smoke_test "$allow_smoke_warn" || return 1

  # Step 5 — Remove MCP globals from parent configs
  log_info "[apply:5/7] Removing MCP globals from parent configs..."
  _apply_remove_globals || return 1

  # Step 6 — Verify parent configs parse clean
  log_info "[apply:6/7] Verifying parent configs parse clean..."
  _apply_verify_configs || return 1

  # Step 7 — success (no rollback needed)
  log_info "[apply:7/7] All steps passed."
  return 0
}

# ---------------------------------------------------------------------------
# Step 1 helper: snapshot generated files before render
# ---------------------------------------------------------------------------

_apply_backup_generated() {
  local backup_dir="$1"
  python3 - "$STATE_FILE" "$backup_dir" <<'PYEOF'
import sys, json, os, shutil, stat, hashlib

state_file, backup_dir = sys.argv[1:]

if not os.path.exists(state_file):
    sys.exit(0)

with open(state_file) as f:
    state = json.load(f)

gen_dir = os.path.join(backup_dir, "generated")
os.makedirs(gen_dir, mode=0o700, exist_ok=True)
os.chmod(gen_dir, 0o700)

manifest = {}
for path in state.get("generated_files", []):
    if os.path.exists(path):
        # Unique key avoids name collision between claude/codex dirs
        key = hashlib.md5(path.encode()).hexdigest()[:8] + "_" + os.path.basename(path)
        dest = os.path.join(gen_dir, key)
        shutil.copy2(path, dest)
        os.chmod(dest, 0o600)
        manifest[path] = key

manifest_path = os.path.join(backup_dir, "generated-manifest.json")
with open(manifest_path, "w") as f:
    json.dump(manifest, f, indent=2)
os.chmod(manifest_path, 0o600)

print(f"[apply:1/7] Snapshotted {len(manifest)} generated file(s)")
PYEOF
}

# ---------------------------------------------------------------------------
# Step 4: Smoke test
# Bug 1: command-not-found is always FATAL. Other smoke failures are FATAL by
# default; explicit --allow-smoke-warn permits them during controlled cutover.
# ---------------------------------------------------------------------------

_apply_smoke_test() {
  local allow_smoke_warn="${1:-0}"
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  python3 - "$REGISTRY_FILE" "$allow_smoke_warn" "$script_dir/libexec" <<'PYEOF'
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

reg_file, allow_smoke_warn_flag, libexec_dir = sys.argv[1:]
allow_smoke_warn = allow_smoke_warn_flag == "1"
sys.path.insert(0, libexec_dir)
from mcp_stdio_client import MCPClientError, MCPStdioClient, load_export_env  # noqa: E402

with open(reg_file) as f:
    reg = json.load(f)

targets = [
    (name, entry)
    for name, entry in reg.get("personal_mcp_servers", {}).items()
    if entry.get("enabled") and entry.get("transport") == "stdio"
]

if not targets:
    print("[smoke] No enabled STDIO targets to test.")
    sys.exit(0)

root = Path.home() / ".config" / "mcp-agent-manager"
runtime_env = os.environ.copy()
runtime_env.update(load_export_env(root / "secrets.env"))

fatal_errors = 0
soft_errors = 0

def materialize_env(entry):
    env = dict(runtime_env)
    for key, value in entry.get("env", {}).items():
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            ref = value[2:-1]
            if ref not in env:
                raise MCPClientError(f"env reference '{value}' not set")
            env[key] = env[ref]
        else:
            env[key] = str(value)
    return env

for name, entry in targets:
    command = entry["command"]
    args = list(entry.get("args", []))
    if not shutil.which(command) and not os.path.isfile(command):
        print(f"[smoke] ✗ FATAL {name} — command not found: {command}", file=sys.stderr)
        fatal_errors += 1
        continue

    client = None
    try:
        init_timeout = float(os.environ.get("MCP_AGENT_MANAGER_INIT_TIMEOUT", "8"))
        client = MCPStdioClient(command=command, args=args, env=materialize_env(entry), timeout=init_timeout, initialize_timeout=init_timeout)
        client.open()
        tools = client.list_tools()
        if isinstance(tools, list):
            print(f"[smoke] ✓ {name}")
            continue
        raise MCPClientError("tools/list returned invalid payload")
    except Exception as exc:
        soft_errors += 1
        print(f"[smoke] ✗ {'WARN' if allow_smoke_warn else 'FATAL'} {name} — {exc}")
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

if fatal_errors:
    print(f"[smoke] {fatal_errors} FATAL error(s) — commands not found. Fix before apply.", file=sys.stderr)
    sys.exit(1)
if soft_errors and not allow_smoke_warn:
    print(f"[smoke] {soft_errors} FATAL smoke error(s). Fix before apply or use explicit --allow-smoke-warn.", file=sys.stderr)
    sys.exit(1)
if soft_errors:
    print(f"[smoke] {soft_errors} warning(s) explicitly allowed by --allow-smoke-warn.")
PYEOF
}

# ---------------------------------------------------------------------------
# Step 5: Remove MCP globals from parent configs
# Bug 7: remove both registry AND deferred names
# ---------------------------------------------------------------------------

_apply_remove_globals() {
  python_toml - \
    "$_APPLY_CODEX_CONFIG" \
    "$_APPLY_CLAUDE_CONFIG" \
    "$REGISTRY_FILE" \
    "$DEFERRED_FILE" \
    <<'PYEOF'
import sys, json, os, stat, tomllib, tempfile

if len(sys.argv) != 5:
    print(f"[ERROR] Expected 4 args, got {len(sys.argv)-1}", file=sys.stderr)
    sys.exit(1)

codex_toml, claude_json, reg_file, def_file = sys.argv[1:]

with open(reg_file) as f:
    reg = json.load(f)

# Bug 7: union registry + deferred names for removal
managed = set(reg.get("personal_mcp_servers", {}).keys())
managed |= {
    entry["_renamed_from"]
    for entry in reg.get("personal_mcp_servers", {}).values()
    if entry.get("_renamed_from")
}
managed -= set(reg.get("unmanaged_mcp_servers", []))
if os.path.exists(def_file):
    with open(def_file) as f:
        def_data = json.load(f)
    managed |= set(def_data.get("deferred", {}).keys())

# ---- Remove from claude.json ----
if os.path.exists(claude_json):
    with open(claude_json) as f:
        data = json.load(f)
    mcp_servers = data.get("mcpServers", {})
    removed = [k for k in list(mcp_servers.keys()) if k in managed]
    for k in removed:
        del mcp_servers[k]
    data["mcpServers"] = mcp_servers

    content = json.dumps(data, indent=2) + "\n"
    json.loads(content)  # validate before write

    # Atomic write
    d = os.path.dirname(os.path.abspath(claude_json))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".claude_", suffix=".tmp")
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.rename(tmp, claude_json)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    for k in removed:
        print(f"[apply:remove] claude.json: removed {k}")
    if not removed:
        print(f"[apply:remove] claude.json: nothing to remove")

# ---- Remove from codex config.toml ----
if os.path.exists(codex_toml):
    with open(codex_toml, "rb") as f:
        cfg = tomllib.load(f)

    mcp_section = cfg.get("mcp_servers", {})
    removed_codex = [k for k in list(mcp_section.keys()) if k in managed]

    if removed_codex:
        # Line-by-line section removal — safer than full TOML re-serialization
        with open(codex_toml) as f:
            lines = f.readlines()

        def split_toml_header(section):
            parts = []
            current = []
            in_quote = False
            quote = ""
            escaped = False
            for ch in section:
                if escaped:
                    current.append(ch)
                    escaped = False
                    continue
                if in_quote:
                    if ch == "\\":
                        escaped = True
                        current.append(ch)
                    elif ch == quote:
                        in_quote = False
                    else:
                        current.append(ch)
                    continue
                if ch in ("'", '"'):
                    in_quote = True
                    quote = ch
                    continue
                if ch == ".":
                    parts.append("".join(current).strip())
                    current = []
                    continue
                current.append(ch)
            parts.append("".join(current).strip())
            return parts

        result = []
        skip = False
        for line in lines:
            stripped = line.strip()
            # Start of a section header — ALWAYS re-evaluate skip flag
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped[1:-1].strip()
                parts = split_toml_header(section)
                is_managed = (
                    len(parts) >= 2
                    and parts[0] == "mcp_servers"
                    and parts[1] in removed_codex
                )
                skip = is_managed  # reset on EVERY section header
            if not skip:
                result.append(line)

        content = "".join(result).rstrip("\n") + "\n"

        # Validate result parses clean before write
        tomllib.loads(content)

        # Atomic write
        d = os.path.dirname(os.path.abspath(codex_toml))
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".codex_", suffix=".tmp")
        try:
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(fd, "w") as f:
                f.write(content)
            os.rename(tmp, codex_toml)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

        for k in removed_codex:
            print(f"[apply:remove] config.toml: removed {k}")
    else:
        print("[apply:remove] config.toml: nothing to remove")
PYEOF
}

# ---------------------------------------------------------------------------
# Step 6: Verify parent configs parse clean
# ---------------------------------------------------------------------------

_apply_verify_configs() {
  python_toml - "$_APPLY_CODEX_CONFIG" "$_APPLY_CLAUDE_CONFIG" <<'PYEOF'
import sys, json, os, tomllib

codex_toml, claude_json = sys.argv[1:]
errors = 0

if os.path.exists(claude_json):
    try:
        with open(claude_json) as f:
            json.load(f)
        print(f"[apply:verify] ✓ {claude_json}")
    except Exception as e:
        print(f"[apply:verify] FAIL {claude_json}: {e}")
        errors += 1

if os.path.exists(codex_toml):
    try:
        with open(codex_toml, "rb") as f:
            tomllib.load(f)
        print(f"[apply:verify] ✓ {codex_toml}")
    except Exception as e:
        print(f"[apply:verify] FAIL {codex_toml}: {e}")
        errors += 1

if errors:
    sys.exit(1)
PYEOF
}

# ---------------------------------------------------------------------------
# Auto-restore from backup
# Bug 6: also restore state + generated files
# Dotfile fix: explicit file list (glob doesn't match .claude.json)
# ---------------------------------------------------------------------------

_restore_one_file() {
  local src="$1" dest="$2"
  if [[ -f "$src" ]]; then
    cp "$src" "$dest"
    chmod 600 "$dest"
    log_info "[restore] Restored: ${dest}"
    return 0
  fi
  return 1
}

_apply_restore() {
  local backup_dir="$1"
  if [[ ! -d "$backup_dir" ]]; then
    log_error "[restore] Backup dir not found: ${backup_dir}"
    return 1
  fi

  local restored=0

  # Explicit file mapping — glob won't match dotfiles like .claude.json
  _restore_one_file "${backup_dir}/config.toml"          "$_APPLY_CODEX_CONFIG"  && restored=$((restored+1)) || true
  _restore_one_file "${backup_dir}/.claude.json"         "$_APPLY_CLAUDE_CONFIG" && restored=$((restored+1)) || true
  _restore_one_file "${backup_dir}/registry.json"        "$REGISTRY_FILE"        && restored=$((restored+1)) || true

  # Read post-render state first so newly-created generated files can be removed.
  _apply_restore_generated "$backup_dir"
  _restore_one_file "${backup_dir}/managed-state.json"   "$STATE_FILE"           && restored=$((restored+1)) || true

  if [[ $restored -eq 0 ]]; then
    log_warn "[restore] No config files restored from ${backup_dir}"
  else
    log_info "[restore] ${restored} config file(s) restored. Verify with: mcp-agent-manager doctor"
  fi
}

_apply_restore_generated() {
  local backup_dir="$1"
  python3 - "$STATE_FILE" "$backup_dir" <<'PYEOF'
import sys, json, os, shutil

state_file, backup_dir = sys.argv[1:]

manifest_path = os.path.join(backup_dir, "generated-manifest.json")
gen_dir = os.path.join(backup_dir, "generated")

if not os.path.exists(manifest_path):
    print("[restore] No generated-manifest.json — skip generated file restore")
    sys.exit(0)

with open(manifest_path) as f:
    manifest = json.load(f)

# Get current generated files (post-render state)
current_files = set()
if os.path.exists(state_file):
    with open(state_file) as f:
        state = json.load(f)
    current_files = set(state.get("generated_files", []))

pre_render_files = set(manifest.keys())
# Remove newly-created files (in current but not in pre-render snapshot)
newly_created = current_files - pre_render_files
for path in newly_created:
    if os.path.exists(path):
        with open(path) as f:
            content = f.read()
        if "mcp-agent-manager:generated" in content:
            os.unlink(path)
            print(f"[restore] Removed newly-created generated file: {path}")

# Restore pre-render generated files from snapshot
for orig_path, key in manifest.items():
    src = os.path.join(gen_dir, key)
    if os.path.exists(src):
        os.makedirs(os.path.dirname(orig_path), exist_ok=True)
        shutil.copy2(src, orig_path)
        os.chmod(orig_path, 0o600)
        print(f"[restore] Restored generated: {orig_path}")
PYEOF
}
