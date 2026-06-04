#!/usr/bin/env python3
"""Claude Chat runtime bridge for scoped MCP sessions."""

from __future__ import annotations

import fcntl
import json
import os
import re
import select
import shutil
import signal
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

def _resolve_root() -> Path:
    env = os.environ.get("MCP_AGENT_MANAGER_HOME", "").strip()
    if env:
        p = Path(env)
        if not p.is_absolute():
            raise ValueError(f"MCP_AGENT_MANAGER_HOME must be absolute path, got: {env!r}")
        return p
    return Path.home() / ".config" / "mcp-agent-manager"


ROOT = _resolve_root()
REGISTRY_FILE = ROOT / "registry.json"
SECRETS_FILE = ROOT / "secrets.env"
CHAT_ROOT = ROOT / "chat-runtime"
LOCK_FILE = CHAT_ROOT / ".lock"
SESSION_CAP = 4
IDLE_TIMEOUT = int(os.environ.get("MCP_AGENT_MANAGER_CHAT_IDLE_TIMEOUT", "300"))
PREVIEW_LIMIT = 12 * 1024

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_stdio_client import MCPClientError, MCPStdioClient, load_export_env, redact_json  # noqa: E402
from mcp_tool_cache import load_cache, write_fresh  # noqa: E402


def ensure_dirs() -> None:
    CHAT_ROOT.mkdir(parents=True, exist_ok=True)
    CHAT_ROOT.chmod(0o700)


def load_registry() -> Dict[str, Any]:
    if not REGISTRY_FILE.exists():
        raise MCPClientError("registry.json not found. Run: mcp-agent-manager bootstrap")
    return json.loads(REGISTRY_FILE.read_text())


def resolve_entry(registry: Dict[str, Any], name: str) -> Dict[str, Any]:
    entry = registry.get("personal_mcp_servers", {}).get(name)
    if not entry:
        raise MCPClientError(f"chat-session: name '{name}' not found in registry")
    if not entry.get("enabled", False):
        raise MCPClientError(f"chat-session: name '{name}' is disabled")
    if entry.get("transport") != "stdio":
        raise MCPClientError(f"chat-session: name '{name}' transport='{entry.get('transport')}' — only stdio supported")
    return entry


def list_active_sessions() -> List[Path]:
    active: List[Path] = []
    if not CHAT_ROOT.exists():
        return active
    for path in CHAT_ROOT.iterdir():
        if not path.is_dir() or path.name.startswith("."):
            continue
        pid_file = path / "pid"
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
        except Exception:
            continue
        active.append(path)
    return active


def cleanup_session_dir(path: Path) -> None:
    if not path.exists():
        return
    for item in sorted(path.rglob("*"), reverse=True):
        if item.is_file():
            try:
                item.unlink()
            except Exception:
                pass
        elif item.is_dir():
            try:
                item.rmdir()
            except Exception:
                pass
    try:
        path.rmdir()
    except Exception:
        pass


