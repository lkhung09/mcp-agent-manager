#!/usr/bin/env python3
"""Persistent redacted tools/list metadata cache."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from mcp_stdio_client import redact_json

ROOT = Path(os.environ.get(
    "MCP_AGENT_MANAGER_HOME",
    str(Path.home() / ".config" / "mcp-agent-manager"),
))
CACHE_ROOT = ROOT / "tool-cache"
INDEX_FILE = ROOT / "tool-index.jsonl"
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_name(name: str) -> str:
    if not isinstance(name, str) or not SLUG_RE.fullmatch(name):
        raise ValueError(f"invalid MCP name: {name!r}")
    return name


def cache_path(name: str) -> Path:
    validate_name(name)
    path = CACHE_ROOT / f"{name}.json"
    if path.parent.resolve() != CACHE_ROOT.resolve():
        raise ValueError("tool cache path escaped cache directory")
    return path


def ensure_cache_dir() -> None:
    CACHE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    CACHE_ROOT.chmod(0o700)


def registry_fingerprint(entry: Dict[str, Any]) -> str:
    env = entry.get("env", {})
    payload = {
        "command": entry.get("command", ""),
        "args": entry.get("args", []),
        "transport": entry.get("transport", ""),
        "target": entry.get("target", "all"),
        "env_keys": sorted(env.keys()) if isinstance(env, dict) else [],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sanitize_tools(tools: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sanitized: List[Dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        sanitized.append(
            {
                # Tool name is routing metadata, not a secret value. Preserve it
                # so callers can invoke tools such as get_secret_details.
                "name": tool.get("name"),
                "description": redact_json(tool.get("description")),
                "inputSchema": redact_json(tool.get("inputSchema", {})),
            }
        )
    return sanitized


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    ensure_cache_dir()
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    json.loads(content)
    fd, tmp_path = tempfile.mkstemp(dir=str(CACHE_ROOT), prefix=".tool-cache_", suffix=".tmp")
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
        os.rename(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def write_fresh(name: str, entry: Dict[str, Any], tools: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    payload = {
        "version": 1,
        "name": validate_name(name),
        "status": "fresh",
        "updated_at": utc_now(),
        "registry_fingerprint": registry_fingerprint(entry),
        "tools": sanitize_tools(tools),
    }
    _atomic_write(cache_path(name), payload)
    return payload


def load_cache(name: str, entry: Optional[Dict[str, Any]] = None, allow_stale: bool = False) -> Optional[Dict[str, Any]]:
    path = cache_path(name)
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    stale = payload.get("status") != "fresh"
    if entry is not None and payload.get("registry_fingerprint") != registry_fingerprint(entry):
        stale = True
    if stale and not allow_stale:
        return None
    return payload


def mark_stale(name: str, reason: str) -> None:
    path = cache_path(name)
    if not path.exists():
        return
    payload = json.loads(path.read_text())
    payload["status"] = "stale"
    payload["stale_reason"] = reason
    payload["updated_at"] = utc_now()
    _atomic_write(path, payload)


def delete_cache(name: str) -> None:
    path = cache_path(name)
    if path.exists():
        path.unlink()


def list_cache_files() -> List[Path]:
    if not CACHE_ROOT.exists():
        return []
    return sorted(path for path in CACHE_ROOT.glob("*.json") if path.is_file())


def build_index_line(name: str, tool: Dict[str, Any]) -> str:
    return json.dumps(
        {
            "name": name,
            "tool": tool.get("name", ""),
            "description": tool.get("description") or "",
        },
        ensure_ascii=False,
    )


def write_index(registry: Dict[str, Any], show_all: bool = False) -> int:
    """Rebuild tool-index.jsonl atomically from all fresh cache files."""
    lines = []
    servers = registry.get("personal_mcp_servers", {})
    for name in sorted(servers):
        entry = servers[name]
        cache = load_cache(name, entry=entry, allow_stale=show_all)
        if not cache:
            continue
        for tool in cache.get("tools", []):
            if isinstance(tool, dict):
                lines.append(build_index_line(name, tool))
    content = "\n".join(lines) + ("\n" if lines else "")
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(ROOT), prefix=".tool-index_", suffix=".tmp")
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.rename(tmp_path, INDEX_FILE)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    return len(lines)


def load_index() -> Optional[List[Dict[str, Any]]]:
    """Load tool-index.jsonl. Returns None if file missing."""
    if not INDEX_FILE.exists():
        return None
    entries = []
    for line in INDEX_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries
