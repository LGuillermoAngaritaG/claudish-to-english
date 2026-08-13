#!/usr/bin/env python3
"""Interactively write the plugin's private LiteLLM provider configuration."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Callable


PROVIDER_RE = re.compile(r"^[a-z0-9_-]+$")


def ask_nonempty(prompt: str, input_fn: Callable[[str], str]) -> str:
    while True:
        value = input_fn(prompt).strip()
        if value:
            return value


def collect_config(
    *,
    input_fn: Callable[[str], str] = input,
    secret_fn: Callable[[str], str] = getpass.getpass,
    output_fn: Callable[[str], None] = print,
) -> dict[str, str]:
    output_fn("Configure the private claudish-to-english LiteLLM provider.")
    output_fn("The API key is hidden while typed and is never printed.")
    while True:
        provider = ask_nonempty(
            "LiteLLM provider prefix (for example: ollama, openai, anthropic): ",
            input_fn,
        ).lower()
        if PROVIDER_RE.fullmatch(provider):
            break
    model_name = ask_nonempty("Model name: ", input_fn)
    model = model_name if model_name.startswith(f"{provider}/") else f"{provider}/{model_name}"

    default_base = "http://localhost:11434" if provider == "ollama" else ""
    base_prompt = "API base URL"
    if default_base:
        base_prompt += f" [{default_base}]"
    api_base = input_fn(f"{base_prompt} (blank for provider default): ").strip()
    if not api_base:
        api_base = default_base

    config = {"provider": provider, "model": model}
    if api_base:
        config["api_base"] = api_base
    if provider != "ollama":
        api_key = ""
        while not api_key:
            api_key = secret_fn("API key (input hidden): ").strip()
        config["api_key"] = api_key
    return config


def write_config_atomic(data_dir: Path, config: dict[str, str]) -> Path:
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        data_dir.chmod(0o700)
    target = data_dir / "config.json"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".config.", suffix=".tmp", dir=data_dir
    )
    temporary = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        if os.name != "nt":
            target.chmod(0o600)
            directory_fd = os.open(data_dir, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def terminal_functions():
    if os.name == "nt":
        if not sys.stdin.isatty():
            raise RuntimeError("interactive terminal unavailable")
        return input, getpass.getpass, print, None
    terminal = open("/dev/tty", "r+", encoding="utf-8", buffering=1)

    def terminal_input(prompt: str) -> str:
        terminal.write(prompt)
        value = terminal.readline()
        if not value:
            raise EOFError
        return value.rstrip("\n")

    def terminal_secret(prompt: str) -> str:
        return getpass.getpass(prompt, stream=terminal)

    def terminal_output(message: str) -> None:
        terminal.write(f"{message}\n")

    return terminal_input, terminal_secret, terminal_output, terminal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-data", required=True, type=Path)
    args = parser.parse_args()
    terminal = None
    try:
        input_fn, secret_fn, output_fn, terminal = terminal_functions()
        config = collect_config(
            input_fn=input_fn, secret_fn=secret_fn, output_fn=output_fn
        )
        target = write_config_atomic(args.plugin_data, config)
        output_fn(f"Configuration saved privately to {target}.")
        output_fn("The new configuration applies to subsequent rewrites.")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("Configuration cancelled; no partial file was kept.", file=sys.stderr)
        return 130
    except Exception:
        print("Configuration failed; no API key was printed.", file=sys.stderr)
        return 1
    finally:
        if terminal is not None:
            terminal.close()


if __name__ == "__main__":
    raise SystemExit(main())
