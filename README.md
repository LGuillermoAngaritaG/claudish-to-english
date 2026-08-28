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
- Adds `/claudish-to-english:configure` for choosing the rewrite model.
- Keeps both display and Markdown hooks fail-open and includes deterministic
  tests that stub the CLI and never make a real model call.

## Install and one-time setup

Install from this repository's marketplace:

```text
/plugin marketplace add LGuillermoAngaritaG/claudish-to-english
/plugin install claudish-to-english@gvzdv-plugins
```

Then exit Claude Code and explicitly initialize installed plugins:

```bash
claude --init-only
```

The only model-runtime prerequisite is
[`uv`](https://docs.astral.sh/uv/getting-started/installation/). The hooks also
use `jq`; install it separately if it is not already available (for example,
`brew install jq` on macOS). You do not need to install or select Python, create
a virtual environment, or run `pip` yourself. If Python 3.14 is unavailable,
`uv` downloads and manages it automatically.

The plugin's documented `Setup` hook creates a versioned virtual environment
under `${CLAUDE_PLUGIN_DATA}`, uses `uv` to install the exact dependencies from
`requirements.lock` with required hashes, verifies LiteLLM is exactly `1.93.2`,
and atomically activates that runtime. The managed Python interpreter,
environment, and package cache all stay under plugin data. Setup does not
install a plugin command on your global `PATH`, invoke `pip`, or modify your
project or shell profile. Uninstalling the plugin without `--keep-data` removes
that private runtime state with the rest of its plugin data.

Start Claude Code again and invoke the user-only configuration command:

```text
/claudish-to-english:configure
```

The interactive script asks only for a model alias, defaulting to `haiku`.
There is no key to enter; the CLI reuses the login you already have. Normal
model invocation cannot trigger this command automatically.

If the runtime or configuration is unavailable, the first skipped rewrite in a
session explains which of those two commands to run. The original text remains
visible.

## Choosing a model

Any alias the Claude Code CLI accepts works, so `haiku`, `sonnet`, or a full
model id such as `claude-haiku-4-5`:

```text
Model alias [haiku]: haiku
```

`haiku` is the default because the display hook fires on every assistant
message. Re-run `/claudish-to-english:configure` to change it.

Rewrites cost roughly five seconds each, nearly all of it CLI startup rather
than the model. They also draw on the same usage allowance as your interactive
sessions, so a chatty session spends real quota on rewrites.

## Configuration and privacy

Configuration is stored as local plaintext at
`${CLAUDE_PLUGIN_DATA}/config.json`. It now holds only a model alias, no
credential. On POSIX systems the plugin still enforces mode `0600` on the file
and `0700` on its directory, writes through a temporary file, fsyncs it, and
activates it with an atomic rename.

Rewrites are sent to Anthropic under your existing Claude credentials, the same
path as your interactive sessions. Display rewrites include the assistant
message plus up to 800 characters of the original user question as context;
Markdown rewrites send the Markdown body. Unlike earlier versions of this fork,
there is no local-only option: routing through the CLI means rewrites always
leave your machine.

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

## Behavior configuration

Rewrites need no launch-time environment variables. The `CLAUDISH_*` variables
only control hook behavior:

| Variable | Default | Meaning |
|---|---:|---|
| `CLAUDISH_ENABLED` | `1` | Master switch; `0` passes everything through. |
| `CLAUDISH_OFF_FILE` | `~/.claude/claudish-off` | Live pause flag checked on every invocation. |
| `CLAUDISH_MODE` | `append` | Display mode: `append` or `replace`. |
| `CLAUDISH_MIN_CHARS` | `200` | Skip shorter prose after stripping fenced code. |
| `CLAUDISH_TIMEOUT` | `45` | Display rewrite timeout in seconds; covers CLI startup too. |
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

The rewrite path no longer imports LiteLLM; it shells out to the Claude Code
CLI and needs only the standard library. The `Setup` hook still provisions the
hash-locked runtime below, which is now vestigial and slated for removal.

LiteLLM `1.82.7` and `1.82.8` were affected by a 2026 PyPI supply-chain
compromise; see the [LiteLLM security advisory](https://github.com/BerriAI/litellm/issues/24518).
This plugin deliberately uses the later signed
[LiteLLM v1.93.2 release](https://github.com/BerriAI/litellm/releases/tag/v1.93.2)
and pins the complete transitive dependency set with package hashes. Setup uses
`uv`, binary distributions only, and validates the installed LiteLLM version
before activating it. Ambient project and user `uv` configuration is ignored
for this installation.

The setup flow follows Claude Code's official documentation for
[Setup hooks](https://code.claude.com/docs/en/hooks#setup) and
[persistent plugin data](https://code.claude.com/docs/en/plugins-reference#persistent-data-directory).
The configuration command is declared
[user-only](https://code.claude.com/docs/en/slash-commands#control-who-invokes-a-skill),
and plugin path variables follow the
[plugin reference](https://code.claude.com/docs/en/plugins-reference).

## Development and testing

The deterministic suite stubs the `claude` binary and a fake private runtime;
it never makes a real model call:

```bash
uv run --no-project --no-config --python 3.14 python -B -m unittest discover -s tests -p 'test_*.py'
bash tests/test_hooks.sh
```

## Layout

```text
claudish-to-english/
├── .claude-plugin/       plugin and marketplace manifests
├── hooks/hooks.json      Setup, MessageDisplay, and PostToolUse hooks
├── requirements.in       deliberately pinned top-level dependency
├── requirements.lock     complete hash-locked runtime dependencies
├── scripts/              uv launchers, setup, configuration, internal helper
├── skills/configure/     user-only configuration command
├── tests/                deterministic unit and hook integration tests
├── rewrite.sh            display hook
└── rewrite-md.sh         opt-in Markdown hook
```

## License

MIT — see [LICENSE](./LICENSE).
