# ADR 0003: Optional Site Map

## Status

Accepted

## Context

OpenStack routing can vary by environment and should not hardcode company-internal names in public docs.

## Decision

- Load optional site routing from `~/.config/mcp-agent-manager/site-map.json`.
- Keep public examples generic.
- Treat missing site as a user prompt, not a fan-out search.

## Consequences

- Repo stays public-safe
- Local users can map their own sites
- Renderers remain flexible without extra dependencies
