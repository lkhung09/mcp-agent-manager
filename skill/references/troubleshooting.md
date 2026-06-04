# Troubleshooting

## Common checks

- `mcp-agent-manager doctor`
- Check `~/.config/mcp-agent-manager/registry.json`
- Verify `~/.claude/skills/mcp-agent-manager`, `~/.agents/skills/mcp-agent-manager`, and `~/.codex/skills/mcp-agent-manager` resolve to the canonical skill dir
- Verify `~/.config/mcp-agent-manager/chat-runtime/` exists for Claude Chat sessions
- Optional site map file: `~/.config/mcp-agent-manager/site-map.json`

## Typical issues

- Run `install --apply` when `doctor` reports a stale runtime copy. Never execute a path inferred from stale state.
- A registry entry is disabled or not `stdio`
- The requested site is missing from the prompt
- A command is blocked by upstream MCP permissions

## Log hygiene

- Do not print raw Teleport catalog JSON
- Do not log raw secret values or authorization headers
- Keep previews short and spill large responses to files
