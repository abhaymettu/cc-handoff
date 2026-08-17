# cc-handoff

An MCP server that routes work from a Claude Desktop chat into Claude Code, either
headlessly, or by opening a terminal you can take over.

The point is the handoff. You ask a question in chat, it runs headlessly in the right
directory, and when you want to drive it yourself the *same session* opens in a real
terminal with its history intact.

## Profiles

A profile is a directory containing a `CLAUDE.md`. That is the whole definition. Each
one has its own instructions and its own folder-scoped memory, so "which profile" is
really "which agent".

Everyone organises these differently, so `setup` reads three layers rather than assuming
one convention:

1. **Names you already chose.** If your shell rc defines a `CLAUDE_PROFILES` map, those
   names and paths are used as-is and sorted to the top. Nobody has to adopt anyone
   else's naming scheme.
2. **Where you actually work.** `~/.claude.json` records every directory you have run
   Claude Code in and when, so the list is ranked by real use rather than by guesswork.
   Worktrees, temp dirs, and `$HOME` are filtered out.
3. **A filesystem scan**, for a machine with no history yet.

Each layer degrades to the next, so a fresh install with no conventions at all still
produces a sensible list. `--limit` caps how many are kept (12 by default).

Every tool runs inside a named profile. There is no free-form path parameter. A
directory that is not in your config cannot be touched.

## Install

Paste this repo's URL to your coding agent and say "install this". It will read
[AGENTS.md](AGENTS.md), work out your profiles, show them to you, and ask before writing
anything.

By hand:

```sh
git clone https://github.com/abhaymettu/cc-handoff
cd cc-handoff
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m cc_handoff setup --dry-run    # see the plan first
.venv/bin/python -m cc_handoff setup --default scratch
.venv/bin/python -m cc_handoff doctor             # confirm it works
```

`setup` walks a few roots for `CLAUDE.md` files, detects which terminal you use and pins
it, writes `~/.config/cc-handoff/config.toml`, and registers itself in
`claude_desktop_config.json` (backing up whatever was there). Restart Claude Desktop
afterward.

Re-running `setup` never destroys a config you have edited: it keeps the profiles already
in the file and only refreshes the terminal and default. Pass `--rescan` to look for new
profiles, which adds but never drops.

It over-collects on purpose. Open the toml and delete what you do not want:

```toml
default_profile = "scratch"

[profiles]
brain   = "/Users/you/Documents/Brain"
scratch = "/Users/you/scratch"
```

Other commands: `cc_handoff profiles`, `cc_handoff terminals`, `cc_handoff doctor`.

`setup --dry-run` prints the plan and writes nothing. Add `--json` to either `setup` or
`doctor` for machine-readable output, which is what an agent driving the install uses.
`doctor` exits non-zero when something fatal is wrong.

## Tools

| Tool | What it does |
|---|---|
| `list_profiles()` | Names, paths, and a one-line gist from each `CLAUDE.md` |
| `ask_claude_code(prompt, profile, allow_edits=False)` | Headless `claude -p`; returns the answer and a `session_id` |
| `handoff_to_terminal(session_id, profile, terminal)` | Reopens that session in a terminal via `--resume` |
| `open_in_claude_code(brief, profile, terminal)` | Writes `<profile>/.claude/HANDOFF.md`, opens a terminal there |

`allow_edits` defaults to false and must be set deliberately.

### Permissions do not survive the handoff

`allow_edits` applies only to the headless run. `handoff_to_terminal` resumes that
session with no permission flags, so once a window is open you are under ordinary
interactive Claude Code rules and approve actions yourself.

This is deliberate. A read-only headless answer becoming a read-only terminal would be
the wrong default: you are at the keyboard now, and the interactive permission prompt is
a better gate than a flag inherited from a chat message. But it does mean a restricted
headless call can be continued into an unrestricted session, so do not treat
`allow_edits=False` as a durable sandbox.

## Terminals

