#!/usr/bin/env python3
"""Synthetic regression tests for shared stdio client and Claude Chat bridge."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBEXEC = ROOT / "libexec"
sys.path.insert(0, str(LIBEXEC))

import mcp_chat_session as chat  # noqa: E402
from mcp_stdio_client import MCPRPCError, MCPStdioClient, load_initialize_timeout  # noqa: E402


NEWLINE_SERVER = r"""
import json, sys
for line in sys.stdin:
    req = json.loads(line)
    method = req.get("method")
    if method == "notifications/initialized":
        continue
    if method == "initialize":
        result = {"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{"name":"fixture","version":"1"}}
    elif method == "tools/list":
        result = {"tools":[{"name":"echo","description":"echo text","inputSchema":{"type":"object"}}]}
    elif method == "tools/call":
        result = {"content":[{"type":"text","text":req["params"]["arguments"].get("text","")}]}
    else:
        continue
    print(json.dumps({"jsonrpc":"2.0","id":req["id"],"result":result}), flush=True)
"""

LEGACY_SERVER = r"""
import json, sys, time
for line in sys.stdin:
    req = json.loads(line)
    method = req.get("method")
    if method == "notifications/initialized":
        continue
    if method == "initialize":
        result = {"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{"name":"fixture","version":"1"}}
    elif method == "tools/list":
        result = {"tools":[]}
    else:
        continue
    raw = json.dumps({"jsonrpc":"2.0","id":req["id"],"result":result}).encode()
    frame = f"Content-Length: {len(raw)}\r\n\r\n".encode() + raw
    for value in frame:
        sys.stdout.buffer.write(bytes([value]))
        sys.stdout.buffer.flush()
"""

LEGACY_INPUT_SERVER = r"""
import json, sys
stream = sys.stdin.buffer
while True:
    header = stream.readline()
    if not header:
        break
    if not header.lower().startswith(b"content-length:"):
        continue
    length = int(header.split(b":", 1)[1].strip())
    if stream.readline() != b"\r\n":
        continue
    req = json.loads(stream.read(length))
    method = req.get("method")
    if method == "notifications/initialized":
        continue
    result = {"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{"name":"fixture","version":"1"}} if method == "initialize" else {"tools":[]}
    raw = json.dumps({"jsonrpc":"2.0","id":req["id"],"result":result}).encode()
    sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode() + raw)
    sys.stdout.buffer.flush()
"""

ERROR_SERVER = r"""
import json, sys
for line in sys.stdin:
    req = json.loads(line)
    method = req.get("method")
    if method == "notifications/initialized":
        continue
    if method == "initialize":
        payload = {"jsonrpc":"2.0","id":req["id"],"result":{"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{"name":"fixture","version":"1"}}}
    else:
        payload = {"jsonrpc":"2.0","id":req["id"],"error":{"code":-32603,"message":"fixture failure"}}
    print(json.dumps(payload), flush=True)
"""

CALL_ERROR_SERVER = r"""
import json, sys
for line in sys.stdin:
    req = json.loads(line)
    method = req.get("method")
    if method == "notifications/initialized":
        continue
    if method == "initialize":
        payload = {"jsonrpc":"2.0","id":req["id"],"result":{"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{"name":"fixture","version":"1"}}}
    elif method == "tools/list":
        payload = {"jsonrpc":"2.0","id":req["id"],"result":{"tools":[{"name":"fail","description":"fail","inputSchema":{"type":"object"}}]}}
    else:
        payload = {"jsonrpc":"2.0","id":req["id"],"error":{"code":-32603,"message":"fixture failure"}}
    print(json.dumps(payload), flush=True)
"""

STDERR_SERVER = r"""
import json, sys
sys.stderr.write("x" * 200000)
sys.stderr.flush()
for line in sys.stdin:
    req = json.loads(line)
    method = req.get("method")
    if method == "notifications/initialized":
        continue
    result = {"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{"name":"fixture","version":"1"}} if method == "initialize" else {"tools":[]}
    print(json.dumps({"jsonrpc":"2.0","id":req["id"],"result":result}), flush=True)
"""

SLOW_INIT_SERVER = r"""
import json, sys, time
for line in sys.stdin:
    req = json.loads(line)
    method = req.get("method")
    if method == "notifications/initialized":
        continue
    if method == "initialize":
        time.sleep(0.25)
        result = {"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{"name":"fixture","version":"1"}}
    elif method == "tools/list":
        result = {"tools":[]}
    else:
        continue
    print(json.dumps({"jsonrpc":"2.0","id":req["id"],"result":result}), flush=True)
"""


def client(script: str, timeout: float = 2.0) -> MCPStdioClient:
    return MCPStdioClient(sys.executable, ["-u", "-c", script], timeout=timeout)


class StdioClientTests(unittest.TestCase):
    def test_newline_initialize_list_call(self) -> None:
        instance = client(NEWLINE_SERVER)
        try:
            instance.open()
            self.assertEqual(instance.list_tools()[0]["name"], "echo")
            self.assertEqual(instance.call_tool("echo", {"text": "ok"})["result"]["content"][0]["text"], "ok")
        finally:
            instance.close()

    def test_legacy_content_length_split_chunks(self) -> None:
        instance = client(LEGACY_SERVER)
        try:
            instance.open()
            self.assertEqual(instance.list_tools(), [])
        finally:
            instance.close()

    def test_legacy_content_length_input_auto_fallback(self) -> None:
        instance = client(LEGACY_INPUT_SERVER, timeout=0.15)
        try:
            instance.open()
            self.assertEqual(instance._write_mode, "content-length")
            self.assertEqual(instance.list_tools(), [])
        finally:
            instance.close()

    def test_rpc_error_propagates(self) -> None:
        instance = client(ERROR_SERVER)
        try:
            instance.open()
            with self.assertRaises(MCPRPCError):
                instance.list_tools()
        finally:
            instance.close()

    def test_large_stderr_does_not_block(self) -> None:
        instance = client(STDERR_SERVER)
        try:
            instance.open()
            self.assertEqual(instance.list_tools(), [])
        finally:
            instance.close()

    def test_initialize_timeout_can_be_raised_by_env(self) -> None:
        old_value = os.environ.get("MCP_AGENT_MANAGER_INIT_TIMEOUT")
        os.environ["MCP_AGENT_MANAGER_INIT_TIMEOUT"] = "1"
        try:
            instance = MCPStdioClient(
                sys.executable,
                ["-u", "-c", SLOW_INIT_SERVER],
                timeout=load_initialize_timeout(),
                initialize_timeout=load_initialize_timeout(),
            )
            try:
                instance.open()
                self.assertEqual(instance.list_tools(), [])
            finally:
                instance.close()
        finally:
            if old_value is None:
                os.environ.pop("MCP_AGENT_MANAGER_INIT_TIMEOUT", None)
            else:
                os.environ["MCP_AGENT_MANAGER_INIT_TIMEOUT"] = old_value


class ChatBridgeTests(unittest.TestCase):
    def test_idle_timeout_loads_settings_env_and_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            root = Path(home) / ".config" / "mcp-agent-manager"
            root.mkdir(parents=True)
            (root / "settings.env").write_text('export MCP_AGENT_MANAGER_CHAT_IDLE_TIMEOUT="900"\n')
            (root / "settings.env").chmod(0o600)
            env = {
                **os.environ,
                "HOME": home,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(LIBEXEC),
            }
            loaded = subprocess.run(
                [sys.executable, "-c", "import mcp_chat_session as c; print(c.IDLE_TIMEOUT)"],
                text=True,
                capture_output=True,
                env=env,
                timeout=3,
            )
            self.assertEqual(loaded.returncode, 0, loaded.stderr)
            self.assertEqual(loaded.stdout.strip(), "900")

            env["MCP_AGENT_MANAGER_CHAT_IDLE_TIMEOUT"] = "1200"
            override = subprocess.run(
                [sys.executable, "-c", "import mcp_chat_session as c; print(c.IDLE_TIMEOUT)"],
                text=True,
                capture_output=True,
                env=env,
                timeout=3,
            )
            self.assertEqual(override.returncode, 0, override.stderr)
            self.assertEqual(override.stdout.strip(), "1200")

    def test_tools_call_rpc_error_returns_ok_false(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            root = Path(home) / ".config" / "mcp-agent-manager"
            root.mkdir(parents=True)
            registry = {
                "personal_mcp_servers": {
                    "fixture": {
                        "enabled": True,
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": ["-u", "-c", CALL_ERROR_SERVER],
                    }
                }
            }
            (root / "registry.json").write_text(json.dumps(registry))
            env = os.environ.copy()
            env["HOME"] = home
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            proc = subprocess.Popen(
                [sys.executable, str(LIBEXEC / "mcp_chat_session.py"), "fixture"],
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            stdout, stderr = proc.communicate(
                '{"id":"1","action":"tools.call","tool":"fail","arguments":{}}\n'
                '{"id":"2","action":"close"}\n',
                timeout=4,
            )
            self.assertEqual(proc.returncode, 0, stderr)
            responses = [json.loads(line) for line in stdout.splitlines()]
            self.assertFalse(responses[1]["ok"])
            self.assertIn("JSON-RPC error", responses[1]["error"]["message"])

    def test_jsonl_search_schema_call_close(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            root = Path(home) / ".config" / "mcp-agent-manager"
            root.mkdir(parents=True)
            registry = {
                "personal_mcp_servers": {
                    "fixture": {
                        "enabled": True,
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": ["-u", "-c", NEWLINE_SERVER],
                    }
                }
            }
            (root / "registry.json").write_text(json.dumps(registry))
            env = os.environ.copy()
            env["HOME"] = home
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            proc = subprocess.Popen(
                [sys.executable, str(LIBEXEC / "mcp_chat_session.py"), "fixture"],
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            requests = (
                '{"id":"1","action":"tools.search","query":"echo"}\n'
                '{"id":"2","action":"tools.schema","tool":"echo"}\n'
                '{"id":"3","action":"tools.call","tool":"echo","arguments":{"text":"ok"}}\n'
                '{"id":"4","action":"close"}\n'
            )
            stdout, stderr = proc.communicate(requests, timeout=4)
            self.assertEqual(proc.returncode, 0, stderr)
            responses = [json.loads(line) for line in stdout.splitlines()]
            self.assertTrue(all(response["ok"] for response in responses))
            self.assertEqual(responses[1]["result"]["matches"][0]["name"], "echo")
            self.assertEqual(responses[3]["result"]["content"][0]["text"], "ok")
            self.assertTrue(responses[4]["closed"])

    def test_malformed_json_returns_error_then_closes(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            root = Path(home) / ".config" / "mcp-agent-manager"
            root.mkdir(parents=True)
            registry = {
                "personal_mcp_servers": {
                    "fixture": {
                        "enabled": True,
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": ["-u", "-c", NEWLINE_SERVER],
                    }
                }
            }
            (root / "registry.json").write_text(json.dumps(registry))
            env = os.environ.copy()
            env["HOME"] = home
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            proc = subprocess.Popen(
                [sys.executable, str(LIBEXEC / "mcp_chat_session.py"), "fixture"],
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            stdout, stderr = proc.communicate('not-json\n{"id":"4","action":"close"}\n', timeout=4)
            self.assertEqual(proc.returncode, 0, stderr)
            responses = [json.loads(line) for line in stdout.splitlines()]
            self.assertFalse(responses[1]["ok"])
            self.assertTrue(responses[2]["closed"])

    def test_session_cap_rejects_fifth_session(self) -> None:
        original_root = chat.CHAT_ROOT
        original_lock = chat.LOCK_FILE
        with tempfile.TemporaryDirectory() as tmp:
            chat.CHAT_ROOT = Path(tmp)
            chat.LOCK_FILE = chat.CHAT_ROOT / ".lock"
            for index in range(chat.SESSION_CAP):
                path = chat.CHAT_ROOT / f"active-{index}"
                path.mkdir()
                (path / "pid").write_text(str(os.getpid()))
            with self.assertRaisesRegex(Exception, "active session cap"):
                chat.claim_session("rejected")
        chat.CHAT_ROOT = original_root
        chat.LOCK_FILE = original_lock

    def test_spill_sanitizes_and_does_not_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp)
            (session_dir / "outputs").mkdir()
            first = Path(chat.spill_output(session_dir, "../../escape", {"ok": True}))
            second = Path(chat.spill_output(session_dir, "../../escape", {"ok": True}))
            self.assertEqual(first.parent.resolve(), (session_dir / "outputs").resolve())
            self.assertEqual(second.parent.resolve(), (session_dir / "outputs").resolve())
            self.assertNotEqual(first, second)

    def test_unicode_preview_respects_byte_limit(self) -> None:
        result = chat.format_result({"text": "á" * 13000})
        self.assertLessEqual(len(result["preview"].encode("utf-8")), chat.PREVIEW_LIMIT)

    def test_missing_env_leaves_no_session_dir(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            root = Path(home) / ".config" / "mcp-agent-manager"
            root.mkdir(parents=True)
            registry = {
                "personal_mcp_servers": {
                    "fixture": {
                        "enabled": True,
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": ["-u", "-c", NEWLINE_SERVER],
                        "env": {"NEED": "${MISSING}"},
                    }
                }
            }
            (root / "registry.json").write_text(json.dumps(registry))
            env = os.environ.copy()
            env["HOME"] = home
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            proc = subprocess.run(
                [sys.executable, str(LIBEXEC / "mcp_chat_session.py"), "fixture"],
                text=True,
                capture_output=True,
                env=env,
                timeout=3,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(any((root / "chat-runtime").glob("fixture-*")) if (root / "chat-runtime").exists() else False)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertFalse(json.loads(proc.stdout)["ok"])

    def test_idle_timeout_cleans_session(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            root = Path(home) / ".config" / "mcp-agent-manager"
            root.mkdir(parents=True)
            registry = {
                "personal_mcp_servers": {
                    "fixture": {
                        "enabled": True,
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": ["-u", "-c", NEWLINE_SERVER],
                    }
                }
            }
            (root / "registry.json").write_text(json.dumps(registry))
            env = os.environ.copy()
            env["HOME"] = home
            env["MCP_AGENT_MANAGER_CHAT_IDLE_TIMEOUT"] = "1"
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            proc = subprocess.Popen(
                [sys.executable, str(LIBEXEC / "mcp_chat_session.py"), "fixture"],
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            returncode = proc.wait(timeout=4)
            stdout = proc.stdout.read()
            stderr = proc.stderr.read()
            proc.stdin.close()
            proc.stdout.close()
            proc.stderr.close()
            self.assertEqual(returncode, 0, stderr)
            self.assertIn('"reason": "idle-timeout"', stdout)
            self.assertFalse(any((root / "chat-runtime").glob("fixture-*")))


if __name__ == "__main__":
    unittest.main()
