# ADR 0001: Preview-First Safety

## Status

Accepted

## Context

Repo mutates registry, generated agents, parent configs, and runtime state.

## Decision

- Preview mode is default for all mutating commands.
- `--apply` is required for real writes.
- Mutations use scoped backups and managed markers.
- Failed cutover must restore state automatically.

## Consequences

- Safer local operations
- More steps before write mode
- Easier rollback when generated files collide with user-owned files