| Terminal | Status |
|---|---|
| Ghostty | tested |
| Terminal.app | tested |
| kitty | untested |
| WezTerm | untested |
| Alacritty | untested |
| iTerm2 | untested |

Untested recipes are written from each emulator's documented flags but have never been
run. If one fails, that is a bug worth reporting.

`setup` picks your terminal once and writes it to the config, so it is a decision you can
see and edit rather than a guess made on every call. Selection order at runtime: the
tool's `terminal` argument, then `terminal` in the config, then `$CC_HANDOFF_TERMINAL`,
then whatever is running (`TERM_PROGRAM`), then whatever is installed. macOS only for now.

### One window per profile

`open_in_claude_code` checks whether a session is already running in that directory. If
one is, it updates `HANDOFF.md` and tells you to switch to that window and say "reread
.claude/HANDOFF.md" instead of stacking up another. Pass `new_window=true` to override.

Tabs are not an option: `open -na` has to start a separate instance to pass `-e`, plain
`open -a` ignores `--args`, Ghostty's `+new-window` action is Linux-only, and macOS
native tabbing cannot merge windows across instances.

Ghostty is launched with `open -na Ghostty.app --args ... -e <command>`, which is what
Ghostty's own help tells you to do: running the bundle binary directly is unsupported on
macOS, starts a fresh instance per call, restores every saved tab, and makes macOS
re-prompt for permission to exec the CLI each time.

`--window-save-state=never` is passed so a handoff window opens empty rather than
restoring an old session. Reusing an already-running instance is not possible. Plain
`open -a` accepts `--args` and silently ignores them.

## Quoting

Briefs and prompts never meet a shell. Commands are built as argv lists and run with
`shell=False`; the brief is written with `Path.write_text`. `tests/quoting_probe.py`
pushes quotes, backticks, `$(whoami)`, newlines, and AppleScript injection bait through
the wire and asserts the file on disk is byte-identical.

iTerm2 and Terminal.app are the one exception: AppleScript only accepts a command
string, so those recipes go through `shlex.quote` and then AppleScript escaping.

## Environment

| Variable | Default |
|---|---|
| `CC_HANDOFF_CLI` | `claude` |
| `CC_HANDOFF_CONFIG` | `~/.config/cc-handoff/config.toml` |
| `CC_HANDOFF_TERMINAL` | auto-detected |
| `CC_HANDOFF_TIMEOUT` | `600` |

Pointing `CC_HANDOFF_CLI` at another agent CLI mostly works, as long as it accepts
`-p` and `--resume`.

## Tests

```sh
.venv/bin/python tests/stdio_probe.py     # MCP protocol over a real pipe
.venv/bin/python tests/quoting_probe.py   # hostile brief, byte-identical on disk
.venv/bin/python tests/e2e_probe.py       # ask -> handoff; spends real tokens
```

## Relation to other projects

This is not a fork. It shares no code with any other project and was written from
scratch.

The closest existing thing is [steipete/claude-code-mcp](https://github.com/steipete/claude-code-mcp)
(JavaScript, MIT), which wraps the Claude Code CLI in a single `claude_code` tool for
one-shot delegation. If all you want is "let my MCP client run a Claude Code prompt",
use that. It is mature and widely used.

cc-handoff is aimed at a different problem, and differs in three ways that matter:

- **Session continuity.** The point here is that a headless answer can be reopened on
  your screen with its history intact, via `--resume`. One-shot delegation has no
  equivalent; the work ends when the call returns.
- **Profile routing.** Work is addressed to a named directory rather than a path
  supplied per call, so "which agent" is a first-class argument and unlisted directories
  cannot be reached at all.
- **Permission default.** `allow_edits` is false unless asked for. steipete's server
  historically starts Claude Code with `--dangerously-skip-permissions` by default
  (configurable via `permissionMode`).

It is also Python rather than JavaScript, and macOS-only, where that server is
cross-platform.

## Requirements

macOS, Python 3.10+, `mcp` (2.x or 1.x, the import is version-guarded), and the
`claude` CLI on `PATH`.
