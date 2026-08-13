#!/usr/bin/env python3
"""Tests for private, interactive provider configuration."""

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
    def test_collects_remote_provider_without_printing_key(self) -> None:
        module = load_module()
        answers = iter(["anthropic", "claude-sonnet-4-5", ""])
        output: list[str] = []

        config = module.collect_config(
            input_fn=lambda _prompt: next(answers),
            secret_fn=lambda _prompt: "super-secret",
            output_fn=output.append,
        )

        self.assertEqual(config["provider"], "anthropic")
        self.assertEqual(config["model"], "anthropic/claude-sonnet-4-5")
        self.assertEqual(config["api_key"], "super-secret")
        self.assertNotIn("api_base", config)
        self.assertNotIn("super-secret", "\n".join(output))

    def test_local_ollama_defaults_endpoint_and_omits_key(self) -> None:
        module = load_module()
        answers = iter(["ollama", "llama3.2:3b", ""])

        config = module.collect_config(
            input_fn=lambda _prompt: next(answers),
            secret_fn=lambda _prompt: self.fail("Ollama must not prompt for a key"),
            output_fn=lambda _line: None,
        )

        self.assertEqual(config["model"], "ollama/llama3.2:3b")
        self.assertEqual(config["api_base"], "http://localhost:11434")
        self.assertNotIn("api_key", config)

    def test_atomic_write_uses_private_file_and_directory_permissions(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "plugin-data"
            target = module.write_config_atomic(
                data_dir,
                {
                    "provider": "openai",
                    "model": "openai/gpt-test",
                    "api_key": "super-secret",
                },
            )

            self.assertEqual(json.loads(target.read_text())["api_key"], "super-secret")
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(data_dir.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(list(data_dir.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
