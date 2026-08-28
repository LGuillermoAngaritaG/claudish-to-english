#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/claudish-hooks.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
assert_contains() { case "$1" in *"$2"*) ;; *) fail "expected output to contain: $2" ;; esac; }

# Stand-in for the real CLI: records what it was handed, then answers per mode.
mkdir -p "$WORK/bin"
cat > "$WORK/bin/claude" <<'FAKE'
#!/usr/bin/env bash
if [ -n "${FAKE_CAPTURE:-}" ]; then
  cat > "$FAKE_CAPTURE.stdin"
  while [ "$#" -gt 0 ]; do
    [ "$1" = "--system-prompt" ] && printf '%s' "$2" > "$FAKE_CAPTURE.system"
    [ "$1" = "--model" ] && printf '%s' "$2" > "$FAKE_CAPTURE.model"
    shift
  done
else
  cat >/dev/null
fi
case "${FAKE_MODE:-success}" in
  hang) sleep 30 ;;
  error) exit 1 ;;
  empty) ;;
  markdown) printf '# Plain title\n\nPlain body.\n' ;;
  *) printf 'Plain response.' ;;
esac
FAKE
chmod +x "$WORK/bin/claude"
WITH_CLI="$WORK/bin:$PATH"
# Has bash and jq, but no claude: the real CLI lives under the user's home.
NO_CLI="/usr/bin:/bin"

# Display hook: the CLI receives the message on stdin and the prompt as a flag.
CAPTURE="$WORK/display"
display_payload='{"message_id":"m1","session_id":"s1","index":0,"final":true,"delta":"Dense source text."}'
display_out="$(printf '%s' "$display_payload" | env -u CLAUDISH_INNER \
  PATH="$WITH_CLI" TMPDIR="$WORK/display-tmp" CLAUDISH_MIN_CHARS=1 CLAUDISH_NOTICE=0 \
  FAKE_CAPTURE="$CAPTURE" "$ROOT/rewrite.sh" "$ROOT")"
display_content="$(printf '%s' "$display_out" | jq -r '.hookSpecificOutput.displayContent')"
assert_contains "$display_content" 'Dense source text.'
assert_contains "$display_content" 'Plain response.'
[ "$(cat "$CAPTURE.stdin")" = 'Dense source text.' ] || fail 'display request lost source text'
assert_contains "$(cat "$CAPTURE.system")" 'plain language'

# The base prompt must not name a language: the rewrite follows the message's own
# language unless one is configured.
case "$(cat "$CAPTURE.system")" in
  *'plain English'*) fail 'base prompt hard-codes English' ;;
esac

# CLAUDISH_STYLE swaps the base prompt for the matching prompts/style-*.md.
STYLE_CAPTURE="$WORK/style"
printf '%s' "$display_payload" | env -u CLAUDISH_INNER PATH="$WITH_CLI" \
  TMPDIR="$WORK/style-tmp" CLAUDISH_MIN_CHARS=1 CLAUDISH_NOTICE=0 CLAUDISH_STYLE=caveman \
  CLAUDISH_STYLE_FILE="$WORK/no-style-file" HOME="$WORK" \
  FAKE_CAPTURE="$STYLE_CAPTURE" "$ROOT/rewrite.sh" "$ROOT" >/dev/null
assert_contains "$(cat "$STYLE_CAPTURE.system")" 'caveman'

# An unknown style falls back to the default prompt rather than an empty one.
BADSTYLE_CAPTURE="$WORK/badstyle"
printf '%s' "$display_payload" | env -u CLAUDISH_INNER PATH="$WITH_CLI" \
  TMPDIR="$WORK/badstyle-tmp" CLAUDISH_MIN_CHARS=1 CLAUDISH_NOTICE=0 CLAUDISH_STYLE=nonsense \
  CLAUDISH_STYLE_FILE="$WORK/no-style-file" HOME="$WORK" \
  FAKE_CAPTURE="$BADSTYLE_CAPTURE" "$ROOT/rewrite.sh" "$ROOT" >/dev/null
assert_contains "$(cat "$BADSTYLE_CAPTURE.system")" 'plain language'

# CLAUDISH_LANG adds a language instruction; unset leaves the message's own.
LANG_CAPTURE="$WORK/lang"
printf '%s' "$display_payload" | env -u CLAUDISH_INNER PATH="$WITH_CLI" \
  TMPDIR="$WORK/lang-tmp" CLAUDISH_MIN_CHARS=1 CLAUDISH_NOTICE=0 CLAUDISH_LANG='Spanish' \
  CLAUDISH_LANG_FILE="$WORK/no-lang-file" HOME="$WORK" \
  FAKE_CAPTURE="$LANG_CAPTURE" "$ROOT/rewrite.sh" "$ROOT" >/dev/null
assert_contains "$(cat "$LANG_CAPTURE.system")" 'Write the rewrite in Spanish'
case "$(cat "$CAPTURE.system")" in
  *'instead, whatever language'*) fail 'language override added with no language configured' ;;
esac
[ "$(cat "$CAPTURE.model")" = 'haiku' ] || fail 'display request did not default to haiku'

