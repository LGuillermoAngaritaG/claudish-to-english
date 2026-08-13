#!/usr/bin/env bash
set -eu

plugin_root="${1:?plugin root required}"
plugin_data="${2:?plugin data directory required}"

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' 'claudish-to-english setup requires uv: https://docs.astral.sh/uv/getting-started/installation/' >&2
  exit 1
fi

mkdir -p "$plugin_data"
chmod 700 "$plugin_data" 2>/dev/null || true
export UV_PYTHON_INSTALL_DIR="$plugin_data/.uv-python"
export UV_CACHE_DIR="$plugin_data/.uv-cache"

exec uv run --no-project --no-config --managed-python --python 3.14 \
  "$plugin_root/scripts/setup.py" \
  --plugin-root "$plugin_root" --plugin-data "$plugin_data"
