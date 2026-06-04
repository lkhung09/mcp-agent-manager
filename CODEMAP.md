# Code Map

Use this as fast entrypoint for humans and agents.

## Start here

1. `README.md` - what repo does and how to use it
2. `ARCHITECTURE.md` - system flow
3. `skill/SKILL.md` - runtime behavior and routing

## Core files

- `bin/mcp-agent-manager` - CLI dispatcher and usage text
- `lib/utils.sh` - shared shell helpers
- `lib/registry.sh` - registry bootstrap and CRUD
- `lib/renderer_claude.sh` - Claude agent rendering
- `lib/renderer_codex.sh` - Codex agent rendering
- `lib/apply.sh` - backup/render/validate/smoke/cutover flow
- `lib/runner.sh` - STDIO runner for one MCP server
- `lib/chat_runtime.sh` - Claude Chat bridge entry
- `lib/syncer_teleport.sh` - Teleport sync and quarantine
- `lib/doctor.sh` - health checks
- `lib/installer.sh` - symlink and ZIP installer
- `lib/tools.sh` - tool cache CLI wrapper

## Python helpers

- `libexec/mcp_chat_session.py` - JSONL bridge process
- `libexec/mcp_stdio_client.py` - stdio client and redaction
- `libexec/mcp_tool_cache.py` - redacted cache logic
- `libexec/mcp_tools_cli.py` - cache/search/index CLI
- `libexec/mcp_health_gate.py` - Teleport health gate

## Tests

- `tests/test_chat_runtime.py`
- `tests/test_registry_crud.py`
- `tests/test_sync_health.py`
- `tests/test_tool_cache.py`
- `tests/test_public_hygiene.py` - public readiness checks

## Public examples

- `examples/site-map.example.json` - copy to `~/.config/mcp-agent-manager/site-map.json`
