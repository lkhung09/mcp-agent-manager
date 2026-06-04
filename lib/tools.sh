#!/usr/bin/env bash
# lib/tools.sh — persistent MCP tool metadata cache CLI

cmd_tools() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  exec python3 "${script_dir}/libexec/mcp_tools_cli.py" "$@"
}
