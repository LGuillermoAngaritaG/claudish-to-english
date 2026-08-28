#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# MessageDisplay LLM rewrite hook  (buffer-to-final, fail-open)
#
# Claude Code fires the MessageDisplay event once PER STREAMED CHUNK of an
# assistant message. Each fire is a separate process and carries:
#   .message_id  groups chunks of one message
#   .index       chunk order (0,1,2,...)
#   .final       true on the last chunk
#   .delta       this chunk's text fragment (NOT cumulative)
#
# To rewrite a whole message we buffer every .delta to disk (keyed by
# message_id) and only call the LLM on the final chunk, once the whole
# message is known.
#
# On the final chunk we also read the ORIGINAL USER QUESTION from
# .transcript_path (the last real user message) and pass it to the model as
# CONTEXT ONLY — it helps the rewrite stay on-topic. The model is told never
# to rewrite, answer, or repeat the question; only the assistant message is
# rewritten. Missing/unreadable transcript -> no context, still rewrites.
#
# FAIL-OPEN CONTRACT: on ANY problem (disabled, no jq, parse error, LLM down,
# timeout, empty rewrite) we emit nothing and exit 0, which leaves Claude's
# ORIGINAL text on screen. A display hook must never be able to swallow the
# assistant's answer.
#
# Rewrites are produced by claudish-call.sh, which shells out to the Claude
# Code CLI and so reuses the login the user already has. No API key, no
# separate runtime, no setup step.
#
# Behavior config (env, with safe defaults):
#   CLAUDISH_ENABLED   1|0            master switch (default 1)
#   CLAUDISH_OFF_FILE  <path>         flag file checked per message; when it
#                                          exists, rewrites pause (default
#                                          ~/.claude/claudish-off) — lets a
#                                          hotkey/script toggle mid-session
#   CLAUDISH_MODE      append|replace display strategy (default append)
#   CLAUDISH_MIN_CHARS <n>            skip messages shorter than this
#                                           (prose, code stripped) (default 200)
#   CLAUDISH_STUB      1|0            deterministic stub instead of ollama
#                                           (for display-mechanics testing)
#   CLAUDISH_TIMEOUT   <seconds>      rewrite timeout, CLI startup included
#                                          (default 45)
#   CLAUDISH_MODEL     <alias>          model for rewrites (default haiku)
#   CLAUDISH_DEBUG     1|0            write a debug log (default 0)
#   CLAUDISH_NOTICE    1|0            once-per-session on-screen notice when the
#                                           rewrite is skipped because setup or
#                                           configuration is missing, or the
#                                           model call fails (default 1)
# ---------------------------------------------------------------------------
set -uo pipefail

PLUGIN_ROOT="${1:-$(cd "$(dirname "$0")" 2>/dev/null && pwd -P)}"

ENABLED="${CLAUDISH_ENABLED:-1}"
# Runtime kill switch: env is frozen at session launch, so a hotkey or script
# can't flip CLAUDISH_ENABLED mid-session. A flag file can be checked fresh on
# every invocation. Create it to pause rewrites instantly; remove it to resume.
[ -f "${CLAUDISH_OFF_FILE:-$HOME/.claude/claudish-off}" ] && ENABLED=0
MODE="${CLAUDISH_MODE:-append}"
MIN_CHARS="${CLAUDISH_MIN_CHARS:-200}"
STUB="${CLAUDISH_STUB:-0}"
LLM_TIMEOUT="${CLAUDISH_TIMEOUT:-45}"
DEBUG="${CLAUDISH_DEBUG:-0}"
NOTICE="${CLAUDISH_NOTICE:-1}"

BUF_ROOT="${TMPDIR:-/tmp}/claudish-to-english"
SEP=$'\n\n────────────────────────\n💬 In plain English:\n\n'

mkdir -p "$BUF_ROOT" 2>/dev/null || true

dbg() { [ "$DEBUG" = "1" ] && printf '%s [%s] %s\n' "$(date '+%H:%M:%S')" "$$" "$*" >> "$BUF_ROOT/debug.log" 2>/dev/null; return 0; }

# Fail-open: keep the original delta on screen.
pass_through() { dbg "pass_through"; exit 0; }