def cleanup_stale_sessions() -> None:
    if not CHAT_ROOT.exists():
        return
    for path in list(CHAT_ROOT.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        pid_file = path / "pid"
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
        except Exception:
            cleanup_session_dir(path)


def claim_session(session_id: str) -> Path:
    ensure_dirs()
    LOCK_FILE.touch(exist_ok=True)
    with LOCK_FILE.open("r+") as lock_fp:
        fcntl.flock(lock_fp, fcntl.LOCK_EX)
        cleanup_stale_sessions()
        if len(list_active_sessions()) >= SESSION_CAP:
            raise MCPClientError(f"chat-session: active session cap {SESSION_CAP} reached")
        session_dir = CHAT_ROOT / session_id
        session_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        (session_dir / "pid").write_text(str(os.getpid()))
        (session_dir / "started_at").write_text(str(int(time.time())))
        (session_dir / "outputs").mkdir(mode=0o700, exist_ok=True)
        session_dir.chmod(0o700)
        return session_dir


def spill_output(session_dir: Path, tool: str, payload: Any) -> str:
    out_dir = session_dir / "outputs"
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    out_dir.chmod(0o700)
    safe_tool = re.sub(r"[^A-Za-z0-9._-]", "_", tool).strip("._-") or "tool"
    out_path = out_dir / f"{safe_tool}-{uuid.uuid4().hex}.json"
    if out_path.parent.resolve() != out_dir.resolve():
        raise MCPClientError("output path escaped session directory")
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    out_path.chmod(0o600)
    return str(out_path)


def score_tool(query: str, tool: Dict[str, Any]) -> int:
    text = f"{tool.get('name', '')} {tool.get('description', '')} {json.dumps(tool.get('inputSchema', {}), ensure_ascii=False)}".lower()
    score = 0
    for token in query.lower().split():
        if not token:
            continue
        if token in tool.get("name", "").lower():
            score += 6
        if token in text:
            score += 3
    return score


def load_runtime_env() -> Dict[str, str]:
    return load_export_env(SECRETS_FILE)


def format_result(payload: Any) -> Dict[str, Any]:
    redacted = redact_json(payload)
    raw = json.dumps(redacted, ensure_ascii=False)
    raw_bytes = raw.encode("utf-8")
    if len(raw_bytes) <= PREVIEW_LIMIT:
        return {"result": redacted}
    preview = raw_bytes[:PREVIEW_LIMIT].decode("utf-8", errors="ignore")
    return {"preview": preview, "bytes": len(raw_bytes)}


def run_session(name: str) -> int:
    registry = load_registry()
    entry = resolve_entry(registry, name)
    runtime_env = os.environ.copy()
    runtime_env.update(load_runtime_env())
    for key, value in entry.get("env", {}).items():
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            ref = value[2:-1]
            if ref not in runtime_env:
                raise MCPClientError(f"chat-session: env reference '{value}' not set")
            runtime_env[key] = runtime_env[ref]
        else:
            runtime_env[key] = str(value)

    command = entry.get("command")
    args = entry.get("args", [])
    if not isinstance(command, str) or not command:
        raise MCPClientError("chat-session: registry command must be non-empty string")
    if not shutil.which(command) and not Path(command).is_file():
        raise MCPClientError(f"chat-session: command not found: {command}")
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise MCPClientError("chat-session: registry args must be string array")

    session_id = f"{name}-{uuid.uuid4().hex[:8]}"
    session_dir = claim_session(session_id)
    client = MCPStdioClient(
        command=command,
        args=args,
        env=runtime_env,
        timeout=IDLE_TIMEOUT,
        initialize_timeout=8,
    )
    tools_cache: List[Dict[str, Any]] = []
    closed = False

    def cleanup() -> None:
        nonlocal closed
        if closed:
            return
        closed = True
        try:
            client.close()
        except Exception:
            pass
        cleanup_session_dir(session_dir)

    def handle_signal(_signum, _frame) -> None:
        cleanup()
        raise SystemExit(130)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        client.open()
        persistent_cache = load_cache(name, entry=entry)
        if persistent_cache:
            tools_cache = persistent_cache.get("tools", [])
        else:
            tools_cache = client.list_tools()
            write_fresh(name, entry, tools_cache)
        print(json.dumps({"id": "session", "ok": True, "session_id": session_id, "name": name}, ensure_ascii=False), flush=True)

        while True:
            ready, _, _ = select.select([sys.stdin], [], [], IDLE_TIMEOUT)
            if not ready:
                print(json.dumps({"id": "session", "ok": True, "closed": True, "reason": "idle-timeout"}, ensure_ascii=False), flush=True)
                cleanup()
                return 0

            raw_line = sys.stdin.readline()
            if raw_line == "":
                cleanup()
                return 0

            line = raw_line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                print(json.dumps({"ok": False, "error": {"message": f"invalid json: {exc}"}}, ensure_ascii=False), flush=True)
                continue

            req_id = request.get("id")
            action = request.get("action")

            try:
                if action == "close":
                    print(json.dumps({"id": req_id, "ok": True, "closed": True}, ensure_ascii=False), flush=True)
                    cleanup()
                    return 0

                if action == "tools.search":
                    query = str(request.get("query", "")).strip()
                    limit = int(request.get("limit", 8))
                    matches = sorted(
                        ((score_tool(query, tool), tool) for tool in tools_cache),
                        key=lambda item: item[0],
                        reverse=True,
                    )
                    result = [
                        {"name": tool.get("name"), "description": tool.get("description"), "score": score}
                        for score, tool in matches[: max(limit, 0)]
                        if score > 0
                    ]
                    print(json.dumps({"id": req_id, "ok": True, "result": {"query": query, "matches": result}}, ensure_ascii=False), flush=True)
                    continue

                if action == "tools.schema":
                    tool_name = str(request.get("tool", "")).strip()
                    match = next((tool for tool in tools_cache if tool.get("name") == tool_name), None)
                    if not match:
                        raise MCPClientError(f"tool not found: {tool_name}")
                    print(json.dumps({"id": req_id, "ok": True, "result": redact_json(match)}, ensure_ascii=False), flush=True)
                    continue

                if action == "tools.call":
                    tool_name = str(request.get("tool", "")).strip()
                    arguments = request.get("arguments", {})
                    if not isinstance(arguments, dict):
                        raise MCPClientError("arguments must be JSON object")
                    result = client.call_tool(tool_name, arguments)
                    payload = result.get("result", result)
                    response = format_result(payload)
                    if "preview" in response:
                        output_path = spill_output(session_dir, tool_name, redact_json(payload))
                        body = {
                            "id": req_id,
                            "ok": True,
                            "tool": tool_name,
                            "output_file": output_path,
                            "preview": response["preview"],
                        }
                    else:
                        body = {"id": req_id, "ok": True, "tool": tool_name, "result": response["result"]}
                    print(json.dumps(body, ensure_ascii=False), flush=True)
                    continue

                method_hint = "; did you mean 'action' instead of 'method'?" if (action is None and request.get("method")) else ""
                raise MCPClientError(
                    f"unknown action: {action!r}{method_hint} — expected: close | tools.search | tools.schema | tools.call"
                )
            except Exception as exc:
                print(json.dumps({"id": req_id, "ok": False, "error": {"message": str(exc)}}, ensure_ascii=False), flush=True)
    except Exception as exc:
        print(json.dumps({"id": "session", "ok": False, "error": {"message": str(exc)}}, ensure_ascii=False), flush=True)
        cleanup()
        return 1
    finally:
        cleanup()

    return 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in {"--help", "-h"}:
        print("Usage: mcp-agent-manager chat-session <name>")
        return 0

    try:
        return run_session(sys.argv[1])
    except Exception as exc:
        print(json.dumps({"id": "session", "ok": False, "error": {"message": str(exc)}}, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
