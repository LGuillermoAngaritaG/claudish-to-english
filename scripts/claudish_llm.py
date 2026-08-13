#!/usr/bin/env python3
"""Private one-shot LiteLLM adapter used only by the plugin hooks."""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any


MAX_INPUT_BYTES = 8 * 1024 * 1024


class InputError(Exception):
    """Invalid local input or configuration."""


def read_private_json(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise InputError from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise InputError
    if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise InputError

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
            or (os.name != "nt" and stat.S_IMODE(opened.st_mode) & 0o077)
        ):
            os.close(descriptor)
            raise InputError
        with os.fdopen(descriptor, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError from exc
    if not isinstance(value, dict):
        raise InputError
    return value


def validated_config(path: Path) -> dict[str, str]:
    raw = read_private_json(path)
    config: dict[str, str] = {}
    for name in ("provider", "model"):
        value = raw.get(name)
        if not isinstance(value, str) or not value.strip():
            raise InputError
        config[name] = value.strip()
    for name in ("api_base", "api_key"):
        value = raw.get(name)
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise InputError
            config[name] = value.strip()
    return config


def validated_request() -> dict[str, str]:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise InputError
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise InputError from exc
    if not isinstance(value, dict):
        raise InputError
    result: dict[str, str] = {}
    for name in ("system", "content"):
        text = value.get(name)
        if not isinstance(text, str) or not text.strip():
            raise InputError
        result[name] = text
    return result


def response_text(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise InputError from exc
    if not isinstance(content, str) or not content.strip():
        raise InputError
    return content


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--timeout", required=True, type=float)
    try:
        args = parser.parse_args()
        if args.timeout <= 0:
            raise InputError
        config = validated_config(args.config)
        request = validated_request()
    except (InputError, SystemExit, ValueError):
        print("claudish-llm: invalid request or private configuration", file=sys.stderr)
        return 2

    try:
        with open(os.devnull, "w", encoding="utf-8") as sink:
            with redirect_stdout(sink), redirect_stderr(sink):
                import litellm
    except Exception:
        print("claudish-llm: LiteLLM runtime unavailable", file=sys.stderr)
        return 3

    options: dict[str, Any] = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": request["system"]},
            {"role": "user", "content": request["content"]},
        ],
        "temperature": 0.3,
        "stream": False,
        "timeout": args.timeout,
        "num_retries": 0,
        "drop_params": True,
    }
    for name in ("api_base", "api_key"):
        if name in config:
            options[name] = config[name]

    try:
        with open(os.devnull, "w", encoding="utf-8") as sink:
            with redirect_stdout(sink), redirect_stderr(sink):
                response = litellm.completion(**options)
        text = response_text(response)
    except Exception as exc:
        if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
            print("claudish-llm: model request timed out", file=sys.stderr)
            return 124
        print("claudish-llm: model request failed", file=sys.stderr)
        return 1

    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
