#!/usr/bin/env python3
"""Public readiness checks for portability and repo hygiene."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAM = ROOT / "bin" / "mcp-agent-manager"
BAD_ROOT = "/Users/" + "kimhung/Documents/MCP/" + "mcp-agent-manager/"


def write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


class PublicHygieneTests(unittest.TestCase):
    def test_vietnamese_readme_exists_and_matches_public_shape(self) -> None:
        english = (ROOT / "README.md").read_text()
        vietnamese_path = ROOT / "README.vi.md"
        self.assertTrue(vietnamese_path.exists())
        text = vietnamese_path.read_text()

        self.assertIn("[Tiếng Việt](README.vi.md)", english)
        self.assertIn("[English](README.md)", text)

        required = [
            "## Đây là gì",
            "## Không phải là gì",
            "## Phù hợp với ai",
            "## Cách hoạt động",
            "## MCP process sống bao lâu",
            "### 0. Yêu cầu cài đặt",
            "### 1. Cài đặt",
            "### 2. Chạy",
            "### 3. Kiểm tra",
            "## Gỡ / quay lui",
            "## Tính năng",
            "### Đang hỗ trợ",
            "### Helper command đang hỗ trợ",
            "### Chưa hỗ trợ",
        ]
        for item in required:
            self.assertIn(item, text)

        self.assertIn("```mermaid", text)
        self.assertIn("Luồng chính đang hỗ trợ", text)
        self.assertIn("Claude Code agent", text)
        self.assertIn("Codex agent", text)
        self.assertIn("One scoped MCP", text)
        self.assertIn("MCP_AGENT_MANAGER_CHAT_IDLE_TIMEOUT", text)
        self.assertIn("Default idle timeout: `300` giây", text)
        self.assertIn("curl -fsSL", text)
        self.assertIn("raw.githubusercontent.com/lkhung09/mcp-agent-manager/main/install.sh", text)
        self.assertIn("https://github.com/lkhung09/mcp-agent-manager.git", text)
        self.assertNotIn("<owner>", text)
        self.assertNotIn("<your-fork-or-clone-url>", text)
        self.assertIn("brew install git python jq zip ruby", text)
        self.assertIn("sudo apt install -y bash git python3 jq zip ruby", text)
        self.assertIn("source ~/.bashrc  # Ubuntu bash", text)
        self.assertIn("`doctor`", text)
        self.assertIn("`tools list/search/refresh/index`", text)
        self.assertIn("`sync`", text)
        self.assertIn("`add`, `edit` commands", text)
        self.assertIn("Hermes/OpenClaw rendering", text)

    def test_readme_is_non_dev_friendly(self) -> None:
        text = (ROOT / "README.md").read_text()
        required_sections = [
            "## What it is",
            "## What it is not",
            "## Who it is for",
            "## How it works",
            "## MCP process lifetime",
            "### 0. Install requirements",
            "### 1. Install",
            "### 2. Run",
            "### 3. Check",
            "## Remove / Undo",
            "## Features",
            "## Advanced commands",
        ]
        for section in required_sections:
            self.assertIn(section, text)

        self.assertIn("```mermaid", text)
        self.assertIn("Main supported flow today", text)
        self.assertIn("Claude Code agent", text)
        self.assertIn("Codex agent", text)
        self.assertIn("One scoped MCP", text)
        self.assertIn("MCP process lifetime", text)
        self.assertIn("Redacted tool metadata cache", text)
        self.assertIn("No giant MCP tool schema", text)
        self.assertIn("### Supported now", text)
        self.assertIn("### Supported command helpers", text)
        self.assertIn("### Not supported yet", text)
        self.assertIn("Claude Code agent rendering", text)
        self.assertIn("Hermes/OpenClaw rendering", text)
        self.assertIn("curl -fsSL", text)
        self.assertIn("raw.githubusercontent.com/lkhung09/mcp-agent-manager/main/install.sh", text)
        self.assertIn("https://github.com/lkhung09/mcp-agent-manager.git", text)
        self.assertNotIn("<owner>", text)
        self.assertNotIn("<your-fork-or-clone-url>", text)
        self.assertIn("Manual install", text)
        self.assertIn("If you prefer to read the installer first", text)
        self.assertIn("brew install git python jq zip ruby", text)
        self.assertIn("sudo apt install -y bash git python3 jq zip ruby", text)
        self.assertIn("source ~/.bashrc  # Ubuntu bash", text)
        self.assertIn("Teleport `tsh` is optional", text)
        self.assertIn("MCP_AGENT_MANAGER_CHAT_IDLE_TIMEOUT", text)
        self.assertIn("Default idle timeout: `300` seconds", text)
        self.assertIn("Configurable chat-session idle timeout", text)
        self.assertIn("`doctor`", text)
        self.assertIn("`tools list/search/refresh/index`", text)
        self.assertIn("`sync`", text)
        self.assertIn("`add`, `edit` commands", text)
        self.assertLess(text.index("### 1. Install"), text.index("## Advanced commands"))
        self.assertLess(text.index("## Remove / Undo"), text.index("## Advanced commands"))
        self.assertIn("Most commands preview first.", text)
        self.assertIn("File changes need `--apply`.", text)

    def test_cli_help_matches_public_command_surface(self) -> None:
        help_commands = [
            [],
            ["doctor"],
            ["bootstrap"],
            ["list"],
            ["render"],
            ["apply"],
            ["sync"],
            ["enable"],
            ["disable"],
            ["remove"],
            ["run"],
            ["chat-session"],
            ["tools"],
            ["install"],
            ["add"],
            ["edit"],
        ]
        for command in help_commands:
            args = [str(MAM), *command, "--help"] if command else [str(MAM), "--help"]
            result = subprocess.run(
                args,
                text=True,
                capture_output=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("slug", result.stdout.lower())
            self.assertNotIn("<slug>", result.stdout)
            self.assertNotIn("--slug", result.stdout)

        main_help = subprocess.run(
            [str(MAM), "--help"],
            text=True,
            capture_output=True,
            timeout=20,
        ).stdout
        self.assertIn("Common flow:", main_help)
        self.assertIn("mcp-agent-manager bootstrap", main_help)
        self.assertIn("Optional Teleport catalog sync", main_help)
        self.assertIn("source ~/.bashrc", main_help)
        self.assertNotIn("Ví dụ nhanh", main_help)

        doctor_help = subprocess.run(
            [str(MAM), "doctor", "--help"],
            text=True,
            capture_output=True,
            timeout=20,
        ).stdout
        self.assertIn("tsh version when available (optional; only needed for Teleport sync)", doctor_help)

        install_help = subprocess.run(
            [str(MAM), "install", "--help"],
            text=True,
            capture_output=True,
            timeout=20,
        ).stdout
        self.assertIn("~/.zshrc for zsh", install_help)
        self.assertIn("~/.bashrc for bash", install_help)
        self.assertIn("~/.profile fallback", install_help)
        self.assertIn("source ~/.bashrc", install_help)
        self.assertNotIn("Also update ~/.zshrc idempotently", install_help)

        sync_help = subprocess.run(
            [str(MAM), "sync", "--help"],
            text=True,
            capture_output=True,
            timeout=20,
        ).stdout
        self.assertIn("Optional helper: sync Teleport MCP catalog", sync_help)
        self.assertIn("mcp-agent-manager sync --apply --target all", sync_help)

        list_help = subprocess.run(
            [str(MAM), "list", "--help"],
            text=True,
            capture_output=True,
            timeout=20,
        ).stdout
        self.assertIn("Use the name column as <name>", list_help)

        tools_help = subprocess.run(
            [str(MAM), "tools", "--help"],
            text=True,
            capture_output=True,
            timeout=20,
        ).stdout
        self.assertIn("Use <name> values from: mcp-agent-manager list", tools_help)

        run_help = subprocess.run(
            [str(MAM), "run", "--help"],
            text=True,
            capture_output=True,
            timeout=20,
        ).stdout
        self.assertIn("Helper command for generated agents and runtimes", run_help)

        chat_help = subprocess.run(
            [str(MAM), "chat-session", "--help"],
            text=True,
            capture_output=True,
            timeout=20,
        ).stdout
        self.assertIn("Helper command for chat runtimes that speak JSONL", chat_help)

    def test_curl_installer_clones_updates_and_stays_within_temp_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            home = work / "home"
            origin = work / "origin"
            install_dir = home / ".local" / "share" / "mcp-agent-manager"
            home.mkdir()

            shutil.copytree(
                ROOT,
                origin,
                ignore=shutil.ignore_patterns(
                    ".git",
                    "__pycache__",
                    "*.pyc",
                    ".pytest_cache",
                ),
            )
            subprocess.run(["git", "init", "-b", "main"], cwd=origin, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=origin, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=origin, check=True)
            subprocess.run(["git", "add", "."], cwd=origin, check=True)
            subprocess.run(["git", "commit", "-m", "fixture"], cwd=origin, check=True, capture_output=True)

            env = {
                **os.environ,
                "HOME": str(home),
                "MAM_REPO_URL": f"file://{origin}",
                "MAM_INSTALL_DIR": str(install_dir),
                "PYTHONDONTWRITEBYTECODE": "1",
                "SHELL": "/bin/bash",
            }

            for _ in range(2):
                result = subprocess.run(
                    [str(ROOT / "install.sh")],
                    text=True,
                    capture_output=True,
                    env=env,
                    timeout=40,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn(BAD_ROOT, result.stdout)
                self.assertNotIn(BAD_ROOT, result.stderr)

            self.assertTrue((install_dir / ".git").exists())
            cli_link = home / ".local" / "bin" / "mcp-agent-manager"
            skill_link = home / ".claude" / "skills" / "mcp-agent-manager"
            codex_link = home / ".codex" / "skills" / "mcp-agent-manager"
            self.assertTrue(cli_link.is_symlink())
            self.assertEqual(cli_link.resolve(), install_dir.resolve() / "bin" / "mcp-agent-manager")
            self.assertTrue(skill_link.is_symlink())
            self.assertEqual(skill_link.resolve(), install_dir.resolve() / "skill")
            self.assertTrue(codex_link.is_symlink())
            self.assertTrue((home / ".bashrc").exists())
            self.assertFalse((Path.home() / ".local" / "share" / "mcp-agent-manager-public-test").exists())

    def test_install_script_and_doctor_match_ubuntu_optional_teleport_policy(self) -> None:
        install_text = (ROOT / "install.sh").read_text()
        doctor_text = (ROOT / "lib" / "doctor.sh").read_text()

        self.assertIn("apt-get install -y $required_packages", install_text)
        self.assertIn("https://github.com/lkhung09/mcp-agent-manager.git", install_text)
        self.assertNotIn("<owner>", install_text)
        self.assertIn('required_packages="bash git python3 jq zip ruby"', install_text)
        self.assertIn('source "$HOME/.bashrc"  # bash on Ubuntu', install_text)
        self.assertIn("optional; only needed for Teleport sync", doctor_text)

    def test_install_and_doctor_stay_within_temp_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            bin_dir = home / "bin"
            bin_dir.mkdir()
            write_executable(
                bin_dir / "tsh",
                """#!/usr/bin/env python3
