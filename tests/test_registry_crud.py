#!/usr/bin/env python3
"""Synthetic regression tests for personal MCP quick CRUD."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAM = ROOT / "bin" / "mcp-agent-manager"


class RegistryCrudTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.root = self.home / ".config" / "mcp-agent-manager"
        self.root.mkdir(parents=True)
        self.registry = self.root / "registry.json"
        self.state = self.root / "managed-state.json"
        self.registry.write_text(
            json.dumps(
                {
                    "version": 1,
                    "unmanaged_mcp_servers": [],
                    "personal_mcp_servers": {
                        "personal-off": {
                            "enabled": False,
                            "description": "disabled personal fixture",
                            "transport": "stdio",
                            "command": "fixture-command",
                            "args": [],
                            "env": {},
                            "target": "codex",
                        },
                        "personal-on": {
                            "enabled": True,
                            "description": "enabled personal fixture",
                            "transport": "stdio",
                            "command": "fixture-command",
                            "args": [],
                            "env": {},
                            "target": "all",
                        },
                        "teleport-owned": {
                            "enabled": False,
                            "description": "teleport fixture",
                            "transport": "stdio",
                            "command": "tsh",
                            "args": ["mcp", "connect", "fixture"],
                            "env": {},
                            "target": "all",
                            "_source": "teleport",
                        },
                    },
                },
                indent=2,
            )
            + "\n"
        )
        self.state.write_text('{"version":1,"generated_files":[]}\n')
        (self.root / "deferred.json").write_text('{"version":1,"deferred":{}}\n')
        self.registry.chmod(0o600)
        self.state.chmod(0o600)
        self.cache_dir = self.root / "tool-cache"
        self.cache_dir.mkdir(mode=0o700)
        (self.cache_dir / "personal-off.json").write_text(
            '{"version":1,"name":"personal-off","status":"fresh","tools":[]}\n'
        )
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "PYTHONDONTWRITEBYTECODE": "1",
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_mam(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(MAM), *args],
            text=True,
            capture_output=True,
            env=self.env,
            timeout=20,
        )

    def load_registry(self) -> dict:
        return json.loads(self.registry.read_text())

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_preview_does_not_mutate(self) -> None:
        registry_before = self.digest(self.registry)
        state_before = self.digest(self.state)
        result = self.run_mam("enable", "personal-off")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Preview only", result.stdout)
        self.assertIn("mcp-managed-personal-off.toml", result.stdout)
        self.assertEqual(self.digest(self.registry), registry_before)
        self.assertEqual(self.digest(self.state), state_before)

    def test_enable_disable_remove_and_permissions(self) -> None:
        enabled = self.run_mam("enable", "personal-off", "--apply")
        self.assertEqual(enabled.returncode, 0, enabled.stderr)
        self.assertTrue(self.load_registry()["personal_mcp_servers"]["personal-off"]["enabled"])
        codex_agent = self.home / ".codex" / "agents" / "mcp-managed-personal-off.toml"
        self.assertTrue(codex_agent.exists())
        self.assertEqual(stat.S_IMODE(self.registry.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o600)

        disabled = self.run_mam("disable", "personal-off", "--apply")
        self.assertEqual(disabled.returncode, 0, disabled.stderr)
        self.assertFalse(self.load_registry()["personal_mcp_servers"]["personal-off"]["enabled"])
        self.assertFalse(codex_agent.exists())
        stale_cache = json.loads((self.cache_dir / "personal-off.json").read_text())
        self.assertEqual(stale_cache["status"], "stale")
        self.assertEqual(stale_cache["stale_reason"], "disabled")

        removed = self.run_mam("remove", "personal-off", "--apply")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertNotIn("personal-off", self.load_registry()["personal_mcp_servers"])
        self.assertFalse((self.cache_dir / "personal-off.json").exists())

    def test_rejects_teleport_missing_name_unknown_option_and_noop(self) -> None:
        backups = self.root / "backups"
        teleport = self.run_mam("enable", "teleport-owned", "--apply")
        self.assertEqual(teleport.returncode, 1)
        self.assertIn("managed by teleport", teleport.stderr)
        self.assertFalse(backups.exists())

        missing = self.run_mam("disable", "missing")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("name not found", missing.stderr)

        no_name = self.run_mam("remove")
        self.assertEqual(no_name.returncode, 1)
        self.assertIn("missing name", no_name.stderr)

        unknown = self.run_mam("enable", "personal-off", "--bogus")
        self.assertEqual(unknown.returncode, 1)
        self.assertIn("unknown option", unknown.stderr)

        noop = self.run_mam("disable", "personal-off", "--apply")
        self.assertEqual(noop.returncode, 0, noop.stderr)
        self.assertIn("NOOP", noop.stdout)
        self.assertFalse(backups.exists())

    def test_renderer_collision_rolls_back_registry_state_and_generated(self) -> None:
        collision = self.home / ".codex" / "agents" / "mcp-managed-personal-off.toml"
        collision.parent.mkdir(parents=True)
        collision.write_text("user-owned\n")
        registry_before = self.registry.read_text()
        state_before = self.state.read_text()

        result = self.run_mam("enable", "personal-off", "--apply")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Restoring scoped backup", result.stderr)
        self.assertEqual(self.registry.read_text(), registry_before)
        self.assertEqual(self.state.read_text(), state_before)
        self.assertEqual(collision.read_text(), "user-owned\n")


if __name__ == "__main__":
    unittest.main()
