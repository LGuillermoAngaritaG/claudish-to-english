#!/usr/bin/env python3
"""Tests for private, interactive model configuration."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "configure.py"


def load_module():
    spec = importlib.util.spec_from_file_location("claudish_configure", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ConfigureTests(unittest.TestCase):
    def test_collects_model_alias(self) -> None:
        module = load_module()
        output: list[str] = []

        config = module.collect_config(
            input_fn=lambda _prompt: "sonnet",
            output_fn=output.append,
        )

        self.assertEqual(config, {"model": "sonnet"})

    def test_blank_answer_falls_back_to_the_default_model(self) -> None:
        module = load_module()

        config = module.collect_config(
            input_fn=lambda _prompt: "  ",
            output_fn=lambda _line: None,
        )

        self.assertEqual(config, {"model": module.DEFAULT_MODEL})

    def test_atomic_write_uses_private_file_and_directory_permissions(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "plugin-data"
            target = module.write_config_atomic(
                data_dir,
                {"model": "haiku"},
            )

            self.assertEqual(json.loads(target.read_text())["model"], "haiku")
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(data_dir.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(list(data_dir.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