# CLAUDISH_MODEL selects the model.
MODEL_CAPTURE="$WORK/model"
printf '%s' "$display_payload" | env -u CLAUDISH_INNER PATH="$WITH_CLI" \
  TMPDIR="$WORK/model-tmp" CLAUDISH_MIN_CHARS=1 CLAUDISH_NOTICE=0 CLAUDISH_MODEL=sonnet \
  FAKE_CAPTURE="$MODEL_CAPTURE" "$ROOT/rewrite.sh" "$ROOT" >/dev/null
[ "$(cat "$MODEL_CAPTURE.model")" = 'sonnet' ] || fail 'CLAUDISH_MODEL ignored'

# /claudish writes a model flag file; it must outrank the frozen env var.
printf 'opus\n' > "$WORK/model-file"
MFILE_CAPTURE="$WORK/modelfile"
printf '%s' "$display_payload" | env -u CLAUDISH_INNER PATH="$WITH_CLI" \
  TMPDIR="$WORK/modelfile-tmp" CLAUDISH_MIN_CHARS=1 CLAUDISH_NOTICE=0 CLAUDISH_MODEL=sonnet \
  CLAUDISH_MODEL_FILE="$WORK/model-file" \
  FAKE_CAPTURE="$MFILE_CAPTURE" "$ROOT/rewrite.sh" "$ROOT" >/dev/null
[ "$(cat "$MFILE_CAPTURE.model")" = 'opus' ] || fail 'model flag file did not outrank CLAUDISH_MODEL'

# A nested session must fail open rather than call itself.
inner_out="$(printf '%s' "$display_payload" | env PATH="$WITH_CLI" \
  TMPDIR="$WORK/inner-tmp" CLAUDISH_MIN_CHARS=1 CLAUDISH_NOTICE=0 CLAUDISH_INNER=1 \
  "$ROOT/rewrite.sh" "$ROOT")"
[ -z "$inner_out" ] || fail 'nested invocation rewrote instead of passing through'

# Replace mode must re-show the original while explaining a missing CLI.
nocli_out="$(printf '%s' "$display_payload" | env -u CLAUDISH_INNER \
  PATH="$NO_CLI" TMPDIR="$WORK/nocli-tmp" CLAUDISH_MIN_CHARS=1 \
  CLAUDISH_MODE=replace "$ROOT/rewrite.sh" "$ROOT")"
nocli_content="$(printf '%s' "$nocli_out" | jq -r '.hookSpecificOutput.displayContent')"
assert_contains "$nocli_content" 'Dense source text.'
assert_contains "$nocli_content" 'not on PATH'

# Markdown success writes only the sibling, then a CLI failure leaves source untouched.
mkdir -p "$WORK/docs"
printf '# Dense title\n\nDense body.\n' > "$WORK/docs/input.md"
md_payload="$(jq -n --arg cwd "$WORK" --arg path "$WORK/docs/input.md" \
  '{session_id:"md1",cwd:$cwd,tool_input:{file_path:$path}}')"
printf '%s' "$md_payload" | env -u CLAUDISH_INNER PATH="$WITH_CLI" \
  TMPDIR="$WORK/md-tmp" CLAUDISH_MD_DIR="$WORK/docs" \
  CLAUDISH_MIN_CHARS=1 FAKE_MODE=markdown "$ROOT/rewrite-md.sh" "$ROOT" >/dev/null
[ "$(cat "$WORK/docs/input.md")" = $'# Dense title\n\nDense body.' ] || fail 'Markdown source changed in sibling mode'
assert_contains "$(cat "$WORK/docs/input.plain.md")" 'Plain body.'

rm "$WORK/docs/input.plain.md"
md_error="$(printf '%s' "$md_payload" | env -u CLAUDISH_INNER PATH="$WITH_CLI" \
  TMPDIR="$WORK/md-error-tmp" CLAUDISH_MD_DIR="$WORK/docs" CLAUDISH_MIN_CHARS=1 \
  FAKE_MODE=error "$ROOT/rewrite-md.sh" "$ROOT")"
[ ! -e "$WORK/docs/input.plain.md" ] || fail 'CLI failure wrote a Markdown sibling'
assert_contains "$(printf '%s' "$md_error" | jq -r '.systemMessage')" 'File left unchanged'
[ "$(cat "$WORK/docs/input.md")" = $'# Dense title\n\nDense body.' ] || fail 'CLI failure changed Markdown source'

# hooks.json: with an args array Claude Code execs the command as argv[0] with no
# shell, so a quoted command string makes the quotes part of the path and the hook
# silently never runs. Upstream can quote because it has no args array; this fork
# cannot. Guard both hooks.
for _h in MessageDisplay PostToolUse; do
  _cmd="$(jq -r --arg h "$_h" '.hooks[$h][0].hooks[0].command' "$ROOT/hooks/hooks.json")"
  _args="$(jq -r --arg h "$_h" '.hooks[$h][0].hooks[0].args // [] | length' "$ROOT/hooks/hooks.json")"
  case "$_args:$_cmd" in
    0:*) ;;
    *:*'"'*) fail "$_h hook command is quoted while args is set; the hook will never run" ;;
  esac
done

printf 'hook integration tests passed\n'
