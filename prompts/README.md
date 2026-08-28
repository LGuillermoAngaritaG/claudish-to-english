# Prompts

The system prompts the hooks send to the model. Edit these files to change how
rewrites read; no code change and no restart is needed, they are read fresh on
every rewrite.

| file | used by | placeholders |
|---|---|---|
| `display.md` | `rewrite.sh` — the on-screen message rewrite | none |
| `context.md` | `rewrite.sh` — appended to `display.md`, but only when the user's question was recoverable from the transcript | `{{user_question}}` |
| `markdown.md` | `rewrite-md.sh` — the `PostToolUse` Markdown file rewrite | none |

Placeholders are substituted literally, so a question containing `&`, `\`, `*`,
`$VAR` or newlines is inserted as written.

A file that is missing or empty falls back to the built-in prompt compiled into
the script, so a bad edit degrades to the default instead of breaking the hook.
