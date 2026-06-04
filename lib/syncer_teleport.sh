#!/usr/bin/env bash
# lib/syncer_teleport.sh — sync team MCP entries from Teleport catalog

_TELEPORT_PROXY="${TELEPORT_PROXY:-teleport.example.com}"
_TSH_BIN="${TSH_BIN:-tsh}"

# cmd_sync [--apply] [--target claude|codex|all]
# Sync Teleport MCP catalog into registry.json.
# Preview by default; mutate only with --apply.
# SECURITY: never log raw tsh mcp ls JSON output.
cmd_sync() {
  local apply=0
  local target="all"

  if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'USAGE'
Usage: mcp-agent-manager sync [--target all|claude|codex] [--apply]

Optional helper: sync Teleport MCP catalog into registry.json.
Preview by default. Mutation requires --apply.
Default target: all (Claude Code + Codex).
With --apply, smoke-test visible Teleport MCPs and quarantine unhealthy entries.

Requirements:
  - Teleport CLI: tsh
  - active Teleport login with MCP catalog access

Examples:
  mcp-agent-manager sync --target all
  mcp-agent-manager sync --apply --target all
USAGE
    return 0
  fi

  # Bug (--target parse): support both --target=value and --target value forms
  local i=1
  while [[ $i -le $# ]]; do
    local _arg="${!i}"
    case "$_arg" in
      --apply)       apply=1 ;;
      --target=*)    target="${_arg#--target=}" ;;
      --target)
        i=$((i+1))
        target="${!i:-all}"
        ;;
    esac
    i=$((i+1))
  done

  # Validate target value
  case "$target" in
    claude|codex|all) ;;
    *)
      log_error "sync: invalid --target value '${target}'. Use: claude, codex, or all"
      return 1
      ;;
  esac

  if [[ ! -f "$REGISTRY_FILE" ]]; then
    log_error "registry.json not found. Run: mcp-agent-manager bootstrap"
    return 1
  fi

  # Check tsh available
  if ! command -v "$_TSH_BIN" &>/dev/null; then
    log_error "tsh not found. Install Teleport client."
    return 1
  fi

  # Fetch catalog — suppress raw JSON (security: may contain rewrite headers)
  # Extract only server names via jq; never store/log raw output
  local catalog_names
  catalog_names=$(
    TELEPORT_DEBUG=false "$_TSH_BIN" mcp ls --format=json 2>/dev/null \
      | /usr/bin/jq -er '.[].metadata.name' 2>/dev/null
  ) || {
    log_error "tsh mcp ls failed — check Teleport login: tsh login --proxy=${_TELEPORT_PROXY}"
    return 1
  }

  if [[ -z "$catalog_names" ]]; then
    if [[ $apply -eq 1 ]]; then
      log_error "Empty catalog with --apply — aborting to prevent accidental mass-remove."
      return 1
    fi
    log_warn "Teleport catalog empty or no MCP servers visible."
    return 0
  fi

  # FIX: pass catalog names via temp file to avoid heredoc injection
  local tmp_catalog
  tmp_catalog=$(mktemp)
  chmod 600 "$tmp_catalog"
  printf '%s\n' "$catalog_names" > "$tmp_catalog"

  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

  python3 - \
    "$REGISTRY_FILE" \
    "$STATE_FILE" \
    "$apply" \
    "$target" \
    "$_TELEPORT_PROXY" \
    "$tmp_catalog" \
    "$script_dir/libexec" \
    "$_TSH_BIN" \
    <<'PYEOF'
import sys, json, os, stat, time, shutil, tempfile

# Validate arg count
if len(sys.argv) != 9:
    print(f"[ERROR] Expected 8 args, got {len(sys.argv)-1}", file=sys.stderr)
    sys.exit(1)

reg_file, state_file, apply_flag, target, proxy, catalog_file, libexec_dir, tsh_bin = sys.argv[1:]
apply = apply_flag == "1"
sys.path.insert(0, libexec_dir)
from mcp_health_gate import probe_teleport_stdio
from mcp_tool_cache import delete_cache, mark_stale, write_fresh

# Read catalog from temp file (safe — no shell interpolation)
with open(catalog_file) as f:
    catalog = [n.strip() for n in f if n.strip()]

with open(reg_file) as f:
    reg = json.load(f)

servers = reg.get("personal_mcp_servers", {})

health = {}
if apply:
    print("[sync:teleport] Running read-only health gate...")
    for catalog_name in catalog:
        health[catalog_name] = probe_teleport_stdio(name=catalog_name, proxy=proxy, tsh_bin=tsh_bin)
    healthy = [catalog_name for catalog_name in catalog if health[catalog_name]["status"] == "healthy"]
    quarantined = [catalog_name for catalog_name in catalog if health[catalog_name]["status"] == "quarantined"]
    print(f"[sync:teleport] HEALTHY ({len(healthy)})")
    for catalog_name in healthy:
        print(f"  ✓ teleport-{catalog_name}")
    print(f"[sync:teleport] QUARANTINED ({len(quarantined)})")
    for catalog_name in quarantined:
        print(f"  ! teleport-{catalog_name} — {health[catalog_name]['error']}")

