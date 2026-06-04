#!/usr/bin/env python3
"""Synthetic regression tests for persistent MCP tool metadata cache."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBEXEC = ROOT / "libexec"
MAM = ROOT / "bin" / "mcp-agent-manager"

sys.path.insert(0, str(LIBEXEC))
import mcp_tool_cache as cache  # noqa: E402


COUNTING_SERVER = r"""
import json, os, sys
from pathlib import Path
marker = Path(os.environ["TOOLS_LIST_MARKER"])
for line in sys.stdin:
    req = json.loads(line)
    method = req.get("method")
    if method == "notifications/initialized":
        continue
    if method == "initialize":
        result = {"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{"name":"fixture","version":"1"}}
    elif method == "tools/list":
        count = int(marker.read_text()) if marker.exists() else 0
        marker.write_text(str(count + 1))
        result = {"tools":[{"name":"echo","description":"echo text","inputSchema":{"type":"object"}},{"name":"new-tool","description":"not searched","inputSchema":{"type":"object"}}]}
    elif method == "tools/call":
        result = {"content":[{"type":"text","text":req["params"]["name"]}]}
    else:
        continue
    print(json.dumps({"jsonrpc":"2.0","id":req["id"],"result":result}), flush=True)
"""


class ToolCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.root = self.home / ".config" / "mcp-agent-manager"
        self.root.mkdir(parents=True)
        self.marker = self.home / "tools-list-count"
        self.entry = {
            "enabled": True,
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-u", "-c", COUNTING_SERVER],
            "env": {"TOOLS_LIST_MARKER": str(self.marker), "API_TOKEN": "${SECRET_REF}"},
            "target": "all",
        }
        self.disabled_entry = {
            **self.entry,
            "enabled": False,
            "env": {"TOOLS_LIST_MARKER": str(self.marker)},
        }
        self.registry = {"personal_mcp_servers": {"fixture": self.entry, "disabled": self.disabled_entry}}
        (self.root / "registry.json").write_text(json.dumps(self.registry))
        (self.root / "secrets.env").write_text('export SECRET_REF="secret-value"\n')
        self.env = {**os.environ, "HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"}
        self.original_root = cache.CACHE_ROOT
        cache.CACHE_ROOT = self.root / "tool-cache"

    def tearDown(self) -> None:
        cache.CACHE_ROOT = self.original_root
        self.tmp.cleanup()

    def run_mam(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(MAM), *args], text=True, capture_output=True, env=self.env, timeout=10)

    def test_write_permissions_redaction_traversal_and_fingerprint(self) -> None:
        payload = cache.write_fresh(
            "fixture",
            self.entry,
            [{"name": "echo", "description": "Authorization: Bearer secret", "inputSchema": {"api_token": "secret"}}],
        )
        path = self.root / "tool-cache" / "fixture.json"
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertNotIn("secret", json.dumps(payload).lower())
        self.assertIsNotNone(cache.load_cache("fixture", entry=self.entry))
        changed = {**self.entry, "args": ["changed"]}
        self.assertIsNone(cache.load_cache("fixture", entry=changed))
        with self.assertRaises(ValueError):
            cache.cache_path("../../escape")

    def test_cli_refresh_preview_apply_list_and_search_local(self) -> None:
        preview = self.run_mam("tools", "refresh", "fixture")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("Preview only", preview.stdout)
        self.assertFalse(self.marker.exists())

        refreshed = self.run_mam("tools", "refresh", "fixture", "--apply")
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
        self.assertEqual(self.marker.read_text(), "1")

        listed = self.run_mam("tools", "list", "fixture")
        searched = self.run_mam("tools", "search", "echo", "--name", "fixture")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(searched.returncode, 0, searched.stderr)
        self.assertIn("echo", listed.stdout)
        self.assertIn("echo", searched.stdout)
        self.assertEqual(self.marker.read_text(), "1")

        traversal = self.run_mam("tools", "search", "echo", "--name", "../../escape")
        self.assertEqual(traversal.returncode, 1)
        ambiguous = self.run_mam("tools", "refresh", "fixture", "--all")
        self.assertEqual(ambiguous.returncode, 1)

    def test_index_and_search_skip_disabled_servers_by_default(self) -> None:
        disabled_cache = self.root / "tool-cache" / "disabled.json"
        disabled_cache.parent.mkdir(mode=0o700, exist_ok=True)
        disabled_cache.write_text(
            json.dumps(
                {
                    "version": 1,
                    "name": "disabled",
                    "status": "fresh",
                    "registry_fingerprint": cache.registry_fingerprint(self.disabled_entry),
                    "tools": [{"name": "disabled-only", "description": "hidden disabled tool", "inputSchema": {}}],
                }
            )
            + "\n"
        )
        disabled_cache.chmod(0o600)

        indexed = self.run_mam("tools", "index", "--apply")
        self.assertEqual(indexed.returncode, 0, indexed.stderr)
        index_text = (self.root / "tool-index.jsonl").read_text() if (self.root / "tool-index.jsonl").exists() else ""
        self.assertNotIn("disabled-only", index_text)

        searched = self.run_mam("tools", "search", "disabled-only")
        self.assertEqual(searched.returncode, 0, searched.stderr)
        self.assertNotIn("disabled-only", searched.stdout)

    def test_bridge_lazy_fill_then_reuse_and_direct_unknown_call(self) -> None:
        requests = (
            '{"id":"1","action":"tools.search","query":"echo"}\n'
            '{"id":"2","action":"tools.schema","tool":"echo"}\n'
            '{"id":"3","action":"tools.call","tool":"unknown-new-tool","arguments":{}}\n'
            '{"id":"4","action":"close"}\n'
        )
        for expected_count in ("1", "1"):
            proc = subprocess.run(
                [sys.executable, str(LIBEXEC / "mcp_chat_session.py"), "fixture"],
                input=requests,
                text=True,
                capture_output=True,
                env=self.env,
                timeout=10,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            responses = [json.loads(line) for line in proc.stdout.splitlines()]
            self.assertTrue(responses[3]["ok"])
            self.assertEqual(responses[3]["result"]["content"][0]["text"], "unknown-new-tool")
            self.assertEqual(self.marker.read_text(), expected_count)


if __name__ == "__main__":
    unittest.main()
