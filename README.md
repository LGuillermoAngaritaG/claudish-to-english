# claudish-to-english

<p align="center">
  <img
    src="https://github.com/gvzdv/claudish-to-english/releases/download/assets/comparison.png"
    width="820"
    alt="Side-by-side comparison of a dense Claude message and its plain-English rewrite">
</p>

A Claude Code plugin that shows a plain-English rewrite of each assistant
message. Rewrites run through the Claude Code CLI on your existing login, so a Claude
subscription covers them and no API key is stored. Claude's reasoning and saved
transcript keep the original text; only the display changes.

An optional second hook rewrites Markdown files into plain English when Claude
writes or edits them. It is opt-in and defaults to a non-destructive sibling
file.

Every hook fails open. Missing configuration, CLI errors, timeouts, or empty
responses leave Claude's original text (and source files) unchanged.

## What this fork adds

- Replaces direct Ollama HTTP calls with a `claude -p` subprocess, so rewrites
  bill against an existing Claude subscription instead of a metered API key.
- Marks the nested CLI session with `CLAUDISH_INNER` and returns from the
  display hook immediately when it is set, so the nested session cannot append
  its own fail-open notice into the rewrite text the outer session displays.
  The nested session runs in a scratch directory to keep one-shot sessions out
  of the caller's project history.
- Moves the system prompts out of the shell scripts into editable
  [`prompts/`](prompts/) files, written against the published text-simplification
  literature: verbatim retention of numbers, dates and identifiers, an explicit
  licence to leave already-clear sentences alone, and a 25-word sentence cap.
- Drops Python entirely. There is no setup step, no `uv`, no virtual
  environment, no pinned dependency set, and no configuration file: three bash
  scripts and `jq`.
- Keeps both display and Markdown hooks fail-open and includes deterministic
  tests that stub the CLI and never make a real model call.

## Install

```text
/plugin marketplace add LGuillermoAngaritaG/claudish-to-english
/plugin install claudish-to-english@guillermoangarita-plugins
```

That is the whole installation. There is no setup hook and no runtime to
provision.

### Requirements

| | Why |
|---|---|
| `bash` | The hooks are bash. No bash-4 features are used, so macOS's stock 3.2 is fine. |
| `jq` | Parses the hook payload. Install separately if missing, for example `brew install jq`. |
| `claude` on `PATH` | Rewrites run as a nested `claude -p` subprocess. |
| A Claude login | The nested call bills against your existing subscription. No API key is read or stored. |

Both `jq` and `claude` are checked before use and fail open, so a missing one
costs you the rewrite and never the message. `awk`, `tr`, `wc`, `find`, `sed`,
`mktemp` and `date` are also called, all POSIX-standard. There is no `timeout`
binary requirement: the CLI call is bounded by a hand-rolled watchdog, because
macOS does not ship one.

If the CLI is missing, the first skipped rewrite in a session says so and the
original text stays on screen.

## Choosing a model

Set `CLAUDISH_MODEL` to any alias the Claude Code CLI accepts, such as `haiku`,
`sonnet`, or a full model id:

```json
{
  "env": { "CLAUDISH_MODEL": "haiku" }
}
```

It defaults to `haiku` because the display hook fires on every assistant
message.

Rewrite latency scales with the message, and the model dominates it. A bare CLI
call costs about three seconds, and a dense technical message rewrites in about
four on `haiku`. Rewriting needs no reasoning, so the call sets
`MAX_THINKING_TOKENS=0`: left on, `haiku` spent 1597 of 1721 output tokens
thinking about a message that rewrote to 110, which took the same rewrite from
under four seconds to roughly 24. `CLAUDISH_TIMEOUT`
defaults to 300 seconds so a long message is never cut off, and the
`MessageDisplay` hook is given 310 in `hooks.json` so the script's own watchdog
always fails open before Claude Code kills the process. Lower it if you would
rather a slow rewrite give up quickly than keep the block pending.

Rewrites also draw on the same usage allowance as your interactive sessions, so
a chatty session spends real quota on them.

## Privacy

Rewrites are sent to Anthropic under your existing Claude credentials, the same
path as your interactive sessions. Display rewrites include the assistant
message plus up to 800 characters of the original user question as context;
Markdown rewrites send the Markdown body. Unlike earlier versions of this fork,
there is no local-only option: routing through the CLI means rewrites always
leave your machine.

Three things land on disk:

- Chunk buffers under `$TMPDIR/claudish-to-english`, removed as each message
  completes.
- A `<session-id>.notified` flag per session in the same directory, so the
  fail-open notice appears only once. These are small and are swept with the
  buffer directories after 30 minutes.
- **A full transcript of every nested rewrite session**, written by the Claude
  Code CLI into `~/.claude/projects/<slugified-scratch-path>/`. Each one
  contains the assistant message that was rewritten. Upstream leaves these to
  accumulate -- 36 of them totalling 2.0 MB built up while developing this
  fork -- so each rewrite now sweeps those older than 30 minutes. Only
  directories matching `*claudish*cli-scratch` are touched; your real project
  transcripts are never read or removed.

## Display hook

Claude Code fires `MessageDisplay` for each streamed chunk. The hook buffers
chunks in `$TMPDIR/claudish-to-english`, makes one bounded model call after the
final chunk, and removes the buffer.

| Mode | Result |
|---|---|
| `append` (default) | Streams the original normally, then appends a `💬 In plain English:` block. |
| `replace` | Suppresses intermediate chunks and shows only the rewrite. If rewriting fails, it re-shows the full original. |

## Markdown hook

