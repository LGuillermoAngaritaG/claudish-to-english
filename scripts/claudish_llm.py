#!/usr/bin/env python3
"""One-shot adapter: routes rewrites through the Claude Code CLI (OAuth subscription).

Same contract as the LiteLLM version it replaced (see claudish_llm.py.litellm.bak):
stdin {"system":..., "content":...} -> stdout rewrite; exit 0/1/2/3/124.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

MAX_INPUT_BYTES = 8 * 1024 * 1024
GUARD = "CLAUDISH_INNER"


def main() -> int:
    # The nested `claude -p` loads this plugin too; without the guard its
    # MessageDisplay hook would call us again, forever.
    if os.environ.get(GUARD):
        return 3

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--timeout", required=True, type=float)
    try:
        args = parser.parse_args()
        if args.timeout <= 0:
            raise ValueError
        config = json.loads(args.config.read_text(encoding="utf-8"))
        request = json.loads(sys.stdin.buffer.read(MAX_INPUT_BYTES))
        system = request["system"]
        content = request["content"]
        if not (system.strip() and content.strip()):
            raise ValueError
    except Exception:
        print("claudish-llm: invalid request or private configuration", file=sys.stderr)
        return 2

    # config model may carry a litellm-style "provider/" prefix; the CLI wants the bare alias.
    model = str(config.get("model") or "haiku").rsplit("/", 1)[-1]
    claude = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
    if not os.path.isfile(claude):
        print("claudish-llm: claude CLI not found", file=sys.stderr)
        return 3

    # ponytail: one throwaway cwd so nested sessions don't clutter the real project's /resume
    scratch = args.config.parent / "cli-scratch"
    scratch.mkdir(exist_ok=True)

    try:
        done = subprocess.run(
            [claude, "-p", "--model", model,
             "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
             "--system-prompt", system],
            input=content,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            cwd=scratch,
            env={**os.environ, GUARD: "1"},
        )
    except subprocess.TimeoutExpired:
        print("claudish-llm: model request timed out", file=sys.stderr)
        return 124
    except Exception:
        print("claudish-llm: model request failed", file=sys.stderr)
        return 1

    if done.returncode != 0 or not done.stdout.strip():
        print("claudish-llm: model request failed", file=sys.stderr)
        return 1

    sys.stdout.write(done.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
