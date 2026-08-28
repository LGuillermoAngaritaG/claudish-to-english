#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# One rewrite call. Usage: claudish-call.sh <system-prompt> <timeout-seconds>
# with the text to rewrite on stdin and the rewrite on stdout.
#
# Exit: 0 rewrote, 1 the CLI failed or said nothing, 3 refused to recurse,
# 124 timed out. Callers treat every non-zero code as fail-open.
# ---------------------------------------------------------------------------
set -uo pipefail

# The contract is the exit code, not stderr; this also swallows bash's
# asynchronous "Terminated" notice when the watchdog kills a slow child.
exec 2>/dev/null

sys="${1:?system prompt required}"

# /claudish model writes a flag file; env is frozen at session launch, so the
# file is what can change mid-session. File > env > haiku, same precedence the
# off-file and style-file use. Sanitised: this lands on a command line.
model_file="${CLAUDISH_MODEL_FILE:-$HOME/.claude/claudish-model}"
model=""
[ -f "$model_file" ] && model="$(head -c 128 "$model_file" 2>/dev/null | tr -cd 'A-Za-z0-9:._/-' | head -c 64)"
[ -n "$model" ] || model="${CLAUDISH_MODEL:-haiku}"
timeout_s="${2:?timeout required}"

# The nested session loads this plugin too. Without the guard its own
# MessageDisplay hook would call back in here, forever.
[ -n "${CLAUDISH_INNER:-}" ] && exit 3
export CLAUDISH_INNER=1

command -v claude >/dev/null 2>&1 || exit 3

# ponytail: one throwaway cwd so the one-shot sessions don't land in the
# caller's project history and clutter /resume.
scratch="${TMPDIR:-/tmp}/claudish-to-english/cli-scratch"
mkdir -p "$scratch" 2>/dev/null || exit 1

# ponytail: the CLI writes a full session transcript per rewrite into
# ~/.claude/projects/<slugified scratch path>/, and nothing else removes them --
# they had reached 2.0 MB over 36 files in development. Sweep our own once they
# are older than 30 min, the same opportunistic pattern the chunk buffers use.
for _d in "$HOME"/.claude/projects/*claudish*cli-scratch; do
  [ -d "$_d" ] && find "$_d" -name '*.jsonl' -mmin +30 -delete 2>/dev/null
done

out="$(mktemp "${TMPDIR:-/tmp}/claudish.out.XXXXXX")" || exit 1
in_file="$out.in"
expired="$out.expired"
trap 'rm -f "$out" "$in_file" "$expired"' EXIT

# Bash gives a background job /dev/null on stdin, so buffer the text first
# and feed the child from the file instead of inheriting the pipe.
cat > "$in_file"
[ -s "$in_file" ] || exit 1

# No portable `timeout` on macOS, so watchdog the child by hand. The flag file
# is what separates "we killed it" from "it failed on its own".
(cd "$scratch" && claude -p --model "$model" \
  --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
  --system-prompt "$sys") < "$in_file" > "$out" 2>/dev/null &
pid=$!

# stdout must be closed here: callers capture us with $(...), and a background
# job holding the pipe open would stall them for the full timeout every call.
( sleep "$timeout_s"
  kill -0 "$pid" 2>/dev/null && : > "$expired" && kill -TERM "$pid" 2>/dev/null ) \
  >/dev/null 2>&1 &
watchdog=$!

wait "$pid"; rc=$?
kill -TERM "$watchdog" 2>/dev/null
wait "$watchdog" 2>/dev/null

[ -e "$expired" ] && exit 124
[ "$rc" -ne 0 ] && exit 1
[ -s "$out" ] || exit 1
grep -q '[^[:space:]]' "$out" || exit 1
cat "$out"