import sys
if sys.argv[1:] == ["version"]:
    print("Teleport v1.0.0")
raise SystemExit(0)
""",
            )
            env = {
                **os.environ,
                "HOME": str(home),
                "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                "PYTHONDONTWRITEBYTECODE": "1",
            }

            install = subprocess.run(
                [str(MAM), "install", "--apply"],
                text=True,
                capture_output=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            self.assertNotIn(BAD_ROOT, install.stdout)

            cli_link = home / ".local" / "bin" / "mcp-agent-manager"
            skill_link = home / ".claude" / "skills" / "mcp-agent-manager"
            codex_link = home / ".codex" / "skills" / "mcp-agent-manager"
            zip_file = home / ".config" / "mcp-agent-manager" / "dist" / "mcp-agent-manager-skill.zip"
            self.assertTrue(cli_link.is_symlink())
            self.assertEqual(cli_link.resolve(), ROOT / "bin" / "mcp-agent-manager")
            self.assertTrue(skill_link.is_symlink())
            self.assertEqual(skill_link.resolve(), ROOT / "skill")
            self.assertTrue(codex_link.is_symlink())
            self.assertTrue(zip_file.exists())
            self.assertEqual(stat.S_IMODE(zip_file.stat().st_mode), 0o600)

            doctor = subprocess.run(
                [str(MAM), "doctor"],
                text=True,
                capture_output=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            self.assertNotIn(BAD_ROOT, doctor.stdout)
            self.assertNotIn(BAD_ROOT, doctor.stderr)

    def test_bootstrap_preview_and_apply_on_fresh_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".codex").mkdir()
            (home / ".claude").mkdir()
            (home / ".codex" / "config.toml").write_text(
                """