# Replace this chunk's on-screen text with $1 (a temp file, read and then
# removed here — the opportunistic find below only sweeps buffer DIRECTORIES,
# so without this these would pile up in TMPDIR one per assistant message).
emit() {
  jq -n --rawfile dc "$1" \
    '{hookSpecificOutput:{hookEventName:"MessageDisplay",displayContent:$dc}}' \
    2>/dev/null || { rm -f "$1" 2>/dev/null; pass_through; }
  rm -f "$1" 2>/dev/null
  exit 0
}

# Emit an empty string (used to suppress intermediate chunks in replace mode).
emit_empty() {
  jq -n '{hookSpecificOutput:{hookEventName:"MessageDisplay",displayContent:""}}' 2>/dev/null || pass_through
  exit 0
}

[ "$ENABLED" = "1" ] || pass_through
command -v jq  >/dev/null 2>&1 || pass_through

payload="$(cat)"
[ -n "$payload" ] || pass_through

mid="$(printf '%s' "$payload"   | jq -r '.message_id // empty' 2>/dev/null)"
sid="$(printf '%s' "$payload"   | jq -r '.session_id // "nosession"' 2>/dev/null)"
idx="$(printf '%s' "$payload"   | jq -r '(.index // 0) | tostring' 2>/dev/null)"
final="$(printf '%s' "$payload" | jq -r '.final // false' 2>/dev/null)"
tpath="$(printf '%s' "$payload" | jq -r '.transcript_path // empty' 2>/dev/null)"
[ -n "$mid" ] || pass_through
case "$idx" in ''|*[!0-9]*) idx=0 ;; esac

# Opportunistic cleanup of abandoned buffers (older than 30 min), then of the
# session directories they leave behind once empty.
find "$BUF_ROOT" -mindepth 2 -maxdepth 2 -type d -mmin +30 -exec rm -rf {} + 2>/dev/null || true
find "$BUF_ROOT" -mindepth 1 -maxdepth 1 -type d -empty -mmin +30 -exec rmdir {} + 2>/dev/null || true

mdir="$BUF_ROOT/$sid/$mid"
mkdir -p "$mdir" 2>/dev/null || pass_through

# Persist this chunk's delta exactly (jq -j = no added trailing newline).
printf '%s' "$payload" | jq -j '.delta // ""' > "$mdir/$(printf '%08d' "$idx").part" 2>/dev/null || pass_through
dbg "chunk idx=$idx final=$final mid=$mid mode=$MODE"

# ---- non-final chunks ----------------------------------------------------
if [ "$final" != "true" ]; then
  # append: let the original stream through untouched.
  # replace: suppress the streamed original; the whole rewrite lands on final.
  if [ "$MODE" = "replace" ]; then emit_empty; else pass_through; fi
fi

# ---- final chunk: reconstruct + rewrite ----------------------------------
full="$(cat "$mdir"/*.part 2>/dev/null)"
final_part="$mdir/$(printf '%08d' "$idx").part"

# Prose length gate (strip fenced code blocks, then count non-space chars).
prose_len="$(printf '%s' "$full" \
  | awk 'BEGIN{f=0} /^```/{f=!f; next} f==0{print}' \
  | tr -d '[:space:]' | wc -c | tr -d ' ')"
dbg "final: prose_len=$prose_len min=$MIN_CHARS mode=$MODE full_bytes=${#full}"

cleanup() { rm -rf "$mdir" 2>/dev/null || true; }

# Below threshold -> do not rewrite.
if [ "${prose_len:-0}" -lt "$MIN_CHARS" ]; then
  dbg "skip: below min_chars"
  cleanup
  # replace mode already blanked the intermediate chunks, so it MUST re-show
  # the full original here; append mode already streamed it.
  if [ "$MODE" = "replace" ]; then
    out="$mdir.orig"; printf '%s' "$full" > "$out" 2>/dev/null && emit "$out"
  fi
  pass_through
fi

# ---- obtain the rewrite --------------------------------------------------
rewrite=""
llm_rc=0
failure=""
if [ "$STUB" = "1" ]; then
  nparts="$(ls "$mdir"/*.part 2>/dev/null | wc -l | tr -d ' ')"
  rewrite="STUB-SIMPLIFIED ✦ mode=$MODE chunks=$nparts prose_len=$prose_len ✦ (this text came from the hook, not the model)"
  dbg "stub rewrite"
