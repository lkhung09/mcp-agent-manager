#!/usr/bin/env bash
# lib/chat_runtime.sh — Claude Chat runtime bridge

# cmd_chat_session <name>
# Start scoped JSONL bridge for Claude Chat/Desktop Commander.
cmd_chat_session() {
  local name="${1:-}"
  if [[ -z "$name" ]]; then
    log_error "chat-session: missing name. Usage: mcp-agent-manager chat-session <name>"
    return 1
  fi

  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  local py_bridge="${script_dir}/libexec/mcp_chat_session.py"

  if [[ ! -f "$py_bridge" ]]; then
    log_error "chat-session: bridge not found at ${py_bridge}"
    return 1
  fi

  exec python3 "$py_bridge" "$name"
}