[mcp_servers.fixture]
command = "python3"
args = ["-u", "-c", "print('fixture')"]
enabled = true
""".lstrip()
            )
            (home / ".claude.json").write_text('{"mcpServers":{}}\n')

            env = {
                **os.environ,
                "HOME": str(home),
                "PYTHONDONTWRITEBYTECODE": "1",
            }

            preview = subprocess.run(
                [str(MAM), "bootstrap"],
                text=True,
                capture_output=True,
                env=env,
                timeout=20,
            )
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertIn("Would write registry.json (1 entries)", preview.stdout)
            self.assertFalse((home / ".config" / "mcp-agent-manager" / "registry.json").exists())

            apply = subprocess.run(
                [str(MAM), "bootstrap", "--apply"],
                text=True,
                capture_output=True,
                env=env,
                timeout=20,
            )
            self.assertEqual(apply.returncode, 0, apply.stderr)
            root = home / ".config" / "mcp-agent-manager"
            self.assertTrue((root / "registry.json").exists())
            self.assertTrue((root / "deferred.json").exists())
            self.assertTrue((root / "managed-state.json").exists())
            self.assertNotIn(BAD_ROOT, apply.stdout)

    def test_render_uses_optional_site_map_example_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".config" / "mcp-agent-manager"
            root.mkdir(parents=True)
            (root / "registry.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "unmanaged_mcp_servers": [],
                        "personal_mcp_servers": {
                            "demo-openstack-demo_site_1": {
                                "enabled": True,
                                "description": "openstack fixture",
                                "transport": "stdio",
                                "command": "tsh",
                                "args": ["mcp", "connect", "fixture"],
                                "env": {},
                                "target": "all",
                            }
                        },
                    }
                )
                + "\n"
            )
            (root / "managed-state.json").write_text('{"version":1,"generated_files":[]}\n')
            (root / "site-map.json").write_text(
                json.dumps(
                    {
                        "DEMO_SITE_1": {
                            "alias": "demo-alias-1",
                            "name": "demo-openstack-demo_site_1",
                        }
                    },
                    indent=2,
                )
                + "\n"
            )

            env = {
                **os.environ,
                "HOME": str(home),
                "PYTHONDONTWRITEBYTECODE": "1",
            }

            rendered = subprocess.run(
                [str(MAM), "render", "--apply"],
                text=True,
                capture_output=True,
                env=env,
                timeout=20,
            )
            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            claude_agent = home / ".claude" / "agents" / "mcp-managed-demo-openstack-demo_site_1.md"
            codex_agent = home / ".codex" / "agents" / "mcp-managed-demo-openstack-demo_site_1.toml"
            self.assertTrue(claude_agent.exists())
            self.assertTrue(codex_agent.exists())
            self.assertIn("Topology alias demo-alias-1 maps to site DEMO_SITE_1", claude_agent.read_text())
            self.assertIn("Topology alias demo-alias-1 maps to site DEMO_SITE_1", codex_agent.read_text())

    def test_public_scan_has_no_internal_markers(self) -> None:
        patterns = [
            "v" + "npay",
            "jump\\." + "vn" + "paycloud",
            "HCM" + "01",
            "HAN" + "02",
            "HCM" + "03",
            "HAN" + "04",
            "\\bslug\\b",
            "<slug>",
            "--slug",
            "Ví dụ nhanh",
            "Also update ~/.zshrc idempotently",
            "<owner>",
            "<your-fork-or-clone-url>",
            BAD_ROOT,
        ]
        result = subprocess.run(
            [
                "rg",
                "-n",
                "--glob",
                "!tests/test_public_hygiene.py",
                *sum([["-e", pattern] for pattern in patterns], []),
                str(ROOT),
            ],
            text=True,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
