# Installing cc-handoff

You are an agent installing this for the person you are working with. Follow these steps
in order. Stop and ask before step 5, which is the only step that writes anything.

This installs a local MCP server for Claude Desktop. It is macOS only.

## 1. Check the prerequisites

```sh
python3 --version                  # need 3.10 or newer
command -v claude || echo MISSING  # the Claude Code CLI must be on PATH
```

Do not use `which claude`. Many people wrap it in a shell function, and `which` prints
the function body rather than a path, which is easy to misread in both directions. The
authoritative check is `doctor` in step 6.

If `claude` is missing, stop and tell the user to install Claude Code first. Nothing else
here will work without it.

## 2. Install

```sh
git clone https://github.com/abhaymettu/cc-handoff
cd cc-handoff
python3 -m venv .venv
.venv/bin/pip install -e .
```

Use the venv interpreter for every command below. Do not install into system Python.

## 3. Ask what it would do

```sh
.venv/bin/python -m cc_handoff setup --dry-run --json
```

This writes nothing. It returns the full plan as JSON:

- `profiles`, the directories it proposes, each with `name`, `path`, `gist`, `exists`,
  and `new`
- `profile_source`, whether these were discovered or kept from a config already present
- `default_profile` and `default_valid`
- `terminal` and `terminal_tested`
- `desktop_config`, where Claude Desktop's config lives and whether cc-handoff is in it

If `profiles` is empty, the user has no directories with a `CLAUDE.md`. Tell them that a
profile is just a directory with its own `CLAUDE.md`, and that they should create one
before continuing.

## 4. Show the user and get a decision

Do not skip this. Setup writes to their Claude Desktop config and decides which
directories become reachable from a chat window.

Show them the proposed profile names and paths, then ask:

1. Which of these should be kept? It over-collects deliberately.
2. Which should be the default when they do not name one?
3. Is the detected terminal right?

If `terminal_tested` is false, say so plainly: only Ghostty and Terminal.app are
verified, the rest are written from documented flags and have never been run.

## 5. Write the config

```sh
.venv/bin/python -m cc_handoff setup --default <their choice>
```

Then open `~/.config/cc-handoff/config.toml` and delete the profiles they did not want.
That file is meant to be hand-edited. Re-running `setup` keeps the profile entries, but
it rewrites the file, so comments and unknown keys do not survive. Tell the user that.

Use `--terminal <name>` if their answer differed from what was detected.

## 6. Verify

```sh
.venv/bin/python -m cc_handoff doctor
```

Every line must read `ok`. `--json` gives `{"ok": bool, "checks": [...]}` and exits
non-zero if anything fatal failed. Common failures:

| Failure | Fix |
|---|---|
| `mcp package` | `.venv/bin/pip install 'mcp>=2'` |
| `server builds` | usually mcp 1.x; run `.venv/bin/pip install 'mcp>=2'` |
| `terminal` not installed | the .app exists but its CLI does not; pick another with `--terminal` |
| `claude CLI` not on PATH | install Claude Code, or set `CC_HANDOFF_CLI` |
| `profile paths` missing | a path in the config no longer exists, edit the file |
| `Claude Desktop` not registered | re-run step 5; do not pass `--no-register` |
| Desktop points at another interpreter | re-run step 5 from this venv |

## 7. Hand back

Tell the user to quit and reopen Claude Desktop, then try:

> "list my cc-handoff profiles"

and once that works:

> "ask claude code in <profile> what files are here, then open that session in a terminal"

The second one is the point of the tool. It answers in chat, then puts a real terminal on
screen with that same session and its history.

## Things worth knowing

- Every tool call runs inside a named profile. There is no free-form path argument, so a
  directory not in the config cannot be reached.
- `allow_edits` is false unless asked for, and it does not survive into a terminal
  session. Once a window is open the user is under normal interactive permissions.
- `open_in_claude_code` will not open a second window on a profile that already has a
  session running. It updates `HANDOFF.md` and says to reuse the open one.
- Re-running `setup` keeps profiles already in the config. `--rescan` looks for new ones
  and adds without dropping.
