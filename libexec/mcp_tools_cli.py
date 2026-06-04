#!/usr/bin/env python3
"""CLI for persistent MCP tool metadata cache."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

ROOT = Path(os.environ.get(
    "MCP_AGENT_MANAGER_HOME",
    str(Path.home() / ".config" / "mcp-agent-manager"),
))
REGISTRY_FILE = ROOT / "registry.json"
SECRETS_FILE = ROOT / "secrets.env"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_stdio_client import MCPClientError, MCPStdioClient, load_export_env, load_initialize_timeout  # noqa: E402
from mcp_tool_cache import (  # noqa: E402
    INDEX_FILE,
    load_cache,
    load_index,
    sanitize_tools,
    validate_name,
    write_fresh,
    write_index,
)


def load_registry() -> Dict[str, Any]:
    if not REGISTRY_FILE.exists():
        raise MCPClientError("registry.json not found. Run: mcp-agent-manager bootstrap")
    return json.loads(REGISTRY_FILE.read_text())


def score_tool(query: str, tool: Dict[str, Any]) -> int:
    tool_name = tool.get("tool", tool.get("name", ""))
    text = f"{tool.get('name', '')} {tool_name} {tool.get('description', '')} {json.dumps(tool.get('inputSchema', {}), ensure_ascii=False)}".lower()
    score = 0
    for token in query.lower().split():
        if token in tool.get("name", "").lower():
            score += 6
        if token in str(tool_name).lower():
            score += 6
        if token and token in text:
            score += 3
    return score


def display_text(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def eligible(registry: Dict[str, Any], show_all: bool = False) -> Iterable[Tuple[str, Dict[str, Any]]]:
    for name, entry in sorted(registry.get("personal_mcp_servers", {}).items()):
        if show_all or (entry.get("enabled") is True and entry.get("transport") == "stdio"):
            yield name, entry


def resolve_env(entry: Dict[str, Any]) -> Dict[str, str]:
    runtime_env = os.environ.copy()
    runtime_env.update(load_export_env(SECRETS_FILE))
    for key, value in entry.get("env", {}).items():
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            ref = value[2:-1]
            if ref not in runtime_env:
                raise MCPClientError(f"env reference '{value}' not set")
            runtime_env[key] = runtime_env[ref]
        else:
            runtime_env[key] = str(value)
    return runtime_env


def refresh_one(name: str, entry: Dict[str, Any]) -> int:
    if entry.get("enabled") is not True:
        raise MCPClientError(f"tools refresh: name '{name}' is disabled")
    if entry.get("transport") != "stdio":
        raise MCPClientError(f"tools refresh: name '{name}' transport='{entry.get('transport')}' is not stdio")
    command = entry.get("command")
    args = entry.get("args", [])
    if not isinstance(command, str) or not command:
        raise MCPClientError(f"tools refresh: name '{name}' command must be non-empty string")
    if not shutil.which(command) and not Path(command).is_file():
        raise MCPClientError(f"tools refresh: command not found: {command}")
    init_timeout = load_initialize_timeout()
    client = MCPStdioClient(command=command, args=args, env=resolve_env(entry), timeout=init_timeout, initialize_timeout=init_timeout)
    try:
        client.open()
        tools = client.list_tools()
        write_fresh(name, entry, tools)
        print(f"[tools] REFRESHED {name} ({len(tools)} tools)")
        return 0
    finally:
        client.close()


def cmd_list(args: argparse.Namespace) -> int:
    registry = load_registry()
    servers = registry.get("personal_mcp_servers", {})
    rows: List[Tuple[str, str, str, str]] = []
    if args.name:
        validate_name(args.name)
        if args.name not in servers:
            raise MCPClientError(f"tools list: name not found: {args.name}")
        candidates = [(args.name, servers[args.name])]
    else:
        candidates = list(eligible(registry, show_all=args.all))
    for name, entry in candidates:
        cache = load_cache(name, entry=entry, allow_stale=args.all)
        if not cache:
            continue
        for tool in cache.get("tools", []):
            rows.append((name, cache.get("status", "stale"), str(tool.get("name", "")), display_text(tool.get("description"))))
    print(f"{'NAME':45} {'CACHE':8} {'TOOL':38} DESCRIPTION")
    print(f"{'----':45} {'-----':8} {'----':38} -----------")
    for mcp_name, status, tool_name, description in rows:
        print(f"{mcp_name:45} {status:8} {tool_name:38} {description}")
    return 0


def _cmd_search_legacy(args: argparse.Namespace) -> int:
    registry = load_registry()
    if args.name:
        validate_name(args.name)
    rows: List[Tuple[int, str, str, str, str]] = []
    for name, entry in eligible(registry, show_all=args.all):
        if args.name and name != args.name:
            continue
        cache = load_cache(name, entry=entry, allow_stale=args.all)
        if not cache:
            continue
        for tool in cache.get("tools", []):
            score = score_tool(args.query, tool)
            if score > 0:
                rows.append((score, name, cache.get("status", "stale"), str(tool.get("name", "")), display_text(tool.get("description"))))
    rows.sort(key=lambda row: (-row[0], row[1], row[3]))
    print(f"{'SCORE':5} {'NAME':45} {'CACHE':8} {'TOOL':38} DESCRIPTION")
    print(f"{'-----':5} {'----':45} {'-----':8} {'----':38} -----------")
    for score, mcp_name, status, tool_name, description in rows[: max(args.limit, 0)]:
        print(f"{score:<5} {mcp_name:45} {status:8} {tool_name:38} {description}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    if args.name:
        validate_name(args.name)
    registry = load_registry()
    servers = registry.get("personal_mcp_servers", {})
    index = load_index()
    if index is None:
        print("[tools] WARNING: index not found. Run 'tools index --apply' to build it.", file=sys.stderr)
        return _cmd_search_legacy(args)
    rows: List[Tuple[int, str, str, str, str]] = []
    for entry in index:
        name = entry.get("name", "")
        if args.name and name != args.name:
            continue
        server = servers.get(name, {})
        if not args.all and not (server.get("enabled") is True and server.get("transport") == "stdio"):
            continue
        score = score_tool(args.query, entry)
        if score > 0:
            rows.append((score, name, "index", entry.get("tool", ""), entry.get("description", "")))
    rows.sort(key=lambda row: (-row[0], row[1], row[3]))
    print(f"{'SCORE':5} {'NAME':45} {'CACHE':8} {'TOOL':38} DESCRIPTION")
    print(f"{'-----':5} {'----':45} {'-----':8} {'----':38} -----------")
    for score, mcp_name, status, tool_name, description in rows[: max(args.limit, 0)]:
        print(f"{score:<5} {mcp_name:45} {status:8} {tool_name:38} {display_text(description)}")
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    registry = load_registry()
    servers = registry.get("personal_mcp_servers", {})
    if args.all and args.name:
        raise MCPClientError("tools refresh: use either <name> or --all")
    if args.all:
        targets = [(name, entry) for name, entry in eligible(registry) if entry.get("transport") == "stdio"]
    else:
        if not args.name:
            raise MCPClientError("tools refresh: provide <name> or --all")
        validate_name(args.name)
        entry = servers.get(args.name)
        if not entry:
            raise MCPClientError(f"tools refresh: name not found: {args.name}")
        targets = [(args.name, entry)]
    if not args.apply:
        for name, _entry in targets:
            print(f"[tools] Would refresh: {name}")
        print("[tools] Preview only. Pass --apply to refresh cache.")
        return 0
    failures = 0
    for name, entry in targets:
        try:
            refresh_one(name, entry)
        except Exception as exc:
            failures += 1
            print(f"[tools] ERROR {name}: {exc}", file=sys.stderr)
    try:
        registry = load_registry()
        count = write_index(registry)
        print(f"[tools] index rebuilt ({count} entries)")
    except Exception as exc:
        print(f"[tools] WARNING index rebuild failed: {exc}", file=sys.stderr)
    return 1 if failures else 0


def cmd_index(args: argparse.Namespace) -> int:
    registry = load_registry()
    if not args.apply:
        count = 0
        for name, entry in eligible(registry, show_all=args.all):
            cache = load_cache(name, entry=entry, allow_stale=False)
            if cache:
                count += len(cache.get("tools", []))
        print(f"[tools] Would write {count} entries to index. Pass --apply to rebuild.")
        return 0
    count = write_index(registry, show_all=args.all)
    print(f"[tools] index rebuilt: {count} entries → {INDEX_FILE}")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="mcp-agent-manager tools")
    sub = root.add_subparsers(dest="command", required=True)
    list_parser = sub.add_parser("list")
    list_parser.add_argument("name", nargs="?")
    list_parser.add_argument("--all", action="store_true")
    search_parser = sub.add_parser("search")
    search_parser.add_argument("query", help="keyword(s) to match against tool name and description")
    search_parser.add_argument("--name", help="restrict search to a specific MCP name")
    search_parser.add_argument("--limit", type=int, default=8, help="max results to return (default: 8)")
    search_parser.add_argument("--all", action="store_true", help="include inactive and quarantined entries")
    refresh_parser = sub.add_parser("refresh")
    refresh_parser.add_argument("name", nargs="?")
    refresh_parser.add_argument("--all", action="store_true")
    refresh_parser.add_argument("--apply", action="store_true")
    index_parser = sub.add_parser("index", help="rebuild global search index from cache files")
    index_parser.add_argument("--apply", action="store_true", help="write tool-index.jsonl (default: preview)")
    index_parser.add_argument("--all", action="store_true", help="include inactive and quarantined entries")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "list":
            return cmd_list(args)
        if args.command == "search":
            return cmd_search(args)
        if args.command == "refresh":
            return cmd_refresh(args)
        if args.command == "index":
            return cmd_index(args)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
