#!/usr/bin/env python3
"""Read-only Teleport MCP health checks used by sync."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict

from mcp_stdio_client import MCPStdioClient

ERROR_LIMIT = 512


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def redact_error(error: Any) -> str:
    message = " ".join(str(error).split())
    message = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", message)
    message = re.sub(
        r"(?i)\b(authorization|token|secret|password|api[_-]?key|cookie|header)"
        r"\b(\s*[:=]\s*)([^,}\]\s]+)",
        r"\1\2[REDACTED]",
        message,
    )
    return message[:ERROR_LIMIT]


def probe_teleport_stdio(
    name: str,
    proxy: str,
    tsh_bin: str = "tsh",
    timeout: float = 8.0,
) -> Dict[str, Any]:
    client = MCPStdioClient(
        command=tsh_bin,
        args=["mcp", "connect", f"--proxy={proxy}", name],
        env={"TELEPORT_DEBUG": "false"},
        timeout=timeout,
        initialize_timeout=timeout,
    )
    checked_at = utc_now()
    try:
        client.open()
        tools = client.list_tools()
        return {
            "status": "healthy",
            "checked_at": checked_at,
            "tools": tools,
        }
    except Exception as exc:
        return {
            "status": "quarantined",
            "checked_at": checked_at,
            "error": redact_error(exc),
        }
    finally:
        client.close()
