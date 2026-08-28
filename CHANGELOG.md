# Changelog

This fork tracks [gvzdv/claudish-to-english](https://github.com/gvzdv/claudish-to-english)
selectively. It has no shared git history with upstream, so changes are ported
rather than merged.

## 0.5.0

Ported from upstream v0.8.0, keeping this fork's CLI routing and prompts:

- `/claudish` slash command and `claudish-ctl.sh` for mid-session control of
  on/off, append/replace, style, language and model. Adapted: upstream sources
  `providers.sh`, which this fork does not have, so the provider is fixed to the
  `claude` CLI and the model default is `haiku`.
- `lang.sh`, so the rewrite follows the session's `language` setting instead of
  hard-coding English. The base prompts now say "plain language" and carry
  upstream's same-language rule.
- The `tldr`, `5y` and `caveman` style presets, as `prompts/style-*.md` files
  rather than shell strings, so they are editable like every other prompt.
- Upstream's hook-command quoting fix (`a172e1e`).

Fork-specific fixes found while porting:

- `/claudish last` skipped the nested rewrite transcripts this fork writes, so
  it could print a rewrite back as if it were the original. Upstream cannot hit
  this: it has no nested sessions.
- `/claudish model` wrote a flag file nothing read. The CLI call now resolves
  file > env > `haiku`.

- Raise `CLAUDISH_TIMEOUT` to 300s, with the hook ceiling at 310s. A dense
  message measured 46-52s, so this is headroom rather than a fit.

Not ported: `providers.sh` (conflicts with CLI routing) and `session-notice.sh`.

## 0.4.2

- Sweep the nested rewrite session transcripts, which had reached 2.0 MB.

## 0.4.1

- Raise the `MessageDisplay` hook ceiling to 100s, above the script's own 90s
  watchdog, so a slow rewrite fails open instead of being killed.
- Correct the README's latency and privacy claims against measurement.

## 0.4.0

- Move the system prompts into editable `prompts/` files.
- Rewrite them against the text-simplification literature: verbatim retention of
  numbers, dates and identifiers, a licence to leave clear sentences alone, and
  a 25-word sentence cap.
- Raise `CLAUDISH_TIMEOUT` to 90s.

## 0.3.0

- Stop the nested rewrite session leaking a false "CLI is not on PATH" notice
  into the rewrite text.
- Route rewrites through the Claude Code CLI instead of LiteLLM; drop Python.
