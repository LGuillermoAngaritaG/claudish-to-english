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
- Marks the nested CLI session with `CLAUDISH_INNER` so its own display hook
  fails open instead of recursing, and runs it in a scratch directory to keep
  one-shot sessions out of the caller's project history.
- Drops Python entirely. There is no setup step, no `uv`, no virtual
  environment, no pinned dependency set, and no configuration file: three bash
  scripts and `jq`.
- Keeps both display and Markdown hooks fail-open and includes deterministic
  tests that stub the CLI and never make a real model call.

## Install

```text
/plugin marketplace add LGuillermoAngaritaG/claudish-to-english
/plugin install claudish-to-english@gvzdv-plugins
```

That is the whole installation. The hooks need `jq` and the `claude` CLI on
`PATH`; install `jq` separately if it is missing (for example, `brew install jq`
on macOS). There is no setup hook, no runtime to provision, and nothing written
outside the plugin directory.

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

Rewrites cost roughly five to seven seconds each, nearly all of it CLI startup
rather than the model. They also draw on the same usage allowance as your
interactive sessions, so a chatty session spends real quota on rewrites.

## Privacy

Rewrites are sent to Anthropic under your existing Claude credentials, the same
path as your interactive sessions. Display rewrites include the assistant
message plus up to 800 characters of the original user question as context;
Markdown rewrites send the Markdown body. Unlike earlier versions of this fork,
there is no local-only option: routing through the CLI means rewrites always
leave your machine.

Nothing is stored on disk beyond the chunk buffers under
`$TMPDIR/claudish-to-english`, which are removed as each message completes.

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

## Behavior configuration

Rewrites need no launch-time environment variables. The `CLAUDISH_*` variables
only control hook behavior:

| Variable | Default | Meaning |
|---|---:|---|
| `CLAUDISH_ENABLED` | `1` | Master switch; `0` passes everything through. |
| `CLAUDISH_OFF_FILE` | `~/.claude/claudish-off` | Live pause flag checked on every invocation. |
| `CLAUDISH_MODE` | `append` | Display mode: `append` or `replace`. |
| `CLAUDISH_MIN_CHARS` | `200` | Skip shorter prose after stripping fenced code. |
| `CLAUDISH_MODEL` | `haiku` | Model alias passed to the CLI. |
| `CLAUDISH_TIMEOUT` | `90` | Display rewrite timeout in seconds; covers CLI startup too. |
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
├── tests/                hook integration tests
├── claudish-call.sh      one bounded CLI call, shared by both hooks
├── rewrite.sh            display hook
└── rewrite-md.sh         opt-in Markdown hook
```

## License

MIT — see [LICENSE](./LICENSE).
