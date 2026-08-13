#!/usr/bin/env python3
"""Install the pinned LiteLLM runtime into Claude's persistent plugin data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


LITELLM_VERSION = "1.93.2"
PYTHON_VERSION = "3.14"


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def runtime_name(lock_digest: str) -> str:
    version = f"py{sys.version_info.major}{sys.version_info.minor}"
    return f"venv-{lock_digest[:16]}-{version}"


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def validate_runtime(venv: Path) -> bool:
    python = venv_python(venv)
    if not python.is_file():
        return False
    check = subprocess.run(
        [
            str(python),
            "-c",
            (
                "import importlib.metadata,sys;"
                f"sys.exit(0 if importlib.metadata.version('litellm') == '{LITELLM_VERSION}' else 1)"
            ),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return check.returncode == 0


def uv_install_commands(
    *, uv: Path, venv: Path, lock: Path
) -> tuple[list[str], list[str]]:
    cache = venv.parent / ".uv-cache"
    create = [
        str(uv),
        "venv",
        "--python",
        PYTHON_VERSION,
        "--managed-python",
        "--no-project",
        "--no-config",
        "--cache-dir",
        str(cache),
        str(venv),
    ]
    install = [
        str(uv),
        "pip",
        "install",
        "--python",
        str(venv_python(venv)),
        "--require-hashes",
        "--only-binary=:all:",
        "--no-deps",
        "--no-config",
        "--cache-dir",
        str(cache),
        "-r",
        str(lock),
    ]
    return create, install


def write_runtime_atomic(data_dir: Path, runtime: dict[str, str]) -> Path:
    target = data_dir / "runtime.json"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".runtime.", suffix=".tmp", dir=data_dir
    )
    temporary = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(runtime, handle, indent=2, sort_keys=True)
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


def install(plugin_root: Path, plugin_data: Path) -> Path:
    lock = plugin_root / "requirements.lock"
    if not lock.is_file():
        raise RuntimeError("bundled dependency lock is missing")
    lock_hash = digest_file(lock)
    plugin_data.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        plugin_data.chmod(0o700)
    uv_path = shutil.which("uv")
    if uv_path is None:
        raise RuntimeError("uv is not available on PATH")

    name = runtime_name(lock_hash)
    target = plugin_data / name
    if not validate_runtime(target):
        if target.exists():
            shutil.rmtree(target)
        temporary = Path(tempfile.mkdtemp(prefix=".venv-install-", dir=plugin_data))
        try:
            create, install_locked = uv_install_commands(
                uv=Path(uv_path), venv=temporary, lock=lock
            )
            subprocess.run(create, check=True)
            subprocess.run(install_locked, check=True)
            if not validate_runtime(temporary):
                raise RuntimeError("installed runtime validation failed")
            os.replace(temporary, target)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    write_runtime_atomic(
        plugin_data,
        {
            "venv": name,
            "lock_sha256": lock_hash,
            "litellm_version": LITELLM_VERSION,
        },
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-root", required=True, type=Path)
    parser.add_argument("--plugin-data", required=True, type=Path)
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 14):
        print("claudish-to-english setup must be launched by uv with Python 3.14", file=sys.stderr)
        return 1
    try:
        target = install(args.plugin_root.resolve(), args.plugin_data.resolve())
    except Exception:
        print("claudish-to-english setup failed; check the Setup hook diagnostics", file=sys.stderr)
        return 1
    print(f"claudish-to-english LiteLLM runtime ready at {target}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
