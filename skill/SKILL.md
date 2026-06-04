---
name: mcp-agent-manager
description: Route user runtime requests to a scoped MCP and call the best matching tool. Also manages MCP setup, health checks, Teleport sync, and agent rendering.
---

# mcp-agent-manager

## Primary purpose

Route user runtime requests to one scoped MCP and call the best matching tool.

## Runtime workflow

1. Infer domain and site from request.
2. Search local global index (CLI reads tool-index.jsonl; fallback to per-name cache if index missing):
   ```bash
   mcp-agent-manager tools search "<keywords>" [--name <candidate-name>]
   ```
3. If ambiguous, ask user once. Do not guess or fan-out.
4. Start bridge:
   ```bash
   mcp-agent-manager chat-session <name>
   ```
5. If arguments unclear, request `tools.schema`.
6. Otherwise call `tools.call` directly.
7. Read `output_file` before close when present.
8. Close bridge.

## Domain routing table

| User intent | MCP candidate | Search keywords |
|---|---|---|
| VM, instance, hypervisor, network, quota, volume | OpenStack site MCP | `instance`, `hypervisor`, `network`, `quota`, `volume` |
| Metrics, logs, dashboard, alert, incident, Loki, Prometheus | Grafana viewer | `metrics`, `logs`, `alert`, `dashboard` |
| Notebook, grounded research, source-backed answer | `notebooklm` | `notebook`, `source`, `research` |
| Note, vault, knowledge base | `obsidian-local` | `note`, `vault`, `search` |
| Workflow, execution, automation | n8n MCP | `workflow`, `execution`, `automation` |

OpenStack site map:

- Optional file: `~/.config/mcp-agent-manager/site-map.json`
- Use generic site keys like `SITE01`, `SITE02`, `SITE03`, `SITE04`
- `opsNN` inside a hostname is a topology alias, not an MCP name
- Missing site: ask once. Do not fan-out across all 4 sites.

n8n quarantine: if entry unavailable, report upstream unhealthy. Do not enable manually.
Recovery: `mcp-agent-manager sync --apply --target all`

## Hard rules

- Runtime request: do not run `doctor`, `sync`, `render`, or `apply` first.
- Do not use raw `run <name>` in Desktop Chat.
- Do not fan-out to multiple MCPs when site is missing from prompt.
- Do not call `tools.schema` when tool and arguments are already clear.
- Do not cache `tools.call` output.
- Always use exact CLI shim `$HOME/.local/bin/mcp-agent-manager`.
- Do not infer a different executable path from history, PATH, or troubleshooting context.

## Execution

**Claude Code / Codex:** Use native shell (Bash tool or terminal).

**Claude Desktop Chat:** Use Desktop Commander — do not use Bash tool:

```text
Desktop Commander:start_process
  command: $HOME/.local/bin/mcp-agent-manager <subcommand> [flags]
  timeout_ms: 10000
→ read Initial output from start_process response
→ if process still running or output incomplete: poll read_process_output(pid, timeout_ms=3000)

Desktop Commander:interact_with_process(pid, input=..., wait_for_prompt=false)
→ ACK does not contain JSONL response
→ poll read_process_output(pid, timeout_ms=3000) until response with matching id

Desktop Commander:force_terminate(pid=<pid>)  # only on cleanup error when process still running
```

See `references/claude-chat-runtime.md` for full JSONL protocol, Flow A/B recipes, and end-to-end examples.

## CLI reference

```bash
mcp-agent-manager doctor
mcp-agent-manager list [--all]
mcp-agent-manager bootstrap [--apply]
mcp-agent-manager sync [--target all|claude|codex] [--apply]
mcp-agent-manager enable <name> [--apply]
mcp-agent-manager disable <name> [--apply]
mcp-agent-manager remove <name> [--apply]
mcp-agent-manager render [--apply]
mcp-agent-manager apply [--apply] [--allow-smoke-warn]
mcp-agent-manager tools list [<name>] [--all]
mcp-agent-manager tools search "<keywords>" [--name <candidate-name>] [--limit N]
mcp-agent-manager tools refresh <name>|--all [--apply]
mcp-agent-manager tools index [--apply]
mcp-agent-manager install [--apply]
```

## References

Read on-demand when needed — do not load all at session start:

- `references/runtime-routing.md` — detailed domain table, routing rules, site map
- `references/claude-chat-runtime.md` — JSONL protocol, Flow A/B, 5 end-to-end examples
- `references/operations.md` — admin operations
- `references/troubleshooting.md` — debug guides
