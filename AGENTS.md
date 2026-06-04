# AGENTS

This repo is a local-first MCP manager.

## Read first

- `README.md`
- `ARCHITECTURE.md`
- `CODEMAP.md`
- `skill/SKILL.md`

## Rules

- Prefer preview mode before `--apply`
- Use temp `HOME` for portability tests
- Keep secrets and local routing out of public commits
- Do not run against a real personal runtime during public-prep work

## Good checks

- `python3 -m unittest discover -s tests -v`
- `./bin/mcp-agent-manager doctor`
- `rg -n "<internal-markers>" .`
