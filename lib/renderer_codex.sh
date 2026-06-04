#!/usr/bin/env bash
# lib/renderer_codex.sh — render ~/.codex/agents/mcp-managed-<name>.toml

CODEX_AGENTS_DIR="${HOME}/.codex/agents"
_CODEX_GENERATED_MARKER="# mcp-agent-manager:generated"

# render_codex [--apply]
# Preview or write Codex agent TOML files from registry.
render_codex() {
  local apply=0 preflight=0
  for arg in "$@"; do
    [[ "$arg" == "--apply" ]] && apply=1
    [[ "$arg" == "--preflight" ]] && preflight=1
  done

  if [[ ! -f "$REGISTRY_FILE" ]]; then
    log_error "registry.json not found. Run: mcp-agent-manager bootstrap"
    return 1
  fi

  mkdir -p "$CODEX_AGENTS_DIR"

  # Absolute path to CLI binary — generated agents call this wrapper (Bug 2)
  local cli_bin
  cli_bin="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/bin/mcp-agent-manager"

  python3 - \
    "$REGISTRY_FILE" \
    "$STATE_FILE" \
    "$CODEX_AGENTS_DIR" \
    "$apply" \
    "$preflight" \
    "$cli_bin" \
    <<'PYEOF'
import sys, json, os, stat, shutil, time, tempfile

reg_file, state_file, agents_dir, apply_flag, preflight_flag, cli_bin = sys.argv[1:]
apply = apply_flag == "1"
preflight = preflight_flag == "1"
MARKER = "# mcp-agent-manager:generated"

agents_dir = os.path.realpath(os.path.expanduser(agents_dir))
registry_root = os.path.dirname(os.path.realpath(reg_file))

with open(reg_file) as f:
    reg = json.load(f)

with open(state_file) as f:
    state = json.load(f)

generated = set(state.get("generated_files", []))
new_files = []
preview = []
errors = 0

servers = reg.get("personal_mcp_servers", {})

def load_site_map(root_dir):
    candidates = []
    env_path = os.environ.get("MCP_AGENT_MANAGER_SITE_MAP", "").strip()
    if env_path:
        candidates.append(env_path)
    candidates.append(os.path.join(root_dir, "site-map.json"))
    for candidate in candidates:
        if not candidate:
            continue
        path = os.path.abspath(os.path.expanduser(candidate))
        if not os.path.isfile(path):
            continue
        with open(path) as f:
            raw = json.load(f)
        site_map = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                if not isinstance(value, dict):
                    continue
                site_map[str(key).upper()] = {
                    "alias": str(value.get("alias", "")).strip(),
                    "name": str(value.get("name", "")).strip(),
                }
        return site_map
    return {}


site_map = load_site_map(registry_root)

def routing_description(name, entry):
    lower = name.lower()
    if "grafana" in lower:
        return "Use proactively for Grafana dashboards, Prometheus metrics, Loki logs, alerts, incidents, and on-call operations."
    if "n8n" in lower:
        return "Use proactively for n8n workflows, executions, automation debugging, and authorized workflow operations."
    if "openstack" in lower:
        site = lower.rsplit("-", 1)[-1].upper()
        alias = site_map.get(site, {}).get("alias", "")
        alias_hint = f" Topology alias {alias} maps to site {site}; {alias} inside a compute hostname is not an MCP name." if alias else ""
        return f"Use proactively for authorized OpenStack operations in site {site} only.{alias_hint} Ask user to specify site when missing. Use read-only operations by default for inventory and reports."
    if "notebooklm" in lower:
        return "Use proactively for grounded NotebookLM research and source-backed answers."
    if "obsidian" in lower:
        return "Use proactively for reading, searching, and updating authorized Obsidian vault notes."
    if "caveman" in lower:
        return "Use proactively for caveman text and context compression operations."
    return entry.get("description", f"Use for {name} MCP operations.")

# Preflight all paths before writes. Prevent cross-renderer partial mutation and
# keep stale marker violations tracked for manual cleanup.
desired_paths = set()
for name, entry in servers.items():
    if entry.get("enabled", False) and entry.get("target", "all") in ("all", "codex"):
        desired_paths.add(os.path.join(agents_dir, f"mcp-managed-{name}.toml"))

old_codex_files = {
    p for p in generated if os.path.dirname(os.path.realpath(p)) == agents_dir
}
for out_path in sorted(desired_paths):
    if not os.path.exists(out_path):
        continue
    if out_path not in generated:
        print(f"[render:codex] ERROR: {out_path} exists but is not tracked — refusing to overwrite. Remove manually.", file=sys.stderr)
        errors += 1
        continue
    with open(out_path) as f:
        if MARKER not in f.read():
            print(f"[render:codex] ERROR: {out_path} missing managed marker — refusing to overwrite.", file=sys.stderr)
            errors += 1

for stale_path in sorted(old_codex_files - desired_paths):
    if os.path.exists(stale_path):
        with open(stale_path) as f:
            if MARKER not in f.read():
                print(f"[render:codex] ERROR: stale {stale_path} missing managed marker — refusing to drop tracking.", file=sys.stderr)
                errors += 1

if errors:
    print(f"[render:codex] {errors} preflight error(s).", file=sys.stderr)
    sys.exit(1)
if preflight:
    print("[render:codex] Preflight passed.")
    sys.exit(0)

for name, entry in servers.items():
    if not entry.get("enabled", False):
        continue
    target = entry.get("target", "all")
    if target not in ("all", "codex"):
        continue

    description = routing_description(name, entry)
    openstack_hint = ""
    if "openstack" in name.lower():
        site = name.lower().rsplit("-", 1)[-1].upper()
        alias = site_map.get(site, {}).get("alias", "")
        if alias:
            openstack_hint = f"Treat topology alias {alias} inside hostnames as site {site}, not as an MCP name. Use read-only operations by default for inventory and reports."

    # TOML-safe name: replace hyphens with underscores
    safe_name = name.replace("-", "_")

    # Bug 2: use run wrapper — agent calls mcp-agent-manager run <name>
    # Bug 12: use json.dumps for proper TOML string escaping
    desc_safe = json.dumps(description)
    cmd_safe = json.dumps(cli_bin)
    # args: inline TOML array
    args_toml = '["run", ' + json.dumps(name) + ']'

    content = f"""{MARKER}
# name: {name}
# DO NOT EDIT — managed by mcp-agent-manager

name = "mcp-managed-{safe_name}"
description = {desc_safe}
developer_instructions = \"\"\"
MCP-managed agent for {name}.
This agent has access to the {name} MCP server via STDIO transport.
Start via: mcp-agent-manager run {name}
Use only this scoped MCP server. Never expose secrets or sensitive headers.
{openstack_hint}
\"\"\"

[mcp_servers.{safe_name}]
command = {cmd_safe}
args = {args_toml}
"""

    out_path = os.path.join(agents_dir, f"mcp-managed-{name}.toml")
    preview.append((name, out_path))
    new_files.append(out_path)

    if apply:
        # Bug 4: abort if file exists but untracked or missing marker
        if os.path.exists(out_path):
            if out_path not in generated:
                print(
                    f"[render:codex] ERROR: {out_path} exists but is not tracked — "
                    f"refusing to overwrite. Remove manually.",
                    file=sys.stderr,
                )
                errors += 1
                continue
            with open(out_path) as f:
                existing_content = f.read()
            if MARKER not in existing_content:
                print(
                    f"[render:codex] ERROR: {out_path} missing managed marker — "
                    f"refusing to overwrite.",
                    file=sys.stderr,
                )
                errors += 1
                continue
            # Backup tracked managed file before overwrite
            backup_dir = os.path.expanduser(
                f"~/.config/mcp-agent-manager/backups/{int(time.time())}"
            )
            backup_root = os.path.dirname(backup_dir)
            os.makedirs(backup_root, mode=0o700, exist_ok=True)
            os.chmod(backup_root, 0o700)
            os.makedirs(backup_dir, mode=0o700, exist_ok=True)
            os.chmod(backup_dir, 0o700)
            dest = os.path.join(backup_dir, os.path.basename(out_path))
            shutil.copy2(out_path, dest)
            os.chmod(dest, 0o600)

        # Atomic write
        d = os.path.dirname(os.path.abspath(out_path))
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".codex_agent_", suffix=".tmp")
        try:
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(fd, "w") as f:
                f.write(content)
            os.rename(tmp, out_path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

if apply and errors:
    print(f"[render:codex] {errors} error(s) — aborting state update.", file=sys.stderr)
    sys.exit(1)

if not apply:
    print(f"[render:codex] Would write {len(preview)} agent file(s):")
    for name, path in preview:
        print(f"  + {path}")
    print("[render:codex] Pass --apply to write files.")
else:
    new_files_set = set(new_files)
    # Bug 5: compute stale files (old codex files no longer desired)
    stale = old_codex_files - new_files_set
    for stale_path in sorted(stale):
        if os.path.exists(stale_path):
            with open(stale_path) as f:
                stale_content = f.read()
            if MARKER in stale_content:
                os.unlink(stale_path)
                print(f"[render:codex] Removed stale: {stale_path}")
            else:
                raise RuntimeError(f"stale file lost marker after preflight: {stale_path}")

    # Update managed-state: keep non-codex entries, add new codex entries
    existing_non_codex = {p for p in generated if os.path.dirname(os.path.realpath(p)) != agents_dir}
    updated = sorted(existing_non_codex | new_files_set)
    state["generated_files"] = updated

    # Atomic write for state
    d = os.path.dirname(os.path.abspath(state_file))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".state_", suffix=".tmp")
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
        os.rename(tmp, state_file)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    print(f"[render:codex] Written {len(new_files)} agent file(s):")
    for name, path in preview:
        print(f"  + {path}")
    if stale:
        print(f"[render:codex] Removed {len(stale)} stale file(s)")
    print("[render:codex] managed-state.json updated")
