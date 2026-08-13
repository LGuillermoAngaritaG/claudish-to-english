---
name: configure
description: Interactively configure the private model provider used by claudish-to-english
disable-model-invocation: true
---

Run the bundled interactive configurator in the foreground:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/configure.py" --plugin-data "${CLAUDE_PLUGIN_DATA}"
```

The user must type provider, model, endpoint, and (when required) API key into
the terminal. Never ask them to paste an API key into the conversation. Never
read, print, summarize, or otherwise expose `config.json`; report only whether
the configurator succeeded or failed. The script itself reads secrets without
echo and writes the configuration atomically with restrictive permissions.