else
  sys="You rewrite the assistant's message into much simpler, plain English. Keep every fact, name, number, and file path. Use short sentences and everyday words. Leave fenced code blocks unchanged. Output ONLY the rewritten message with no preamble, labels, or commentary."

  # Context only: the original user question the assistant is answering.
  # Truncated to 800 codepoints inside jq (safe on multibyte boundaries).
  userq=""
  if [ -n "$tpath" ] && [ -f "$tpath" ]; then
    userq="$(jq -rs '([ .[] | select(.type=="user" and (.message.content|type=="string") and (.isMeta!=true)) | .message.content ] | last // "") | .[0:800]' "$tpath" 2>/dev/null)"
  fi
  if [ -n "$userq" ]; then
    sys="$sys"$'\n\n'"For context, the user asked the assistant: \"$userq\". Use this only to understand the message. Do NOT rewrite, answer, or repeat the user's question — rewrite only the assistant's message that follows."
    dbg "context: userq_bytes=${#userq}"
  fi

  req_ok=1
  [ -n "$sys" ] && [ -n "$full" ] || req_ok=0
  if [ "$req_ok" != "1" ]; then
    llm_rc=1
    failure="request"
  else
    rewrite="$(printf '%s' "$full" | "$PLUGIN_ROOT/claudish-call.sh" "$sys" "$LLM_TIMEOUT")"
    llm_rc=$?
    [ "$llm_rc" = "124" ] && failure="timeout"
    [ "$llm_rc" = "3" ] && failure="cli"
    [ "$llm_rc" != "0" ] && [ -z "$failure" ] && failure="provider"
    [ "$llm_rc" = "0" ] && [ -z "$rewrite" ] && failure="empty"
  fi
  dbg "llm rc=$llm_rc failure=${failure:-none} rewrite_bytes=${#rewrite}"
fi

# Empty/failed rewrite -> fail open (or re-show original in replace mode).
if [ -z "$rewrite" ]; then
  dbg "empty rewrite -> fail open (llm_rc=$llm_rc failure=${failure:-none})"

  # One-time, per-session notice when the cause is a FIXABLE setup problem:
  # missing setup/configuration, timeout, or provider failure. A merely empty
  # completion stays silent because the provider did return successfully.
  # The notice only APPENDS one line to the original; it never suppresses
  # content, so the fail-open contract still holds.
  notified="$BUF_ROOT/$sid.notified"
  if [ "$NOTICE" = "1" ] && [ ! -e "$notified" ] && [ -n "${failure:-}" ] && [ "$failure" != "empty" ]; then
    : > "$notified" 2>/dev/null || true
    last_delta="$(cat "$final_part" 2>/dev/null)"
    case "$failure" in
      cli) why="the \`claude\` CLI is not on PATH" ;;
      timeout) why="the rewrite timed out after ${LLM_TIMEOUT}s — raise CLAUDISH_TIMEOUT or set CLAUDISH_MODEL to a faster model" ;;
      *) why="the rewrite call failed — check that \`claude\` runs and you are logged in" ;;
    esac
    note=$'\n\n────────────────────────\n'"⚠️ claudish-to-english: $why. Showing Claude's original text unchanged. Shown once per session; set CLAUDISH_NOTICE=0 to silence."
    out="$BUF_ROOT/$sid.$mid.notice"
    if [ "$MODE" = "replace" ]; then
      { printf '%s' "$full"; printf '%s' "$note"; } > "$out" 2>/dev/null
    else
      { printf '%s' "$last_delta"; printf '%s' "$note"; } > "$out" 2>/dev/null
    fi
    cleanup
    emit "$out"
  fi

  cleanup
  if [ "$MODE" = "replace" ]; then
    out="$mdir.orig"; printf '%s' "$full" > "$out" 2>/dev/null && emit "$out"
  fi
  pass_through
fi

# ---- build displayContent for the final chunk ----------------------------
out="$BUF_ROOT/$sid.$mid.out"
if [ "$MODE" = "replace" ]; then
  # Everything before was suppressed; show only the rewrite.
  printf '%s' "$rewrite" > "$out"
else
  # append: keep the streamed original (final chunk = its last delta),
  # then append the simplified version.
  { cat "$final_part" 2>/dev/null; printf '%s' "$SEP"; printf '%s' "$rewrite"; } > "$out"
fi
cleanup
emit "$out"
