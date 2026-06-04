# Contributing

## Local setup

```bash
git clone <repo-url>
cd mcp-agent-manager
./bin/mcp-agent-manager install --apply
```

## Before a change

- Read `README.md`, `ARCHITECTURE.md`, and `CODEMAP.md`
- Keep edits small and scoped
- Prefer preview mode first
- Do not commit local runtime state

## Verification

```bash
python3 -m unittest discover -s tests -v
HOME="$(mktemp -d)" ./bin/mcp-agent-manager install --apply
HOME="$(mktemp -d)" MCP_AGENT_MANAGER_HOME="$(mktemp -d)/.config/mcp-agent-manager" ./bin/mcp-agent-manager bootstrap
rg -n "<internal-markers>" .
```

## Patch style

- Keep changes minimal
- Add tests when behavior changes
- Prefer shell and stdlib Python over new dependencies
