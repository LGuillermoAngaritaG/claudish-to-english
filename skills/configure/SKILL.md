---
name: configure
description: Interactively configure the model used by claudish-to-english
disable-model-invocation: true
---

Run the bundled interactive configurator in the foreground:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/configure.sh" \
  "${CLAUDE_PLUGIN_ROOT}" "${CLAUDE_PLUGIN_DATA}"
```

The user types a model alias into the terminal; there is no credential to
collect, since rewrites run through the Claude Code CLI on their existing
login. Report only whether the configurator succeeded or failed. The script
writes the configuration atomically with restrictive permissions.
