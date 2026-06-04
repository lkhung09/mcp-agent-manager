#!/usr/bin/env python3
"""Public readiness checks for portability and repo hygiene."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAM = ROOT / "bin" / "mcp-agent-manager"
BAD_ROOT = "/Users/" + "kimhung/Documents/MCP/" + "mcp-agent-manager/"
BAD_ROOT_IS_CURRENT_REPO = ROOT.resolve() == Path(BAD_ROOT).resolve()


def write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def assert_no_private_source_leak(testcase: unittest.TestCase, text: str) -> None:
    if BAD_ROOT_IS_CURRENT_REPO:
        return
    testcase.assertNotIn(BAD_ROOT, text)


class PublicHygieneTests(unittest.TestCase):
    def test_vietnamese_readme_exists_and_matches_public_shape(self) -> None:
        english = (ROOT / "README.md").read_text()
        vietnamese_path = ROOT / "README.vi.md"
        self.assertTrue(vietnamese_path.exists())
        text = vietnamese_path.read_text()

        self.assertIn("[Tiếng Việt](README.vi.md)", english)
        self.assertIn("[English](README.md)", text)

        required = [
            "## Vấn đề",
            "## Giải pháp",
            "## Làm được gì",
            "## Không phải là gì",
            "## Bắt đầu nhanh",
            "### Yêu cầu",
            "### Cài đặt",
            "### Lần chạy đầu tiên",
            "## Gỡ cài đặt",
            "## Tính năng",
            "## Vòng đời MCP process",
        ]
        for item in required:
            self.assertIn(item, text)

        self.assertIn("```mermaid", text)
        self.assertIn("Có dùng  —  scoped agents", text)
        self.assertIn("Claude / Codex", text)
        self.assertIn("Chỉ MCP A", text)
        self.assertIn("MCP_AGENT_MANAGER_CHAT_IDLE_TIMEOUT", text)
        self.assertIn("mặc định 300s", text)
        self.assertIn("curl -fsSL", text)
        self.assertIn("raw.githubusercontent.com/lkhung09/mcp-agent-manager/main/install.sh", text)
        self.assertIn("https://github.com/lkhung09/mcp-agent-manager.git", text)
        self.assertNotIn("<owner>", text)
        self.assertNotIn("<your-fork-or-clone-url>", text)
        self.assertIn("brew install git python jq zip", text)
        self.assertIn("sudo apt update && sudo apt install -y bash git python3 jq zip", text)
        self.assertIn("source ~/.bashrc   # Linux bash", text)
        self.assertIn("mcp-agent-manager doctor", text)
        self.assertIn("mcp-agent-manager tools search", text)
        self.assertIn("mcp-agent-manager sync", text)
        self.assertIn("Lệnh `add`, `edit`", text)
        self.assertIn("Hermes / OpenClaw rendering", text)

    def test_readme_is_non_dev_friendly(self) -> None:
        text = (ROOT / "README.md").read_text()
        required_sections = [
            "## The problem",
            "## The fix",
            "## What it does",
            "## What it is not",
            "## Quick start",
            "### Requirements",
            "### Install",
            "### First run",
            "## Undo",
            "## Supported features",
            "## Runtime modes",
        ]
        for section in required_sections:
            self.assertIn(section, text)

        self.assertIn("```mermaid", text)
        self.assertIn("With  —  scoped agents", text)
        self.assertIn("Claude / Codex", text)
        self.assertIn("MCP A only", text)
        self.assertIn("MCP process lifetime", text)
        self.assertIn("redacted `tools/list` metadata", text)
        self.assertIn("hundreds of schema lines", text)
        self.assertIn("Claude Code agent rendering", text)
        self.assertIn("Hermes / OpenClaw rendering", text)
        self.assertIn("curl -fsSL", text)
        self.assertIn("raw.githubusercontent.com/lkhung09/mcp-agent-manager/main/install.sh", text)
        self.assertIn("https://github.com/lkhung09/mcp-agent-manager.git", text)
        self.assertNotIn("<owner>", text)
        self.assertNotIn("<your-fork-or-clone-url>", text)
        self.assertIn("Manual:", text)
        self.assertIn("Prefer to read first", text)
        self.assertIn("brew install git python jq zip", text)
        self.assertIn("sudo apt update && sudo apt install -y bash git python3 jq zip", text)
        self.assertIn("source ~/.bashrc   # Linux bash", text)
        self.assertIn("Not tied to Teleport", text)
        self.assertIn("MCP_AGENT_MANAGER_CHAT_IDLE_TIMEOUT", text)
        self.assertIn("default 300s", text)
        self.assertIn("Configurable session idle timeout", text)
        self.assertIn("mcp-agent-manager doctor", text)
        self.assertIn("mcp-agent-manager tools search", text)
        self.assertIn("mcp-agent-manager sync", text)
        self.assertIn("`add`, `edit` commands", text)
        self.assertLess(text.index("### Install"), text.index("## Demo"))
        self.assertLess(text.index("## Undo"), text.index("## Contributing"))
        self.assertIn("Every command previews before it changes anything.", text)
        self.assertIn("Add `--apply` when the preview looks right.", text)

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
            ["session"],
            ["chat-session"],
            ["tools"],
            ["config"],
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
        self.assertIn("Use the name column as <mcp-name>", list_help)

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
            [str(MAM), "session", "--help"],
            text=True,
            capture_output=True,
            timeout=20,
        ).stdout
        self.assertIn("Usage: mcp-agent-manager session <mcp-name>", chat_help)
        self.assertIn("Helper command for agent runtimes", chat_help)
        self.assertIn("Compatibility alias", chat_help)

        legacy_chat_help = subprocess.run(
            [str(MAM), "chat-session", "--help"],
            text=True,
            capture_output=True,
            timeout=20,
        ).stdout
        self.assertIn("Usage: mcp-agent-manager session <mcp-name>", legacy_chat_help)

        config_help = subprocess.run(
            [str(MAM), "config", "--help"],
            text=True,
            capture_output=True,
            timeout=20,
        ).stdout
        self.assertIn("Usage: mcp-agent-manager config <get|set|reset> session-idle-timeout [seconds]", config_help)
        self.assertIn("mcp-agent-manager config set session-idle-timeout 900", config_help)
        self.assertIn("Compatibility alias", config_help)

    def test_config_chat_idle_timeout_uses_temp_home_and_env_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            env = {
                **os.environ,
                "HOME": str(home),
                "PYTHONDONTWRITEBYTECODE": "1",
            }

            get_default = subprocess.run(
                [str(MAM), "config", "get", "session-idle-timeout"],
                text=True,
                capture_output=True,
                env=env,
                timeout=20,
            )
            self.assertEqual(get_default.returncode, 0, get_default.stderr)
            self.assertEqual(get_default.stdout.strip(), "300")

            set_timeout = subprocess.run(
                [str(MAM), "config", "set", "session-idle-timeout", "900"],
                text=True,
                capture_output=True,
                env=env,
                timeout=20,
            )
            self.assertEqual(set_timeout.returncode, 0, set_timeout.stderr)
            settings = home / ".config" / "mcp-agent-manager" / "settings.env"
            self.assertTrue(settings.exists())
            self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o600)
            self.assertIn('export MCP_AGENT_MANAGER_CHAT_IDLE_TIMEOUT="900"', settings.read_text())

            get_set = subprocess.run(
                [str(MAM), "config", "get", "session-idle-timeout"],
                text=True,
                capture_output=True,
                env=env,
                timeout=20,
            )
            self.assertEqual(get_set.returncode, 0, get_set.stderr)
            self.assertEqual(get_set.stdout.strip(), "900")

            get_legacy_alias = subprocess.run(
                [str(MAM), "config", "get", "chat-idle-timeout"],
                text=True,
                capture_output=True,
                env=env,
                timeout=20,
            )
            self.assertEqual(get_legacy_alias.returncode, 0, get_legacy_alias.stderr)
            self.assertEqual(get_legacy_alias.stdout.strip(), "900")

            env_override = {
                **env,
                "MCP_AGENT_MANAGER_CHAT_IDLE_TIMEOUT": "1200",
            }
            get_env = subprocess.run(
                [str(MAM), "config", "get", "session-idle-timeout"],
                text=True,
                capture_output=True,
                env=env_override,
                timeout=20,
            )
            self.assertEqual(get_env.returncode, 0, get_env.stderr)
            self.assertEqual(get_env.stdout.strip(), "1200")

            invalid = subprocess.run(
                [str(MAM), "config", "set", "session-idle-timeout", "5"],
                text=True,
                capture_output=True,
                env=env,
                timeout=20,
            )
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("between 30 and 86400", invalid.stderr)

            reset = subprocess.run(
                [str(MAM), "config", "reset", "session-idle-timeout"],
                text=True,
                capture_output=True,
                env=env,
                timeout=20,
            )
            self.assertEqual(reset.returncode, 0, reset.stderr)

            get_reset = subprocess.run(
                [str(MAM), "config", "get", "session-idle-timeout"],
                text=True,
                capture_output=True,
                env=env,
                timeout=20,
            )
            self.assertEqual(get_reset.returncode, 0, get_reset.stderr)
            self.assertEqual(get_reset.stdout.strip(), "300")

    def test_bootstrap_apply_does_not_crash_on_fresh_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            env = {**os.environ, "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
            result = subprocess.run(
                [str(MAM), "bootstrap", "--apply"],
                text=True,
                capture_output=True,
                env=env,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            registry = home / ".config" / "mcp-agent-manager" / "registry.json"
            self.assertTrue(registry.exists())
            self.assertIn("file not found", result.stderr + result.stdout)

    def test_doctor_accepts_jq_from_path_or_override_not_usr_bin_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            bin_dir = Path(tmp) / "bin"
            home.mkdir()
            bin_dir.mkdir()
            fake_jq = bin_dir / "jq"
            write_executable(fake_jq, "#!/usr/bin/env sh\nexit 0\n")
            env = {
                **os.environ,
                "HOME": str(home),
                "MCP_AGENT_MANAGER_JQ": str(fake_jq),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            result = subprocess.run(
                [str(MAM), "doctor"],
                text=True,
                capture_output=True,
                env=env,
                timeout=20,
            )
            self.assertIn(f"jq {fake_jq}", result.stdout)
            self.assertNotIn("jq not found at /usr/bin/jq", result.stderr + result.stdout)

    def test_run_parses_secrets_env_without_executing_shell_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".config" / "mcp-agent-manager"
            root.mkdir(parents=True)
            marker = home / "should-not-exist"
            registry = {
                "personal_mcp_servers": {
                    "fixture": {
                        "enabled": True,
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": ["-c", "import os; print(os.environ.get('NEED', ''))"],
                        "env": {"NEED": "${SAFE_VALUE}"},
                        "target": "all",
                    }
                }
            }
            (root / "registry.json").write_text(json.dumps(registry))
            secrets = root / "secrets.env"
            secrets.write_text(f'export SAFE_VALUE="$(touch {marker})"\n')
            secrets.chmod(0o600)
            env = {**os.environ, "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
            result = subprocess.run(
                [str(MAM), "run", "fixture"],
                text=True,
                capture_output=True,
                env=env,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists())
            self.assertEqual(result.stdout.strip(), f"$(touch {marker})")

    def test_apply_removes_quoted_mcp_name_with_dot_from_codex_toml(self) -> None:
        server = (
            "import json, sys\n"
            "for line in sys.stdin:\n"
            "    req=json.loads(line); method=req.get('method')\n"
            "    if method == 'notifications/initialized': continue\n"
            "    result={'protocolVersion':'2024-11-05','capabilities':{},'serverInfo':{'name':'fixture','version':'1'}} if method == 'initialize' else {'tools':[]}\n"
            "    print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}), flush=True)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".config" / "mcp-agent-manager"
            codex_dir = home / ".codex"
            root.mkdir(parents=True)
            codex_dir.mkdir()
            (root / "registry.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "unmanaged_mcp_servers": [],
                        "personal_mcp_servers": {
                            "foo.bar": {
                                "enabled": True,
                                "description": "dot fixture",
                                "transport": "stdio",
                                "command": sys.executable,
                                "args": ["-u", "-c", server],
                                "env": {},
                                "target": "codex",
                            }
                        },
                    }
                )
            )
            (root / "managed-state.json").write_text('{"version":1,"generated_files":[]}\n')
            (root / "deferred.json").write_text('{"version":1,"deferred":{}}\n')
            config = codex_dir / "config.toml"
            config.write_text(
                '[mcp_servers."foo.bar"]\n'
                f'command = "{sys.executable}"\n'
                'args = []\n'
                '[mcp_servers."foo.bar".env]\n'
                'TOKEN = "x"\n'
                '[mcp_servers.keep]\n'
                'command = "keep"\n'
            )
            env = {**os.environ, "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    f"source {ROOT / 'lib' / 'utils.sh'}; "
                    f"source {ROOT / 'lib' / 'registry.sh'}; "
                    f"source {ROOT / 'lib' / 'renderer_claude.sh'}; "
                    f"source {ROOT / 'lib' / 'renderer_codex.sh'}; "
                    f"source {ROOT / 'lib' / 'apply.sh'}; "
                    "_apply_remove_globals",
                ],
                text=True,
                capture_output=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            text = config.read_text()
            self.assertNotIn('foo.bar', text)
            self.assertIn("[mcp_servers.keep]", text)

    def test_install_shell_rc_read_error_does_not_overwrite_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            rc_dir = Path(tmp) / "rc-dir"
            home.mkdir()
            rc_dir.mkdir()
            env = {
                **os.environ,
                "HOME": str(home),
                "SHELL": "/bin/bash",
                "MAM_SHELL_RC": str(rc_dir),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            result = subprocess.run(
                [str(MAM), "install", "--apply"],
                text=True,
                capture_output=True,
                env=env,
                timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(rc_dir.is_dir())
            self.assertIn("failed reading shell rc", result.stderr)

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
                assert_no_private_source_leak(self, result.stdout)
                assert_no_private_source_leak(self, result.stderr)

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
            assert_no_private_source_leak(self, install.stdout)

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
            assert_no_private_source_leak(self, doctor.stdout)
            assert_no_private_source_leak(self, doctor.stderr)

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
            assert_no_private_source_leak(self, apply.stdout)

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
        ]
        if not BAD_ROOT_IS_CURRENT_REPO:
            patterns.append(BAD_ROOT)
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
