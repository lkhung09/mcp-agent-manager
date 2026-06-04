# Operations

## Core commands

- `doctor`: validate the environment, symlinks, and runtime directories
- `list`: show available registry entries; use `--all` to inspect disabled and
  quarantined entries
- `bootstrap`: import globals into the registry
- `sync`: refresh Teleport-backed entries; `--apply` quarantines unhealthy MCPs
- `enable <name>`: enable one personal MCP; preview by default
- `disable <name>`: disable one personal MCP; preview by default
- `remove <name>`: remove one personal MCP; preview by default
- `render`: generate specialized Claude Code and Codex agents
- `apply`: run backup, render, validate, smoke, and cutover flow
- `run <name>`: start the scoped stdio wrapper for a registry entry
- `chat-session <name>`: start the Claude Chat JSONL runtime bridge
- `tools list`: inspect per-name tool metadata cache
- `tools search`: search global index (tool-index.jsonl); fallback to per-name cache if index missing. CLI only — JSONL bridge `tools.search` action reads RAM cache in session (unchanged).
- `tools refresh <name>|--all [--apply]`: preview or refresh metadata cache
- `tools index [--apply]`: rebuild global search index (tool-index.jsonl); preview by default

## Safety rules

- Preview first for mutations
- Use `--apply` only when you want real writes
- Do not expose raw secrets or secret-bearing headers in logs
- Keep generated files under managed markers only

## Desktop Commander execution (Desktop Chat only)

Dùng absolute path `$HOME/.local/bin/mcp-agent-manager`.

Hard rule: luôn dùng exact path này. Không suy diễn executable path khác.

`start_process` trả PID kèm Initial output. Đọc Initial output trước. Chỉ poll
`read_process_output(pid, timeout_ms=3000)` khi process còn chạy hoặc output chưa đủ.

| Command | start_process timeout_ms | Poll budget |
|---|---:|---:|
| doctor | 10000 | ~30s |
| list | 10000 | ~30s |
| bootstrap / bootstrap --apply | 10000 | ~30s |
| sync / sync --apply | 10000 | ~60s |
| enable / disable / remove | 10000 | ~30s |
| render / render --apply | 10000 | ~30s |
| apply / apply --apply | 10000 | ~120s |
| install / install --apply | 10000 | ~30s |
| chat-session \<name\> | 10000 | per-action |
| tools list / search | 10000 | ~30s |
| tools refresh / tools refresh --apply | 10000 | ~60s |
| tools index / tools index --apply | 10000 | ~10s |

Không dùng `run <name>` trong Desktop Chat. Đây là raw stdio wrapper dành cho generated agents.
