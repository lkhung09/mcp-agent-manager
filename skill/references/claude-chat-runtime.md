# Claude Chat runtime

Claude Chat uses a scoped JSONL bridge launched through Desktop Commander.

## Flow A: Tool unknown — search first

Use when you don't know the exact tool name:

```bash
# Step 1: search global index (CLI: mcp-agent-manager tools search; fallback to per-name cache if index missing)
$HOME/.local/bin/mcp-agent-manager tools search "instance" \
  --name demo-mcp-site-1

# Step 2: open bridge
mcp-agent-manager chat-session demo-mcp-site-1

# Step 3: get schema if arguments unclear
{"id":"1","action":"tools.schema","tool":"<tool_name_from_search>"}

# Step 4: call tool
{"id":"2","action":"tools.call","tool":"<tool_name>","arguments":{...}}

# Step 5: close
{"id":"3","action":"close"}
```

## Flow B: Tool and arguments already known

Skip search and schema — open bridge and call directly:

```bash
mcp-agent-manager chat-session demo-mcp-site-1
```

```json
{"id":"1","action":"tools.call","tool":"get_instance","arguments":{"name":"vm-01"}}
```

```json
{"id":"2","action":"close"}
```

Do not repeat `tools.search` or `tools.schema` when tool + args are already clear.

---

## End-to-end examples

### 1. VM count at DEMO_SITE_1

```text
User: "Có bao nhiêu VM đang chạy tại DEMO_SITE_1?"
→ domain: OpenStack, site: DEMO_SITE_1
→ name: demo-mcp-site-1
→ tools search "instance list" --name demo-mcp-site-1
→ chat-session demo-mcp-site-1
→ tools.call list_instances (hoặc equivalent) với filter status=ACTIVE
→ đọc output, close
```

### 2. VM details by hostname with demo-alias-4

```text
User: "Chi tiết VM compute-demo-4-01.dc.local"
→ demo-alias-4 = topology alias → DEMO_SITE_4
→ name: demo-mcp-site-4
→ tools search "instance detail" --name demo-mcp-site-4
→ chat-session demo-mcp-site-4
→ tools.call get_instance với name="compute-demo-4-01.dc.local"
→ đọc output, close
```

### 3. Grafana logs

```text
User: "Tìm log lỗi payment trong 1 giờ qua"
→ domain: Grafana/Loki
→ name: teleport-mcp-internal-grafana-viewer
→ tools search "logs loki" --name teleport-mcp-internal-grafana-viewer
→ chat-session teleport-mcp-internal-grafana-viewer
→ tools.call query_loki với query="{service="payment"} |= "error"", range=1h
→ đọc output (có thể có output_file), close
```

No site disambiguation needed for Grafana.

### 4. Obsidian note search

```text
User: "Tìm note về octavia trong vault"
→ domain: Obsidian
→ name: obsidian-local
→ tools search "note search" --name obsidian-local
→ chat-session obsidian-local
→ tools.call search_notes với query="octavia"
→ đọc output, close
```

### 5. n8n unavailable (quarantine)

```text
User: "Kiểm tra workflow n8n đang lỗi"
→ domain: n8n
→ mcp-agent-manager list → n8n entry: status=unavailable/quarantined
→ Báo: "n8n MCP hiện không khỏe (quarantined). Không tự enable."
→ Recovery: mcp-agent-manager sync --apply --target all
→ Không mở chat-session, không gọi tools.
```

---

## Desktop Commander recipe

```text
# 1. Start bridge
Desktop Commander:start_process(
  command="$HOME/.local/bin/mcp-agent-manager chat-session <name>",
  timeout_ms=10000
)
→ lưu PID
→ đọc Initial output
→ nếu chưa thấy id="session": poll read_process_output(pid=<pid>, timeout_ms=3000)
→ lặp đến id="session", ok=true; budget tổng ~30s
→ khi process exit: đọc buffered output lần cuối trước khi abort
→ abort khi ok=false, DC lỗi, hoặc vượt budget

# 2. Send JSONL action
# wait_for_prompt=false chỉ trả ACK. Poll bắt buộc để lấy JSONL response.
# Không gửi action kế tiếp trước khi nhận response đúng id.

Desktop Commander:interact_with_process(
  pid=<pid>,
  input='{"id":"1","action":"tools.search","query":"<keyword>"}\n',
  wait_for_prompt=false
)
→ poll read_process_output(pid=<pid>, timeout_ms=3000)
→ lặp đến id=1; budget ~10s

Desktop Commander:interact_with_process(
  pid=<pid>,
  input='{"id":"2","action":"tools.schema","tool":"<tool_name>"}\n',
  wait_for_prompt=false
)
→ poll đến id=2; budget ~10s

Desktop Commander:interact_with_process(
  pid=<pid>,
  input='{"id":"3","action":"tools.call","tool":"<tool_name>","arguments":{...}}\n',
  wait_for_prompt=false
)
→ poll đến id=3; budget tổng ~60s
→ nếu response có "output_file": Desktop Commander:read_file(path=<output_file>)
→ đọc file TRƯỚC close vì session cleanup sẽ xóa file

# 3. Close cleanly
Desktop Commander:interact_with_process(
  pid=<pid>,
  input='{"id":"4","action":"close"}\n',
  wait_for_prompt=false
)
→ đọc buffered output đến khi thấy id=4, closed=true
→ process exit sau close là expected
→ nếu chưa thấy closed=true: ghi nhận cleanup chưa xác minh
→ force_terminate chỉ khi process vẫn còn chạy
```

## JSONL contract

- `tools.search`: `query`
- `tools.schema`: `tool`
- `tools.call`: `tool` + `arguments` JSON object
- `close`: no additional fields
- `id`: always use to correlate response
- When process exits mid-action: read buffered output before abort

## Persistent metadata cache

- Cache `tools/list` redacted tại `~/.config/mcp-agent-manager/tool-cache/<name>.json`
- Global search index tại `~/.config/mcp-agent-manager/tool-index.jsonl` — 1 dòng/tool, rebuild bằng `tools index --apply` hoặc auto sau `tools refresh --apply`. JSONL bridge `tools.search` action đọc RAM cache session — không dùng file index này.
- Bridge reuse cache fresh; cache miss hoặc stale fetch `tools/list` một lần
- `tools.search` và `tools.schema` chỉ đọc cache RAM trong session
- Khi đã biết tool + arguments, gọi thẳng `tools.call`
- Không cache output `tools.call`

## Rules

- Only use enabled `transport=stdio` registry entries
- No local allowlist gate; upstream auth and RBAC decide access
- Limit active Claude Chat sessions to 4
- Idle timeout is 60 seconds
- Large outputs spill to `~/.config/mcp-agent-manager/chat-runtime/<session-id>/outputs/`
