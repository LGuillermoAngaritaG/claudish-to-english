#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/claudish-hooks.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
assert_contains() { case "$1" in *"$2"*) ;; *) fail "expected output to contain: $2" ;; esac; }

make_runtime() {
  data="$1"
  mkdir -p "$data/fake-venv/bin"
  chmod 700 "$data"
  printf '{"venv":"fake-venv"}\n' > "$data/runtime.json"
  printf '{"provider":"ollama","model":"ollama/test"}\n' > "$data/config.json"
  chmod 600 "$data/runtime.json" "$data/config.json"
  cp "$WORK/fake-python" "$data/fake-venv/bin/python"
  chmod +x "$data/fake-venv/bin/python"
}

cat > "$WORK/fake-python" <<'SH'
#!/usr/bin/env bash
request="$(cat)"
[ -n "${FAKE_CAPTURE:-}" ] && printf '%s' "$request" > "$FAKE_CAPTURE"
case "${FAKE_MODE:-success}" in
  timeout) exit 124 ;;
  error) exit 1 ;;
  markdown) printf '# Plain title\n\nPlain body.\n' ;;
  *) printf 'Plain response.' ;;
esac
SH
chmod +x "$WORK/fake-python"

# Display hook: the internal helper receives the system prompt and full text.
DISPLAY_DATA="$WORK/display-data"
make_runtime "$DISPLAY_DATA"
DISPLAY_CAPTURE="$WORK/display-request.json"
display_payload='{"message_id":"m1","session_id":"s1","index":0,"final":true,"delta":"Dense source text."}'
display_out="$(printf '%s' "$display_payload" | env \
  TMPDIR="$WORK/display-tmp" CLAUDISH_MIN_CHARS=1 CLAUDISH_NOTICE=0 \
  FAKE_CAPTURE="$DISPLAY_CAPTURE" "$ROOT/rewrite.sh" "$ROOT" "$DISPLAY_DATA")"
display_content="$(printf '%s' "$display_out" | jq -r '.hookSpecificOutput.displayContent')"
assert_contains "$display_content" 'Dense source text.'
assert_contains "$display_content" 'Plain response.'
[ "$(jq -r '.content' "$DISPLAY_CAPTURE")" = 'Dense source text.' ] || fail 'display request lost source text'
jq -e '.system | contains("plain English")' "$DISPLAY_CAPTURE" >/dev/null || fail 'display request lost system prompt'

# Replace mode must re-show the original while explaining missing setup.
setup_out="$(printf '%s' "$display_payload" | env \
  TMPDIR="$WORK/setup-tmp" CLAUDISH_MIN_CHARS=1 CLAUDISH_MODE=replace \
  "$ROOT/rewrite.sh" "$ROOT" "$WORK/no-runtime")"
setup_content="$(printf '%s' "$setup_out" | jq -r '.hookSpecificOutput.displayContent')"
assert_contains "$setup_content" 'Dense source text.'
assert_contains "$setup_content" 'claude --init-only'

# A ready runtime without private configuration points at the explicit command.
CONFIG_DATA="$WORK/config-data"
make_runtime "$CONFIG_DATA"
rm "$CONFIG_DATA/config.json"
config_out="$(printf '%s' "$display_payload" | env \
  TMPDIR="$WORK/config-tmp" CLAUDISH_MIN_CHARS=1 \
  "$ROOT/rewrite.sh" "$ROOT" "$CONFIG_DATA")"
config_content="$(printf '%s' "$config_out" | jq -r '.hookSpecificOutput.displayContent')"
assert_contains "$config_content" '/claudish-to-english:configure'

# Markdown success writes only the sibling, then provider failure leaves source untouched.
MD_DATA="$WORK/md-data"
make_runtime "$MD_DATA"
mkdir -p "$WORK/docs"
printf '# Dense title\n\nDense body.\n' > "$WORK/docs/input.md"
md_payload="$(jq -n --arg cwd "$WORK" --arg path "$WORK/docs/input.md" \
  '{session_id:"md1",cwd:$cwd,tool_input:{file_path:$path}}')"
printf '%s' "$md_payload" | env TMPDIR="$WORK/md-tmp" CLAUDISH_MD_DIR="$WORK/docs" \
  CLAUDISH_MIN_CHARS=1 FAKE_MODE=markdown "$ROOT/rewrite-md.sh" "$ROOT" "$MD_DATA" >/dev/null
[ "$(cat "$WORK/docs/input.md")" = $'# Dense title\n\nDense body.' ] || fail 'Markdown source changed in sibling mode'
assert_contains "$(cat "$WORK/docs/input.plain.md")" 'Plain body.'

rm "$WORK/docs/input.plain.md"
md_error="$(printf '%s' "$md_payload" | env TMPDIR="$WORK/md-error-tmp" \
  CLAUDISH_MD_DIR="$WORK/docs" CLAUDISH_MIN_CHARS=1 FAKE_MODE=error \
  "$ROOT/rewrite-md.sh" "$ROOT" "$MD_DATA")"
[ ! -e "$WORK/docs/input.plain.md" ] || fail 'provider failure wrote a Markdown sibling'
assert_contains "$(printf '%s' "$md_error" | jq -r '.systemMessage')" 'File left unchanged'
[ "$(cat "$WORK/docs/input.md")" = $'# Dense title\n\nDense body.' ] || fail 'provider failure changed Markdown source'

printf 'hook integration tests passed\n'
