# Security Policy

`mcp-agent-manager` is local-first. Treat `secrets.env`, `registry.json`, `site-map.json`, and any tool credentials as private machine-local state.

## What not to commit

- Raw tokens, passwords, API keys, cookies, or authorization headers
- Real Teleport proxy names or company-internal hostnames
- Raw `tools.call` output
- Local runtime state under `~/.config/mcp-agent-manager/`

## Handling rules

- Tool metadata cache stores redacted `tools/list` only.
- `tools.call` output is never cached.
- Preview commands should stay read-only unless `--apply` is explicit.
- Optional site routing belongs in `~/.config/mcp-agent-manager/site-map.json`, not in public docs or shared examples.

## Reporting

Use a GitHub security advisory or open an issue for any suspected leak or unsafe behavior.
