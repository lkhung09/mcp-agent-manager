#!/usr/bin/env python3
"""Synthetic regression tests for Teleport sync health gate."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAM = ROOT / "bin" / "mcp-agent-manager"

FAKE_TSH = r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
if args[:3] == ["mcp", "ls", "--format=json"]:
    print(json.dumps([
        {"metadata": {"name": "fixture-good"}},
        {"metadata": {"name": "fixture-bad"}},
    ]))
    raise SystemExit(0)

if args[:2] == ["mcp", "connect"]:
    marker = os.environ.get("MOCK_CONNECT_MARKER")
    if marker:
        Path(marker).touch()
    name = args[-1]
    for line in sys.stdin:
        request = json.loads(line)
        method = request.get("method")
        if method == "notifications/initialized":
            continue
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": name, "version": "1"},
            }
            payload = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        elif method == "tools/list" and name == "fixture-bad" and os.environ.get("MOCK_BAD", "1") == "1":
            payload = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {
                    "code": -32603,
                    "message": "Authorization: Bearer secret-token fixture failure",
                },
            }
        else:
            payload = {"jsonrpc": "2.0", "id": request["id"], "result": {"tools": []}}
        print(json.dumps(payload), flush=True)
    raise SystemExit(0)

raise SystemExit(2)
"""


class SyncHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.bin_dir = self.home / "bin"
        self.bin_dir.mkdir()
        self.tsh = self.bin_dir / "tsh"
        self.tsh.write_text(FAKE_TSH)
        self.tsh.chmod(0o755)
        state_dir = self.home / ".config" / "mcp-agent-manager"
        state_dir.mkdir(parents=True)
        (state_dir / "registry.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "unmanaged_mcp_servers": [],
                    "personal_mcp_servers": {
                        "teleport-fixture-bad": {
                            "enabled": True,
                            "description": "stale enabled fixture",
                            "transport": "stdio",
                            "command": "tsh",
                            "args": ["mcp", "connect", "fixture-bad"],
                            "env": {},
                            "target": "all",
                            "_source": "teleport",
                        },
                        "teleport-fixture-removed": {
                            "enabled": False,
                            "description": "removed catalog fixture",
                            "transport": "stdio",
                            "command": "tsh",
                            "args": ["mcp", "connect", "fixture-removed"],
                            "env": {},
                            "target": "all",
                            "_source": "teleport",
                            "_removed_from_catalog": True,
                        }
                    },
                }
            )
            + "\n"
        )
        (state_dir / "managed-state.json").write_text('{"version":1,"generated_files":[]}\n')
        (state_dir / "deferred.json").write_text('{"version":1,"deferred":{}}\n')
        (self.home / ".codex").mkdir()
        (self.home / ".codex" / "config.toml").write_text("[mcp_servers]\n")
        (self.home / ".claude.json").write_text('{"mcpServers":{}}\n')
        self.registry = state_dir / "registry.json"
        self.cache_dir = state_dir / "tool-cache"
        self.cache_dir.mkdir()
        (self.cache_dir / "teleport-fixture-removed.json").write_text(
            '{"version":1,"name":"teleport-fixture-removed","status":"fresh","tools":[]}\n'
        )
        (self.cache_dir / "teleport-fixture-bad.json").write_text(
            '{"version":1,"name":"teleport-fixture-bad","status":"fresh","tools":[]}\n'
        )
        self.env = os.environ.copy()
        self.env.update(
            {
                "HOME": str(self.home),
                "PATH": f"{self.bin_dir}:{self.env.get('PATH', '')}",
                "TSH_BIN": str(self.tsh),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_mam(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(MAM), *args],
            text=True,
            capture_output=True,
            env=env or self.env,
            timeout=20,
        )

    def load_registry(self) -> dict:
        return json.loads(self.registry.read_text())

    def test_preview_does_not_smoke_or_mutate(self) -> None:
        marker = self.home / "connect-marker"
        env = {**self.env, "MOCK_CONNECT_MARKER": str(marker)}
        before = self.registry.read_text()
        result = self.run_mam("sync", "--target", "all", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Health gate runs during --apply", result.stdout)
        self.assertFalse(marker.exists())
        self.assertEqual(self.registry.read_text(), before)

    def test_quarantine_render_recovery_and_strict_apply(self) -> None:
        first = self.run_mam("sync", "--apply", "--target", "all")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("QUARANTINED (1)", first.stdout)
        servers = self.load_registry()["personal_mcp_servers"]
        self.assertTrue(servers["teleport-fixture-good"]["enabled"])
        self.assertNotIn("teleport-fixture-removed", servers)
        self.assertFalse((self.cache_dir / "teleport-fixture-removed.json").exists())
        good_cache = json.loads((self.cache_dir / "teleport-fixture-good.json").read_text())
        self.assertEqual(good_cache["status"], "fresh")
        bad = servers["teleport-fixture-bad"]
        self.assertFalse(bad["enabled"])
        self.assertEqual(bad["_health"]["status"], "quarantined")
        self.assertIn("checked_at", bad["_health"])
        self.assertNotIn("secret-token", bad["_health"]["error"])
        self.assertLessEqual(len(bad["_health"]["error"]), 512)
        bad_cache = json.loads((self.cache_dir / "teleport-fixture-bad.json").read_text())
        self.assertEqual(bad_cache["status"], "stale")
        self.assertEqual(bad_cache["stale_reason"], "quarantined")

        rendered = self.run_mam("render", "--apply")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertTrue((self.home / ".claude" / "agents" / "mcp-managed-teleport-fixture-good.md").exists())
        self.assertFalse((self.home / ".claude" / "agents" / "mcp-managed-teleport-fixture-bad.md").exists())

        strict = self.run_mam("apply", "--apply")
        self.assertEqual(strict.returncode, 0, strict.stderr)

        recovered = self.run_mam("sync", "--apply", "--target", "all", env={**self.env, "MOCK_BAD": "0"})
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        bad = self.load_registry()["personal_mcp_servers"]["teleport-fixture-bad"]
        self.assertTrue(bad["enabled"])
        self.assertEqual(bad["_health"]["status"], "healthy")
        self.assertNotIn("error", bad["_health"])


if __name__ == "__main__":
    unittest.main()