PYEOF
}

# validate_codex — check generated .toml files have valid marker + mcp_servers section
# Bug 3: use exact directory comparison (not substring) to find codex agents
validate_codex() {
  if [[ ! -f "$STATE_FILE" ]]; then
    log_warn "managed-state.json not found"; return 1
  fi
  python_toml - "$STATE_FILE" "$CODEX_AGENTS_DIR" <<'PYEOF'
import sys, json, os, re

state_file, agents_dir = sys.argv[1:]
# Bug 3: realpath so symlinks resolve consistently
agents_dir = os.path.realpath(os.path.expanduser(agents_dir))

with open(state_file) as f:
    state = json.load(f)

errors = 0
found = 0
for path in state.get("generated_files", []):
    # Bug 3: exact parent directory comparison, not substring
    if os.path.dirname(os.path.realpath(path)) != agents_dir:
        continue
    found += 1
    if not os.path.exists(path):
        print(f"[validate:codex] MISSING {path}")
        errors += 1
        continue
    with open(path) as f:
        content = f.read()
    if "# mcp-agent-manager:generated" not in content:
        print(f"[validate:codex] MISSING MARKER {path}")
        errors += 1
        continue
    if not re.search(r'^\[mcp_servers\.\w+\]', content, re.MULTILINE):
        print(f"[validate:codex] MISSING mcp_servers section {path}")
        errors += 1
        continue
    # Validate TOML parses cleanly — strip comment lines first
    try:
        import tomllib
        clean = "\n".join(l for l in content.splitlines() if not l.startswith("#"))
        tomllib.loads(clean)
    except Exception as e:
        print(f"[validate:codex] TOML PARSE ERROR {path}: {e}")
        errors += 1
        continue
    print(f"[validate:codex] ✓ {os.path.basename(path)}")

if found == 0:
    print("[validate:codex] No codex agent files tracked — nothing to validate")

if errors:
    sys.exit(1)
PYEOF
}
