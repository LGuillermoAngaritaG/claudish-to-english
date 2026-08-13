#!/usr/bin/env python3
"""Deterministic tests for setup metadata and activation."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "setup.py"


def load_module():
    spec = importlib.util.spec_from_file_location("claudish_setup", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SetupTests(unittest.TestCase):
    def test_runtime_name_is_versioned_by_lock_and_python(self) -> None:
        module = load_module()
        name = module.runtime_name("a" * 64)
        self.assertRegex(name, r"^venv-a{16}-py\d+$")

    def test_activation_metadata_is_atomic_and_private(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            target = module.write_runtime_atomic(
                data_dir,
                {
                    "venv": "venv-test-py310",
                    "lock_sha256": "a" * 64,
                    "litellm_version": "1.93.2",
                },
            )

            self.assertEqual(json.loads(target.read_text())["litellm_version"], "1.93.2")
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(list(data_dir.glob("*.tmp")), [])

    def test_builds_uv_commands_without_pip_or_stdlib_venv(self) -> None:
        module = load_module()
        venv = Path("/plugin-data/private-venv")
        lock = Path("/plugin-root/requirements.lock")

        create, install = module.uv_install_commands(
            uv=Path("/usr/local/bin/uv"), venv=venv, lock=lock
        )

        self.assertEqual(
            create,
            [
                "/usr/local/bin/uv",
                "venv",
                "--python",
                "3.14",
                "--managed-python",
                "--no-project",
                "--no-config",
                "--cache-dir",
                "/plugin-data/.uv-cache",
                str(venv),
            ],
        )
        self.assertEqual(
            install,
            [
                "/usr/local/bin/uv",
                "pip",
                "install",
                "--python",
                str(module.venv_python(venv)),
                "--require-hashes",
                "--only-binary=:all:",
                "--no-deps",
                "--no-config",
                "--cache-dir",
                "/plugin-data/.uv-cache",
                "-r",
                str(lock),
            ],
        )
        self.assertNotIn("pip", Path(create[0]).name)
        self.assertNotIn("python", Path(create[0]).name)

    def test_setup_hook_bootstraps_through_uv_managed_python(self) -> None:
        hook_config = json.loads((ROOT / "hooks" / "hooks.json").read_text())
        setup = hook_config["hooks"]["Setup"][0]["hooks"][0]

        self.assertEqual(
            setup["command"], "${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh"
        )
        self.assertEqual(
            setup["args"],
            [
                "${CLAUDE_PLUGIN_ROOT}",
                "${CLAUDE_PLUGIN_DATA}",
            ],
        )
        launcher = (ROOT / "scripts" / "setup.sh").read_text()
        self.assertIn('UV_PYTHON_INSTALL_DIR="$plugin_data/.uv-python"', launcher)
        self.assertIn('UV_CACHE_DIR="$plugin_data/.uv-cache"', launcher)
        self.assertIn(
            "exec uv run --no-project --no-config --managed-python --python 3.14",
            launcher,
        )

    def test_user_only_configurator_also_runs_through_uv(self) -> None:
        skill = (ROOT / "skills" / "configure" / "SKILL.md").read_text()
        launcher = (ROOT / "scripts" / "configure.sh").read_text()

        self.assertIn("disable-model-invocation: true", skill)
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/scripts/configure.sh", skill)
        self.assertNotIn("\npython3 ", skill)
        self.assertIn('UV_PYTHON_INSTALL_DIR="$plugin_data/.uv-python"', launcher)
        self.assertIn(
            "exec uv run --no-project --no-config --managed-python --python 3.14",
            launcher,
        )


if __name__ == "__main__":
    unittest.main()
