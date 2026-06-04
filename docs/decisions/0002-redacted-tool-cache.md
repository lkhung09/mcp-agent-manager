# ADR 0002: Redacted Tool Cache

## Status

Accepted

## Context

`tools/list` metadata can be large and may contain sensitive field names or headers.

## Decision

- Cache `tools/list` metadata locally.
- Redact secret-bearing text before write.
- Never cache `tools.call` output.
- Keep cache under `~/.config/mcp-agent-manager/tool-cache/`.

## Consequences

- Faster local search
- Lower repeated discovery cost
- Smaller blast radius if cache is inspected