The `PostToolUse` hook is off until `CLAUDISH_MD_DIR` is set. It only processes
Markdown files whose canonical path is below that directory.

| Mode | Result |
|---|---|
| `sibling` (default) | Writes `NAME.plain.md`; the original is untouched. |
| `overwrite` | Atomically replaces `NAME.md` and adds an idempotency marker. |

YAML frontmatter is detached and reattached verbatim. Fenced code is protected
by the model instruction. An error or empty response never writes a partial or
empty file.

For example, enable safe sibling output in your Claude Code `settings.json`:

```json
{
  "env": {
    "CLAUDISH_MD_DIR": "/absolute/path/to/docs",
    "CLAUDISH_MD_MODE": "sibling"
  }
}
```

## Changing the prompts

The system prompts sent to the model live in [`prompts/`](prompts/), one file
per hook. Edit a file and the next rewrite uses it; there is no restart, no
rebuild, and no environment variable to set.

| file | used by | placeholders |
|---|---|---|
| `prompts/display.md` | the on-screen message rewrite | none |
| `prompts/append.md` | appended to `display.md`, only in `append` mode where the original stays on screen | none |
| `prompts/context.md` | appended after those, only when the user's question was recoverable from the transcript | `{{user_question}}` |
| `prompts/markdown.md` | the `PostToolUse` Markdown rewrite | none |

Placeholders are substituted literally, so a question containing `&`, `\`, `*`,
`$VAR` or newlines is inserted as written. A file that is missing or empty falls
back to the prompt built into the script, so a bad edit degrades to the default
rather than breaking the hook.

## Styles, language, and `/claudish`

`/claudish` switches the rewrite mid-session without a restart. `/claudish` on
its own prints a dashboard; `on`, `off`, `append`, `replace`,
`style <tldr|5y|caveman>`, `language <name>`, `model <name>`, `last`, `cycle`
and `reset` each change one thing. Every override is a flag file re-read on the
next message, which is why it can take effect mid-session where a frozen
environment variable cannot.

| style | prompt file | result |
|---|---|---|
| default | `prompts/display.md` | plain-language rewrite |
| `tldr` | `prompts/style-tldr.md` | a summary, half the length or less |
| `5y` | `prompts/style-5y.md` | explained as if to a five-year-old |
| `caveman` | `prompts/style-caveman.md` | blunt caveman speak |

The rewrite follows the language of the message it rewrites. Set `language` in
your Claude Code `settings.json`, or `/claudish language <name>`, to force one;
`CLAUDISH_LANG=""` keeps the message's own language.

## Behavior configuration

Rewrites need no launch-time environment variables. The `CLAUDISH_*` variables
only control hook behavior:

| Variable | Default | Meaning |
|---|---:|---|
| `CLAUDISH_ENABLED` | `1` | Master switch; `0` passes everything through. |
| `CLAUDISH_OFF_FILE` | `~/.claude/claudish-off` | Live pause flag checked on every invocation. |
| `CLAUDISH_MODE` | `append` | Display mode: `append` or `replace`. |
| `CLAUDISH_MIN_CHARS` | `200` | Skip shorter prose after stripping fenced code. |
| `CLAUDISH_MODEL` | `haiku` | Model alias passed to the CLI. `/claudish model` writes a flag file that outranks it. |
| `CLAUDISH_STYLE` | unset | `tldr`, `5y` or `caveman`. `/claudish style` overrides via flag file. |
| `CLAUDISH_LANG` | unset | Force an output language. Set but empty keeps the message's own. |
| `CLAUDISH_TIMEOUT` | `300` | Display rewrite timeout in seconds; covers CLI startup too. |
| `CLAUDISH_MD_TIMEOUT` | `150` | Markdown model-call timeout in seconds. |
| `CLAUDISH_NOTICE` | `1` | Show one fail-open notice per session; `0` stays silent. |
| `CLAUDISH_DEBUG` | `0` | Log non-secret state and result sizes under `$TMPDIR/claudish-to-english`. |
| `CLAUDISH_STUB` | `0` | Deterministic local stub for hook testing; no model call. |
| `CLAUDISH_MD_DIR` | unset | Required opt-in root for Markdown rewriting. |
| `CLAUDISH_MD_MODE` | `sibling` | `sibling` or `overwrite`. |
| `CLAUDISH_MD_SUFFIX` | `plain` | Sibling filename infix. |

To pause and resume without restarting Claude Code:

```bash
touch ~/.claude/claudish-off
rm ~/.claude/claudish-off
```

## Dependency security

There are no third-party dependencies. Earlier versions of this fork installed
a hash-locked LiteLLM runtime to reach model providers; routing through the
Claude Code CLI removed the need for it, along with the supply-chain surface it
carried.

The hooks follow Claude Code's
[hooks reference](https://code.claude.com/docs/en/hooks) and the
[plugin reference](https://code.claude.com/docs/en/plugins-reference).

## Development and testing

The suite stubs the `claude` binary, so it never makes a real model call:

```bash
bash tests/test_hooks.sh
```

## Layout

```text
claudish-to-english/
├── .claude-plugin/       plugin and marketplace manifests
├── hooks/hooks.json      MessageDisplay and PostToolUse hooks
├── commands/claudish.md  the /claudish slash command
├── prompts/              the system prompts, one file per hook and style
├── tests/                hook integration tests
├── claudish-ctl.sh       /claudish runtime control
├── lang.sh               output-language resolver (sourced)
├── claudish-call.sh      one bounded CLI call, shared by both hooks
├── rewrite.sh            display hook
└── rewrite-md.sh         opt-in Markdown hook
```

## License

MIT — see [LICENSE](./LICENSE).
