#!/usr/bin/env bash
# lib/doctor.sh — health checks for mcp-agent-manager

_DOCTOR_PASS=1
_MCP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_CANONICAL_SKILL_DIR="${_MCP_ROOT}/skill"
_LEGACY_RUNTIME_DIR="${HOME}/.local/share/agent-skills/mcp-agent-manager"

_doctor_ok() { printf '[doctor] ✓ %s\n' "$*"; }
_doctor_warn() { printf '[doctor] ⚠ %s\n' "$*"; }
_doctor_fail() { printf '[doctor] ✗ %s\n' "$*" >&2; _DOCTOR_PASS=0; }

_check_runtime_dirs() {
  local dirs=(
    "${HOME}/.config/mcp-agent-manager"
    "${HOME}/.config/mcp-agent-manager/backups"
    "${HOME}/.config/mcp-agent-manager/chat-runtime"
    "${HOME}/.config/mcp-agent-manager/tool-cache"
    "${HOME}/.claude/agents"
    "${HOME}/.codex/agents"
    "${HOME}/.agents/skills"
    "${HOME}/.claude/skills"
    "${HOME}/.codex/skills"
    "${HOME}/.local/bin"
  )
  for d in "${dirs[@]}"; do
    if [[ -d "$d" ]]; then
      _doctor_ok "directory present: ${d}"
    else
      _doctor_fail "missing directory: ${d}. Run: mcp-agent-manager install --apply"
    fi
  done
}

_check_jq() {
  if [[ ! -x /usr/bin/jq ]]; then
    _doctor_fail "jq not found at /usr/bin/jq"
    return
  fi
  _doctor_ok "jq /usr/bin/jq"
}

_check_tsh() {
  local tsh_path
  tsh_path="$(command -v tsh 2>/dev/null)"
  if [[ -z "$tsh_path" ]]; then
    _doctor_warn "tsh not found in PATH (optional; only needed for Teleport sync)"
    return
  fi
  local raw_ver
  raw_ver="$(tsh version 2>/dev/null | grep -oE 'Teleport v[0-9]+\.[0-9]+\.[0-9]+' | head -1 | sed 's/Teleport v//')"
  [[ -n "$raw_ver" ]] && _doctor_ok "tsh ${tsh_path} (v${raw_ver})" || _doctor_ok "tsh ${tsh_path}"
}

_check_claude() {
  local claude_path
  claude_path="$(command -v claude 2>/dev/null)"
  if [[ -z "$claude_path" ]]; then
    _doctor_warn "claude not found in PATH"
    return
  fi
  _doctor_ok "claude ${claude_path}"
}

_check_codex() {
  local codex_path
  codex_path="$(command -v codex 2>/dev/null)"
  if [[ -z "$codex_path" ]]; then
    _doctor_warn "codex not found in PATH"
    return
  fi
  _doctor_ok "codex ${codex_path}"
}

_check_agent_dirs() {
  local dirs=(
    "${HOME}/.claude/agents"
    "${HOME}/.codex/agents"
  )
  for d in "${dirs[@]}"; do
    if [[ ! -w "$d" ]]; then
      _doctor_fail "${d} is not writable"
    else
      _doctor_ok "${d}/ writable"
    fi
  done
}

_check_legacy_runtime_dir() {
  if [[ -e "$_LEGACY_RUNTIME_DIR" || -L "$_LEGACY_RUNTIME_DIR" ]]; then
    _doctor_fail "legacy runtime dir still exists: ${_LEGACY_RUNTIME_DIR}"
  else
    _doctor_ok "legacy runtime dir removed"
  fi
}

_check_skill_layout() {
  local required=(
    "${_CANONICAL_SKILL_DIR}/SKILL.md"
    "${_CANONICAL_SKILL_DIR}/agents/openai.yaml"
    "${_CANONICAL_SKILL_DIR}/references/operations.md"
    "${_CANONICAL_SKILL_DIR}/references/runtime-routing.md"
    "${_CANONICAL_SKILL_DIR}/references/claude-chat-runtime.md"
    "${_CANONICAL_SKILL_DIR}/references/troubleshooting.md"
  )
  local path
  for path in "${required[@]}"; do
    if [[ -f "$path" ]]; then
      _doctor_ok "skill file present: ${path}"
    else
      _doctor_fail "missing skill file: ${path}"
    fi
  done
}

_check_skill_metadata() {
  local metadata="${_CANONICAL_SKILL_DIR}/agents/openai.yaml"
  if python3 - "$metadata" <<'PYEOF'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text() if path.exists() else ""
required = (
    "interface:\n",
    "  display_name:",
    "  short_description:",
    "  default_prompt:",
)
if not all(token in text for token in required):
    raise SystemExit(1)
PYEOF
  then
    _doctor_ok "skill metadata shape valid"
  else
    _doctor_fail "invalid skill metadata shape: ${metadata}"
  fi
}

