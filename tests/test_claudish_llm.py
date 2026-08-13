#!/usr/bin/env python3
"""Deterministic contract tests for the bundled LiteLLM helper."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "claudish_llm.py"


class ClaudishLlmTests(unittest.TestCase):
    def run_helper(
        self,
        request: object,
        *,
        config: dict[str, str] | None = None,
        fake_mode: str = "success",
        config_mode: int = 0o600,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object] | None]:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            capture = temp / "capture.json"
            config_path = temp / "config.json"
            config_path.write_text(
                json.dumps(
                    config
                    or {
                        "provider": "openai",
                        "model": "openai/test-model",
                        "api_base": "https://provider.invalid/v1",
                        "api_key": "test-secret-key",
                    }
                )
            )
            config_path.chmod(config_mode)
            (temp / "litellm.py").write_text(
                textwrap.dedent(
                    """
                    import json
                    import os
                    from types import SimpleNamespace

                    print("IMPORT NOISE THAT MUST NOT REACH STDOUT")

                    def completion(**kwargs):
                        with open(os.environ["FAKE_LITELLM_CAPTURE"], "w") as handle:
                            json.dump(kwargs, handle)
                        if os.environ.get("FAKE_LITELLM_MODE") == "timeout":
                            raise TimeoutError("SECRET provider diagnostic")
                        if os.environ.get("FAKE_LITELLM_MODE") == "error":
                            raise RuntimeError("SECRET provider diagnostic")
                        content = "" if os.environ.get("FAKE_LITELLM_MODE") == "empty" else "Plain response"
                        return SimpleNamespace(
                            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
                        )
                    """
                )
            )
            env = os.environ.copy()
            env["PYTHONPATH"] = str(temp)
            env["FAKE_LITELLM_CAPTURE"] = str(capture)
            env["FAKE_LITELLM_MODE"] = fake_mode

            result = subprocess.run(
                [
                    sys.executable,
                    str(HELPER),
                    "--config",
                    str(config_path),
                    "--timeout",
                    "17",
                ],
                input=json.dumps(request),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            captured = json.loads(capture.read_text()) if capture.exists() else None
            return result, captured

    def test_emits_only_response_text_and_uses_private_config(self) -> None:
        result, captured = self.run_helper(
            {"system": "Rewrite plainly.", "content": "Dense source text."}
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "Plain response")
        self.assertEqual(result.stderr, "")
        self.assertEqual(captured["model"], "openai/test-model")
        self.assertEqual(captured["api_base"], "https://provider.invalid/v1")
        self.assertEqual(captured["api_key"], "test-secret-key")
        self.assertEqual(
            captured["messages"],
            [
                {"role": "system", "content": "Rewrite plainly."},
                {"role": "user", "content": "Dense source text."},
            ],
        )
        self.assertEqual(captured["timeout"], 17.0)
        self.assertEqual(captured["num_retries"], 0)
        self.assertFalse(captured["stream"])

    def test_local_ollama_does_not_require_a_key(self) -> None:
        result, captured = self.run_helper(
            {"system": "Rewrite plainly.", "content": "Dense source text."},
            config={
                "provider": "ollama",
                "model": "ollama/llama3.2:3b",
                "api_base": "http://localhost:11434",
            },
        )

        self.assertEqual(result.returncode, 0)
        self.assertNotIn("api_key", captured)

    @unittest.skipIf(os.name == "nt", "POSIX permission check")
    def test_rejects_config_readable_by_group_or_other_users(self) -> None:
        result, captured = self.run_helper(
            {"system": "Rewrite plainly.", "content": "Dense source text."},
            config_mode=0o644,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIsNone(captured)
        self.assertNotIn("test-secret-key", result.stderr)

    def test_provider_error_is_generic_and_has_empty_stdout(self) -> None:
        result, _ = self.run_helper(
            {"system": "Rewrite plainly.", "content": "Dense source text."},
            fake_mode="error",
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("SECRET", result.stderr)
        self.assertNotIn("test-secret-key", result.stderr)

    def test_timeout_has_distinct_exit_code_without_diagnostic_leak(self) -> None:
        result, _ = self.run_helper(
            {"system": "Rewrite plainly.", "content": "Dense source text."},
            fake_mode="timeout",
        )

        self.assertEqual(result.returncode, 124)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("SECRET", result.stderr)

    def test_rejects_invalid_request_before_calling_provider(self) -> None:
        result, captured = self.run_helper({"system": "", "content": 42})

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIsNone(captured)

    def test_rejects_empty_provider_response(self) -> None:
        result, _ = self.run_helper(
            {"system": "Rewrite plainly.", "content": "Dense source text."},
            fake_mode="empty",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
