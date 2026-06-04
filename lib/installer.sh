#!/usr/bin/env bash
# lib/installer.sh — install one-source skill symlinks and CLI shim

_MCP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_CANONICAL_SKILL_DIR="${_MCP_ROOT}/skill"
_BIN_SRC="${_MCP_ROOT}/bin/mcp-agent-manager"
_LOCAL_BIN_DIR="${HOME}/.local/bin"
_LOCAL_BIN_LINK="${_LOCAL_BIN_DIR}/mcp-agent-manager"
_CLAUDE_SKILL_LINK="${HOME}/.claude/skills/mcp-agent-manager"
_AGENTS_SKILL_LINK="${HOME}/.agents/skills/mcp-agent-manager"
_CODEX_COMPAT_SKILL_LINK="${HOME}/.codex/skills/mcp-agent-manager"
_LEGACY_RUNTIME_DIR="${HOME}/.local/share/agent-skills/mcp-agent-manager"
case "$(basename "${SHELL:-}")" in
  bash) _SHELL_RC="${MAM_SHELL_RC:-${HOME}/.bashrc}" ;;
  zsh)  _SHELL_RC="${MAM_SHELL_RC:-${HOME}/.zshrc}" ;;
  *)    _SHELL_RC="${MAM_SHELL_RC:-${HOME}/.profile}" ;;
esac
_LOCAL_BIN_PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
_LEGACY_PATH_LINE='export PATH="$HOME/.local/share/agent-skills/mcp-agent-manager:$PATH"'
_DIST_DIR="${HOME}/.config/mcp-agent-manager/dist"
_DESKTOP_SKILL_ZIP="${_DIST_DIR}/mcp-agent-manager-skill.zip"

cmd_install() {
  local apply=0
  for arg in "$@"; do
    [[ "$arg" == "--apply" ]] && apply=1
  done

  if [[ $apply -eq 0 ]]; then
    printf '[install] Preview — would ensure:\n'
    printf '  canonical skill dir : %s\n' "$_CANONICAL_SKILL_DIR"
    printf '  cli shim           : %s -> %s\n' "$_LOCAL_BIN_LINK" "$_BIN_SRC"
    printf '  claude skill link  : %s -> %s\n' "$_CLAUDE_SKILL_LINK" "$_CANONICAL_SKILL_DIR"
    printf '  agents skill link  : %s -> %s\n' "$_AGENTS_SKILL_LINK" "$_CANONICAL_SKILL_DIR"
    printf '  codex  skill link  : %s -> %s\n' "$_CODEX_COMPAT_SKILL_LINK" "$_CANONICAL_SKILL_DIR"
    printf '  legacy runtime dir : %s (would remove)\n' "$_LEGACY_RUNTIME_DIR"
    printf '  shell PATH         : ensure %s in %s; remove legacy PATH line\n' "$_LOCAL_BIN_DIR" "$_SHELL_RC"
    printf '  Desktop Chat ZIP   : %s\n' "$_DESKTOP_SKILL_ZIP"
    printf '  tool metadata cache: %s\n' "${HOME}/.config/mcp-agent-manager/tool-cache"
    printf '[install] Pass --apply to apply.\n'
    return 0
  fi

  if [[ ! -d "$_CANONICAL_SKILL_DIR" ]]; then
    log_error "canonical skill dir not found: ${_CANONICAL_SKILL_DIR}"
    return 1
  fi

  local registry_dir="${HOME}/.config/mcp-agent-manager"
  local backup_dir="${registry_dir}/backups"
  local chat_dir="${registry_dir}/chat-runtime"
  local tool_cache_dir="${registry_dir}/tool-cache"
  mkdir -p "$registry_dir" "$backup_dir" "$chat_dir" "$tool_cache_dir" "$_DIST_DIR"
  chmod 700 "$registry_dir" "$backup_dir" "$chat_dir" "$tool_cache_dir" "$_DIST_DIR"

  if [[ -e "$_LEGACY_RUNTIME_DIR" || -L "$_LEGACY_RUNTIME_DIR" ]]; then
    local legacy_backup="${backup_dir}/legacy-runtime-$(date +%s)"
    while [[ -e "$legacy_backup" ]]; do
      legacy_backup="${legacy_backup}-1"
    done
    mv "$_LEGACY_RUNTIME_DIR" "$legacy_backup"
    log_info "Backed up legacy runtime dir: ${_LEGACY_RUNTIME_DIR} -> ${legacy_backup}"
  fi

  mkdir -p \
    "$_LOCAL_BIN_DIR" \
    "${HOME}/.claude/skills" \
    "${HOME}/.agents/skills" \
    "${HOME}/.codex/skills" \
    "${HOME}/.claude/agents" \
    "${HOME}/.codex/agents"

  _make_symlink "$_LOCAL_BIN_LINK" "$_BIN_SRC"
  _make_symlink "$_CLAUDE_SKILL_LINK" "$_CANONICAL_SKILL_DIR"
  _make_symlink "$_AGENTS_SKILL_LINK" "$_CANONICAL_SKILL_DIR"
  _make_symlink "$_CODEX_COMPAT_SKILL_LINK" "$_CANONICAL_SKILL_DIR"

  ensure_secrets_env
  _ensure_shell_path
  _package_desktop_skill
  log_info "[install] Done. Desktop Chat upload remains manual: ${_DESKTOP_SKILL_ZIP}"
  _print_shell_activation
}