_check_skill_symlink() {
  local canonical_resolved
  canonical_resolved="$(realpath "$_CANONICAL_SKILL_DIR" 2>/dev/null || printf '%s' "$_CANONICAL_SKILL_DIR")"
  local required_symlinks=(
    "${HOME}/.claude/skills/mcp-agent-manager"
    "${HOME}/.agents/skills/mcp-agent-manager"
    "${HOME}/.codex/skills/mcp-agent-manager"
  )
  local link
  for link in "${required_symlinks[@]}"; do
    if [[ ! -e "$link" && ! -L "$link" ]]; then
      _doctor_fail "missing skill symlink: ${link}"
      continue
    fi
    local resolved
    resolved="$(readlink "$link" 2>/dev/null || realpath "$link" 2>/dev/null || true)"
    if [[ "$resolved" != "$canonical_resolved" ]]; then
      _doctor_fail "skill symlink ${link} does not resolve to canonical skill dir"
    else
      _doctor_ok "skill symlink ${link} → canonical"
    fi
  done
}

_check_cli_symlink() {
  local cli_link="${HOME}/.local/bin/mcp-agent-manager"
  local canonical_bin="${_MCP_ROOT}/bin/mcp-agent-manager"
  if [[ ! -e "$cli_link" && ! -L "$cli_link" ]]; then
    _doctor_warn "CLI shim missing: ${cli_link}"
    return
  fi
  local resolved
  resolved="$(readlink "$cli_link" 2>/dev/null || realpath "$cli_link" 2>/dev/null || true)"
  if [[ "$resolved" != "$canonical_bin" ]]; then
    _doctor_fail "CLI shim ${cli_link} does not resolve to canonical binary"
  else
    _doctor_ok "CLI shim ${cli_link} → canonical"
  fi
}

_check_chat_runtime_dirs() {
  local base="${HOME}/.config/mcp-agent-manager/chat-runtime"
  if [[ -d "$base" ]]; then
    _doctor_ok "chat runtime dir present: ${base}"
  else
    _doctor_warn "chat runtime dir missing: ${base}"
  fi
}

_check_chat_runtime_mode() {
  local base="${HOME}/.config/mcp-agent-manager/chat-runtime"
  [[ -d "$base" ]] || return
  local mode
  mode="$(stat -f "%OLp" "$base" 2>/dev/null || stat -c "%a" "$base" 2>/dev/null)"
  mode="${mode#0}"
  if [[ "$mode" == "700" ]]; then
    _doctor_ok "chat runtime dir mode 0700"
  else
    _doctor_fail "chat runtime dir mode is 0${mode}; expected 0700"
  fi
}

_check_tool_cache_mode() {
  local base="${HOME}/.config/mcp-agent-manager/tool-cache"
  [[ -d "$base" ]] || return
  local mode
  mode="$(stat -f "%OLp" "$base" 2>/dev/null || stat -c "%a" "$base" 2>/dev/null)"
  mode="${mode#0}"
  if [[ "$mode" == "700" ]]; then
    _doctor_ok "tool cache dir mode 0700"
  else
    _doctor_fail "tool cache dir mode is 0${mode}; expected 0700"
  fi
}

_check_python_helpers() {
  if python3 - "${_MCP_ROOT}/libexec/mcp_stdio_client.py" "${_MCP_ROOT}/libexec/mcp_chat_session.py" "${_MCP_ROOT}/libexec/mcp_health_gate.py" "${_MCP_ROOT}/libexec/mcp_tool_cache.py" "${_MCP_ROOT}/libexec/mcp_tools_cli.py" <<'PYEOF'
import ast
import sys
from pathlib import Path

for value in sys.argv[1:]:
    ast.parse(Path(value).read_text(), filename=value)
PYEOF
  then
    _doctor_ok "Python runtime helpers parse clean"
  else
    _doctor_fail "Python runtime helpers contain syntax errors"
  fi
}

cmd_doctor() {
  _DOCTOR_PASS=1
  _check_runtime_dirs
  _check_jq
  _check_tsh
  _check_claude
  _check_codex
  _check_agent_dirs
  _check_legacy_runtime_dir
  _check_skill_layout
  _check_skill_metadata
  _check_skill_symlink
  _check_cli_symlink
  _check_chat_runtime_dirs
  _check_chat_runtime_mode
  _check_tool_cache_mode
  _check_python_helpers

  if (( _DOCTOR_PASS == 1 )); then
    printf '[doctor] PASS\n'
    return 0
  fi

  printf '[doctor] FAIL\n' >&2
  return 1
}
