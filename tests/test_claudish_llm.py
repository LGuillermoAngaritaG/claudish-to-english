#!/usr/bin/env python3
"""Deterministic contract tests for the bundled Claude CLI helper."""

from __future__ import annotations

import json
import os
from pathlib import Path
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
        timeout: str = "17",
        guard: str | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object] | None]:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            capture = temp / "capture.json"
            config_path = temp / "config.json"
            config_path.write_text(
                json.dumps(config or {"provider": "claude-cli", "model": "haiku"})
            )
            config_path.chmod(0o600)

            fake = temp / "claude"
            fake.write_text(
                textwrap.dedent(
                    f"""
                    #!{sys.executable}
                    import json, os, sys, time
                    json.dump(
                        {{"argv": sys.argv[1:],
                          "stdin": sys.stdin.read(),
                          "cwd": os.getcwd(),
                          "guard": os.environ.get("CLAUDISH_INNER")}},
                        open({str(capture)!r}, "w"),
                    )
                    mode = {fake_mode!r}
                    if mode == "hang":
                        time.sleep(30)
                    if mode == "fail":
                        sys.exit(1)
                    if mode != "empty":
                        sys.stdout.write("Plain response")
                    """
                ).lstrip()
            )
            fake.chmod(0o755)

            env = dict(os.environ, PATH=f"{temp}{os.pathsep}{os.environ['PATH']}")
            env.pop("CLAUDISH_INNER", None)
            if guard is not None:
                env["CLAUDISH_INNER"] = guard

            result = subprocess.run(
                [sys.executable, str(HELPER), "--config", str(config_path), "--timeout", timeout],
                input=request if isinstance(request, str) else json.dumps(request),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            captured = json.loads(capture.read_text()) if capture.exists() else None
            return result, captured

    def test_emits_only_response_text_and_passes_prompt_through(self) -> None:
        result, captured = self.run_helper(
            {"system": "Rewrite plainly.", "content": "Dense source text."}
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "Plain response")
        self.assertEqual(result.stderr, "")
        self.assertEqual(captured["stdin"], "Dense source text.")
        argv = captured["argv"]
        self.assertIn("-p", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")
        self.assertEqual(argv[argv.index("--system-prompt") + 1], "Rewrite plainly.")

    def test_strips_litellm_style_provider_prefix_from_model(self) -> None:
        _, captured = self.run_helper(
            {"system": "Rewrite plainly.", "content": "Dense source text."},
            config={"provider": "anthropic", "model": "anthropic/claude-haiku-4-5"},
        )

        argv = captured["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "claude-haiku-4-5")

    def test_nested_invocation_is_refused_before_spawning_the_cli(self) -> None:
        result, captured = self.run_helper(
            {"system": "Rewrite plainly.", "content": "Dense source text."}, guard="1"
        )

        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout, "")
        self.assertIsNone(captured)

    def test_child_is_marked_so_its_own_hook_cannot_recurse(self) -> None:
        _, captured = self.run_helper(
            {"system": "Rewrite plainly.", "content": "Dense source text."}
        )

        self.assertEqual(captured["guard"], "1")

    def test_child_runs_outside_the_callers_project_directory(self) -> None:
        _, captured = self.run_helper(
            {"system": "Rewrite plainly.", "content": "Dense source text."}
        )

        self.assertEqual(Path(captured["cwd"]).name, "cli-scratch")

    def test_cli_failure_is_generic_and_has_empty_stdout(self) -> None:
        result, _ = self.run_helper(
            {"system": "Rewrite plainly.", "content": "Dense source text."}, fake_mode="fail"
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.strip(), "claudish-llm: model request failed")

    def test_rejects_empty_cli_response(self) -> None:
        result, _ = self.run_helper(
            {"system": "Rewrite plainly.", "content": "Dense source text."}, fake_mode="empty"
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")

    def test_timeout_has_distinct_exit_code_without_diagnostic_leak(self) -> None:
        result, _ = self.run_helper(
            {"system": "Rewrite plainly.", "content": "Dense source text."},
            fake_mode="hang",
            timeout="1",
        )

        self.assertEqual(result.returncode, 124)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.strip(), "claudish-llm: model request timed out")

    def test_rejects_invalid_request_before_spawning_the_cli(self) -> None:
        result, captured = self.run_helper("not json")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIsNone(captured)

    def test_rejects_blank_request_fields(self) -> None:
        result, captured = self.run_helper({"system": "  ", "content": "Dense source text."})

        self.assertEqual(result.returncode, 2)
        self.assertIsNone(captured)


if __name__ == "__main__":
    unittest.main()