# Classify catalog entries vs registry
adds = []
updates = []
removes = []

renames = []  # (old_name, new_name, entry)

for catalog_name in catalog:
    name = "teleport-" + catalog_name
    entry = servers.get(name)

    new_entry = {
        "enabled": health.get(catalog_name, {}).get("status") == "healthy" if apply else True,
        "description": f"Use for authorized Teleport MCP operations via {name}.",
        "transport": "stdio",
        "command": "tsh",
        "args": ["mcp", "connect", f"--proxy={proxy}", name],
        "env": {},
        "target": target,
        "_source": "teleport",
    }
    if apply:
        new_entry["_health"] = {k: v for k, v in health[catalog_name].items() if k != "tools"}

    if entry is None:
        # Bug 8: check for legacy bootstrap name (double mcp- prefix)
        # bootstrap may have imported key as teleport-mcp-<name> if Codex config used that format
        legacy_name = "teleport-mcp-" + name
        if legacy_name in servers:
            renamed_entry = dict(new_entry)
            renamed_entry["_renamed_from"] = legacy_name
            renames.append((legacy_name, name, renamed_entry))
        else:
            adds.append((name, new_entry))
    else:
        # Strip metadata fields for comparison
        current = {k: v for k, v in entry.items() if k not in ("_source", "_removed_from_catalog", "_renamed_from", "_health")}
        desired = {k: v for k, v in new_entry.items() if k not in ("_source", "_removed_from_catalog")}
        if apply:
            current["_health"] = entry.get("_health")
        if current != desired:
            updates.append((name, new_entry, entry))

# Find registry entries sourced from teleport but no longer in catalog
catalog_names = {"teleport-" + n for n in catalog}

for name, entry in servers.items():
    if entry.get("_source") == "teleport" and name not in catalog_names:
        removes.append(name)

# Print diff
print(f"[sync:teleport] Catalog: {len(catalog)} server(s)")
if renames:
    print(f"[sync:teleport] RENAME/RECONCILE ({len(renames)}) — legacy name → canonical:")
    for old, new, _ in renames:
        print(f"  >> {old} -> {new}")
if adds:
    print(f"[sync:teleport] ADD ({len(adds)}):")
    for name, _ in adds:
        print(f"  + {name}")
if updates:
    print(f"[sync:teleport] UPDATE ({len(updates)}):")
    for name, _, _ in updates:
        print(f"  ~ {name}")
if removes:
    print(f"[sync:teleport] REMOVE ({len(removes)}) — no longer in catalog:")
    for name in removes:
        print(f"  - {name}")
if not renames and not adds and not updates and not removes:
    print("[sync:teleport] Registry already up to date.")

if not apply:
    print("[sync:teleport] Preview only. Health gate runs during --apply.")
    print("[sync:teleport] Pass --apply to mutate registry.")
    sys.exit(0)

# Apply mutations
# Bug 8: rename legacy names first
for old_name, new_name, renamed_entry in renames:
    del servers[old_name]
    servers[new_name] = renamed_entry
    print(f"[sync:teleport] Renamed: {old_name} -> {new_name}")

for name, entry in adds:
    servers[name] = entry

for name, new_entry, _ in updates:
    servers[name] = new_entry

for name in removes:
    del servers[name]

reg["personal_mcp_servers"] = servers

# Validate content BEFORE touching disk
content = json.dumps(reg, indent=2) + "\n"
json.loads(content)  # raises if malformed

# Backup registry before write — mode 0700 directory, chmod copied file
backup_dir = os.path.expanduser(f"~/.config/mcp-agent-manager/backups/{int(time.time())}")
backup_root = os.path.dirname(backup_dir)
os.makedirs(backup_root, mode=0o700, exist_ok=True)
os.chmod(backup_root, 0o700)
os.makedirs(backup_dir, mode=0o700, exist_ok=True)
os.chmod(backup_dir, 0o700)  # enforce even if dir already existed
shutil.copy2(reg_file, backup_dir)
os.chmod(os.path.join(backup_dir, os.path.basename(reg_file)), stat.S_IRUSR | stat.S_IWUSR)

# Atomic write: tempfile with restricted perms, then rename
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

if apply:
    for catalog_name in catalog:
        name = "teleport-" + catalog_name
        entry = servers[name]
        if health[catalog_name]["status"] == "healthy":
            write_fresh(name, entry, health[catalog_name].get("tools", []))
        else:
            mark_stale(name, "quarantined")
    for name in removes:
        delete_cache(name)
    for old_name, new_name, _renamed_entry in renames:
        if old_name != new_name:
            delete_cache(old_name)

print(f"[sync:teleport] registry.json updated (backup in {backup_dir})")
print("[sync:teleport] DONE — run: mcp-agent-manager render --apply")
PYEOF

  local rc=$?
  rm -f "$tmp_catalog"
  return $rc
}
