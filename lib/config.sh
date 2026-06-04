#!/usr/bin/env bash
# lib/config.sh — user-facing local settings

SETTINGS_FILE="${REGISTRY_DIR}/settings.env"
CHAT_IDLE_TIMEOUT_DEFAULT=300
CHAT_IDLE_TIMEOUT_KEY="MCP_AGENT_MANAGER_CHAT_IDLE_TIMEOUT"

_config_usage() {
  cat <<'USAGE'
Usage: mcp-agent-manager config <get|set|reset> session-idle-timeout [seconds]

Manage simple local settings under:
  ~/.config/mcp-agent-manager/settings.env

Precedence:
  1. Current environment variable
  2. settings.env
  3. default 300 seconds

Examples:
  mcp-agent-manager config get session-idle-timeout
  mcp-agent-manager config set session-idle-timeout 900
  mcp-agent-manager config reset session-idle-timeout

Compatibility alias:
  chat-idle-timeout
USAGE
}

_config_validate_timeout() {
  local value="${1:-}"
  if [[ ! "$value" =~ ^[0-9]+$ ]]; then
    log_error "session-idle-timeout must be seconds between 30 and 86400."
    return 1
  fi
  if (( value < 30 || value > 86400 )); then
    log_error "session-idle-timeout must be seconds between 30 and 86400."
    return 1
  fi
}

_config_file_timeout() {
  if [[ ! -f "$SETTINGS_FILE" ]]; then
    return 1
  fi
  local line value
  line="$(grep -E "^export ${CHAT_IDLE_TIMEOUT_KEY}=" "$SETTINGS_FILE" | tail -1 || true)"
  [[ -n "$line" ]] || return 1
  value="${line#export ${CHAT_IDLE_TIMEOUT_KEY}=}"
  value="${value%\"}"
  value="${value#\"}"
  printf '%s\n' "$value"
}

cmd_config() {
  local action="${1:-}"
  local key="${2:-}"
  local value="${3:-}"

  if [[ "$action" == "--help" || "$action" == "-h" || -z "$action" ]]; then
    _config_usage
    return 0
  fi

  if [[ "$key" != "session-idle-timeout" && "$key" != "chat-idle-timeout" ]]; then
    log_error "config: unsupported setting '${key}'. Use: session-idle-timeout"
    return 1
  fi

  case "$action" in
    get)
      if [[ -n "${MCP_AGENT_MANAGER_CHAT_IDLE_TIMEOUT:-}" ]]; then
        printf '%s\n' "$MCP_AGENT_MANAGER_CHAT_IDLE_TIMEOUT"
        return 0
      fi
      if _config_file_timeout; then
        return 0
      fi
      printf '%s\n' "$CHAT_IDLE_TIMEOUT_DEFAULT"
      ;;
    set)
      _config_validate_timeout "$value" || return 1
      mkdir -p "$REGISTRY_DIR"
      chmod 700 "$REGISTRY_DIR"
      local tmp="${SETTINGS_FILE}.mcp-agent-manager.$$"
      if [[ -f "$SETTINGS_FILE" ]]; then
        grep -v -E "^export ${CHAT_IDLE_TIMEOUT_KEY}=" "$SETTINGS_FILE" > "$tmp" || true
      else
        : > "$tmp"
      fi
      printf 'export %s="%s"\n' "$CHAT_IDLE_TIMEOUT_KEY" "$value" >> "$tmp"
      mv "$tmp" "$SETTINGS_FILE"
      chmod 600 "$SETTINGS_FILE"
      log_info "Set session-idle-timeout=${value} seconds"
      ;;
    reset)
      mkdir -p "$REGISTRY_DIR"
      chmod 700 "$REGISTRY_DIR"
      if [[ ! -f "$SETTINGS_FILE" ]]; then
        log_info "session-idle-timeout already uses default ${CHAT_IDLE_TIMEOUT_DEFAULT} seconds"
        return 0
      fi
      local tmp="${SETTINGS_FILE}.mcp-agent-manager.$$"
      grep -v -E "^export ${CHAT_IDLE_TIMEOUT_KEY}=" "$SETTINGS_FILE" > "$tmp" || true
      mv "$tmp" "$SETTINGS_FILE"
      chmod 600 "$SETTINGS_FILE"
      log_info "Reset session-idle-timeout to default ${CHAT_IDLE_TIMEOUT_DEFAULT} seconds"
      ;;
    *)
      log_error "config: unsupported action '${action}'. Use: get, set, or reset"
      return 1
      ;;
  esac
}
