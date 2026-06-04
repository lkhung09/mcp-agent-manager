# Runtime routing

## Domain routing table

| User intent | MCP candidate | Search keywords |
|---|---|---|
| VM, instance, hypervisor, network, quota, volume | OpenStack site MCP | `instance`, `hypervisor`, `network`, `quota`, `volume` |
| Metrics, logs, dashboard, alert, incident, Loki, Prometheus | Grafana viewer | `metrics`, `logs`, `alert`, `dashboard` |
| Notebook, grounded research, source-backed answer | `notebooklm` | `notebook`, `source`, `research` |
| Note, vault, knowledge base | `obsidian-local` | `note`, `vault`, `search` |
| Workflow, execution, automation | n8n MCP | `workflow`, `execution`, `automation` |

## OpenStack site map

| Topology alias | Site | MCP name |
|---|---|---|
| `demo-alias-1` | `DEMO_SITE_1` | `demo-mcp-site-1` |
| `demo-alias-2` | `DEMO_SITE_2` | `demo-mcp-site-2` |
| `demo-alias-3` | `DEMO_SITE_3` | `demo-mcp-site-3` |
| `demo-alias-4` | `DEMO_SITE_4` | `demo-mcp-site-4` |

Rules:
- `demo-alias-N` inside a hostname (e.g. `compute-demo-4-01`) is a topology alias, not an MCP name
- Do not fall back to SSH alias when the user intent is OpenStack MCP
- Read-only inventory/report actions are the default
- Missing site: ask user once. Do not search all 4 sites and pick highest score.
- Do not fan-out multiple OpenStack MCPs in parallel.

## Routing priority

1. Explicit MCP name in request
2. Topology alias mapping (demo-alias-1–demo-alias-4)
3. Explicit site name
4. Ask user once if unresolvable

## n8n quarantine

If n8n MCP entry is unavailable:
- Report: "n8n upstream is quarantined / not healthy"
- Do not enable manually via `enable <name> --apply`
- Recovery path: `mcp-agent-manager sync --apply --target all`

## Grafana

No site disambiguation needed — single Grafana viewer MCP covers all sites.
Search keywords: `metrics`, `logs`, `alert`, `dashboard`, `loki`, `prometheus`, `incident`.

## Obsidian / NotebookLM

Local services — no site needed.
- `obsidian-local`: vault note search/read/write
- `notebooklm`: grounded research and source-backed synthesis