_make_symlink() {
  local link_path="$1"
  local target="$2"

  if [[ -L "$link_path" ]]; then
    local existing
    existing="$(readlink "$link_path")"
    if [[ "$existing" == "$target" ]]; then
      log_info "  symlink OK: ${link_path} -> ${target}"
      return 0
    fi
    rm "$link_path"
  elif [[ -e "$link_path" ]]; then
    log_error "path exists and is not a symlink: ${link_path}"
    return 1
  fi

  ln -s "$target" "$link_path"
  log_info "  created: ${link_path} -> ${target}"
}

_ensure_shell_path() {
  local tmp="${_SHELL_RC}.mcp-agent-manager.$$"
  local changed=0

  if [[ ! -e "$_SHELL_RC" ]]; then
    : > "$_SHELL_RC"
  fi

  if grep -qxF "$_LEGACY_PATH_LINE" "$_SHELL_RC"; then
    changed=1
  else
    local legacy_rc=$?
    if [[ $legacy_rc -gt 1 ]]; then
      log_error "failed reading shell rc: ${_SHELL_RC}"
      return 1
    fi
  fi

  local grep_rc
  if grep -qxF "$_LOCAL_BIN_PATH_LINE" "$_SHELL_RC"; then
    grep_rc=0
  else
    grep_rc=$?
  fi
  if [[ $grep_rc -eq 1 ]]; then
    changed=1
  elif [[ $grep_rc -gt 1 ]]; then
    log_error "failed reading shell rc: ${_SHELL_RC}"
    return 1
  fi

  if [[ $changed -eq 0 ]]; then
    log_info "  shell PATH OK: ${_LOCAL_BIN_DIR}"
    return 0
  fi

  backup_file "$_SHELL_RC"
  local strip_rc
  if grep -vxF "$_LEGACY_PATH_LINE" "$_SHELL_RC" > "$tmp"; then
    strip_rc=0
  else
    strip_rc=$?
  fi
  if [[ $strip_rc -gt 1 ]]; then
    rm -f "$tmp"
    log_error "failed rewriting shell rc: ${_SHELL_RC}"
    return 1
  fi
  if ! grep -qxF "$_LOCAL_BIN_PATH_LINE" "$tmp"; then
    printf '\n# mcp-agent-manager\n%s\n' "$_LOCAL_BIN_PATH_LINE" >> "$tmp"
  fi
  mv "$tmp" "$_SHELL_RC"
  log_info "  shell PATH updated: ${_SHELL_RC}"
}

_package_desktop_skill() {
  local tmp_dir
  tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/mcp-agent-manager-skill.XXXXXX")"
  cp -R "$_CANONICAL_SKILL_DIR" "${tmp_dir}/mcp-agent-manager"
  rm -f "$_DESKTOP_SKILL_ZIP"
  (
    cd "$tmp_dir"
    zip -qr "$_DESKTOP_SKILL_ZIP" mcp-agent-manager
  )
  rm -rf "$tmp_dir"
  chmod 600 "$_DESKTOP_SKILL_ZIP"
  log_info "  Desktop Chat ZIP ready: ${_DESKTOP_SKILL_ZIP}"
}

_print_shell_activation() {
  case ":${PATH}:" in
    *":${_LOCAL_BIN_DIR}:"*)
      log_info "  current shell PATH active: ${_LOCAL_BIN_DIR}"
      ;;
    *)
      printf '\n'
      log_warn "Current shell has not loaded ${_LOCAL_BIN_DIR} yet."
      printf '[install] Run in this terminal:\n'
      printf '  source "%s"\n' "$_SHELL_RC"
      printf '  mcp-agent-manager --help\n'
      printf '[install] Or open a new terminal.\n'
      ;;
  esac
}
