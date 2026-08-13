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


if __name__ == "__main__":
    unittest.main()
