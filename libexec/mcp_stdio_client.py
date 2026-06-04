#!/usr/bin/env python3
"""MCP stdio client helpers shared by smoke tests and chat runtime."""

from __future__ import annotations

import json
import os
import selectors
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


class MCPClientError(RuntimeError):
    pass


class MCPTimeoutError(MCPClientError):
    pass


class MCPRPCError(MCPClientError):
    def __init__(self, error: Any):
        self.error = error
        super().__init__(f"JSON-RPC error: {error}")


def load_export_env(path: str | os.PathLike[str]) -> Dict[str, str]:
    """Load simple `export KEY=value` lines from secrets.env."""
    env: Dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return env

    for raw_line in p.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith("export "):
            continue
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if len(parts) < 2 or parts[0] != "export":
            continue
        assignment = parts[1]
        if "=" not in assignment:
            continue
        key, value = assignment.split("=", 1)
        env[key] = value
    return env


def redact_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        redacted: Dict[str, Any] = {}
        for k, v in obj.items():
            lowered = str(k).lower()
            sensitive_keys = ("token", "secret", "authorization", "cookie", "password", "api_key", "apikey", "header")
            if any(key in lowered for key in sensitive_keys):
              redacted[k] = "[REDACTED]"
            else:
              redacted[k] = redact_json(v)
        return redacted
    if isinstance(obj, list):
        return [redact_json(v) for v in obj]
    if isinstance(obj, str):
        lowered = obj.lower()
        sensitive_keys = ("token", "secret", "authorization", "cookie", "password", "api_key", "apikey", "header")
        if any(key in lowered for key in sensitive_keys):
            return "[REDACTED]"
    return obj


@dataclass
class MCPStdioClient:
    command: str
    args: List[str] = field(default_factory=list)
    env: Optional[Dict[str, str]] = None
    timeout: float = 8.0
    initialize_timeout: Optional[float] = None
    proc: Optional[subprocess.Popen] = field(default=None, init=False)
    _stdout_buffer: bytearray = field(default_factory=bytearray, init=False)
    _next_id: int = field(default=1, init=False)
    _write_mode: str = field(default="newline", init=False)

    def open(self) -> None:
        if self.proc is not None:
            return
        for mode in ("newline", "content-length"):
            self._write_mode = mode
            self._spawn()
            try:
                result = self.request(
                    {
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "mcp-agent-manager", "version": "1.0"},
                        },
                    },
                    timeout=self.initialize_timeout or self.timeout,
                )
                if "result" not in result:
                    raise MCPClientError(f"initialize failed: {result}")
                self.notify({"method": "notifications/initialized"})
                return
            except (MCPTimeoutError, BrokenPipeError, OSError):
                self._stop_process()
                if mode == "newline":
                    continue
                raise
            except Exception:
                self._stop_process()
                raise

    def _spawn(self) -> None:
        merged_env = os.environ.copy()
        if self.env:
            merged_env.update(self.env)
        self.proc = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=merged_env,
            bufsize=0,
        )

    def close(self) -> None:
        self._stop_process()

    def _stop_process(self) -> None:
        if self.proc is None:
            return
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=1)
        except Exception:
            try:
                self.proc.kill()
                self.proc.wait(timeout=1)
            except Exception:
                pass
        try:
            if self.proc.stdout and not self.proc.stdout.closed:
                self.proc.stdout.close()
        except Exception:
            pass
        self.proc = None
        self._stdout_buffer.clear()

    def _next_request_id(self) -> int:
        req_id = self._next_id
        self._next_id += 1
        return req_id

    def notify(self, payload: Dict[str, Any]) -> None:
        payload.setdefault("jsonrpc", "2.0")
        self._write(payload)

    def request(self, payload: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        payload.setdefault("jsonrpc", "2.0")
        if "id" not in payload:
            payload["id"] = self._next_request_id()
        self._write(payload)
        response = self._read_response(int(payload["id"]), timeout=timeout)
        if "error" in response:
            raise MCPRPCError(response["error"])
        return response

    def list_tools(self) -> List[Dict[str, Any]]:
        result = self.request({"method": "tools/list"})
        payload = result.get("result")
        if not isinstance(payload, dict) or not isinstance(payload.get("tools"), list):
            raise MCPClientError("tools/list returned invalid payload")
        return payload["tools"]

    def call_tool(self, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self.request(
            {
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            }
        )

    def _write(self, payload: Dict[str, Any]) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise MCPClientError("client not open")
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if self._write_mode == "content-length":
            raw = f"Content-Length: {len(raw)}\r\n\r\n".encode("utf-8") + raw
        else:
            raw += b"\n"
        self.proc.stdin.write(raw)
        self.proc.stdin.flush()

    def _read_response(self, expected_id: int, timeout: Optional[float] = None) -> Dict[str, Any]:
        if self.proc is None or self.proc.stdout is None:
            raise MCPClientError("client not open")
        deadline = time.monotonic() + (timeout or self.timeout)
        selector = selectors.DefaultSelector()
        selector.register(self.proc.stdout, selectors.EVENT_READ)

        try:
            while time.monotonic() < deadline:
                maybe = self._extract_message(expected_id)
                if maybe is not None:
                    return maybe
                events = selector.select(timeout=0.25)
                if not events and self.proc.poll() is not None:
                    break
                for _key, _mask in events:
                    chunk = os.read(self.proc.stdout.fileno(), 4096)
                    if chunk:
                        self._stdout_buffer.extend(chunk)
            maybe = self._extract_message(expected_id)
            if maybe is not None:
                return maybe
        finally:
            selector.close()

        raise MCPTimeoutError(f"timeout waiting for response id={expected_id}")

    def _extract_message(self, expected_id: int) -> Optional[Dict[str, Any]]:
        while self._stdout_buffer:
            if self._stdout_buffer.lower().startswith(b"content-length:"):
                message = self._extract_framed_message()
            else:
                message = self._extract_line_message()
            if message is None:
                return None
            if message.get("id") == expected_id:
                return message
        return None

    def _extract_framed_message(self) -> Optional[Dict[str, Any]]:
        marker = b"\r\n\r\n"
        if marker not in self._stdout_buffer:
            return None
        header, payload = self._stdout_buffer.split(marker, 1)
        header_text = header.decode("utf-8", errors="ignore")
        length = None
        for line in header_text.splitlines():
            if line.lower().startswith("content-length:"):
                try:
                    length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    length = None
                break
        if length is None:
            raise MCPClientError("invalid Content-Length header")
        if len(payload) < length:
            return None
        body = bytes(payload[:length])
        del self._stdout_buffer[: len(header) + len(marker) + length]
        return json.loads(body.decode("utf-8"))

    def _extract_line_message(self) -> Optional[Dict[str, Any]]:
        newline = self._stdout_buffer.find(b"\n")
        if newline == -1:
            return None
        raw_line = bytes(self._stdout_buffer[:newline]).strip()
        del self._stdout_buffer[: newline + 1]
        if not raw_line:
            return None
        try:
            return json.loads(raw_line.decode("utf-8"))
        except json.JSONDecodeError:
            return None
