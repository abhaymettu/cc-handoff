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
   names and paths are used as-is and always survive `--limit`. Nobody has to adopt
   anyone else's naming scheme. The written list is alphabetical, not ranked.
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
.venv/bin/python -m cc_handoff setup --default <one of your profiles>
.venv/bin/python -m cc_handoff doctor             # confirm it works
```

`setup` walks a few roots for `CLAUDE.md` files, detects which terminal you use and pins
it, writes `~/.config/cc-handoff/config.toml`, and registers itself in
`claude_desktop_config.json` (backing up whatever was there). Restart Claude Desktop
afterward.

Re-running `setup` keeps every profile already in the file and only refreshes the
terminal and default. Pass `--rescan` to look for new profiles, which adds but never
drops. The file is rewritten rather than patched, so comments and any keys cc-handoff
does not know about are lost; keep notes elsewhere.

It over-collects on purpose. Open the toml and delete what you do not want:

```toml
default_profile = "scratch"

[profiles]
brain   = "/Users/you/Documents/Brain"
scratch = "/Users/you/scratch"
```

Other commands: `cc-handoff profiles`, `cc-handoff terminals`, `cc-handoff doctor`.
The console script is `cc-handoff`; `python -m cc_handoff` is equivalent.

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

| Terminal | Status | How it launches |
|---|---|---|
| Ghostty | tested | `open -na` |
| Terminal.app | tested | AppleScript |
| iTerm2 | untested | AppleScript |
| kitty | untested | needs its CLI |
| WezTerm | untested | needs its CLI |
| Alacritty | untested | needs its CLI |

Untested means never run, not "probably works". Expect the three that need a CLI to
fail unless you have installed it: kitty, WezTerm and Alacritty ship their command
line tool inside the .app bundle and do not put it on `PATH` on their own. cc-handoff
looks on `PATH` first and then inside the bundle, and refuses to select a terminal it
cannot actually launch, so the failure is an error message rather than a hang.

Auto-selection prefers tested recipes. An untested one is only chosen if it is the
terminal you are currently running in, or if nothing tested is installed.

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

The brief never meets a shell. It is written with `Path.write_text` and never enters an
argv. Commands are built as argv lists and run with `shell=False` for four of the six
terminals; iTerm2 and Terminal.app are the exception, see below. 

iTerm2 and Terminal.app are the exception: AppleScript takes a command string, not an
argv, so those recipes build `cd <dir> && <command>` with `shlex.quote` and then escape
the result for the AppleScript literal. That string is run by a shell.

`tests/quoting_probe.py` covers both halves. It pushes a hostile brief through the wire
and asserts the file on disk is byte identical, then takes ten hostile arguments,
including newlines, quotes, backslashes and AppleScript injection bait, generates the
real Terminal.app script, compiles it with `osascript`, and asserts the command comes
back unchanged. Reverting the escaper to a version that does not handle newlines makes
the probe fail, which is the point.

## Environment

| Variable | Default |
|---|---|
| `CC_HANDOFF_CLI` | `claude` |
| `CC_HANDOFF_CONFIG` | `~/.config/cc-handoff/config.toml` |
| `CC_HANDOFF_TERMINAL` | auto-detected |
| `CC_HANDOFF_TIMEOUT` | `600` |
| `CC_HANDOFF_DRY_RUN` | unset; when set, terminal launches return the argv instead of opening a window |

Pointing `CC_HANDOFF_CLI` at another agent CLI mostly works, as long as it accepts
`-p` and `--resume`.

## Tests

```sh
.venv/bin/python tests/run_all.py              # protocol and quoting
.venv/bin/python tests/run_all.py --with-e2e   # adds ask -> handoff, spends real tokens
```

Individually: `stdio_probe.py` does a real MCP handshake over a pipe to a subprocess,
`quoting_probe.py` covers the brief and the AppleScript escaping, and `e2e_probe.py`
runs a headless prompt and hands the session to a terminal. Only the last one costs
anything.

## Relation to other projects

This is not a fork. It shares no code with any other project and was written from
scratch.

The closest existing thing is [steipete/claude-code-mcp](https://github.com/steipete/claude-code-mcp)
(JavaScript, MIT), which wraps the Claude Code CLI in a single `claude_code` tool for
one-shot delegation. If all you want is "let my MCP client run a Claude Code prompt",
use that. It is mature and widely used.

That server is not one-shot: its `claude_code` tool takes a `sessionId`, and repeated
calls with the same id resume the same session. Session continuity is not the
difference. The differences are:

- **Handing a session to a human.** cc-handoff opens the session in a real terminal
  window with its history intact, so you stop being the relay between a chat box and
  your own machine. That is the whole reason this exists.
- **Profile routing.** Work is addressed to a named directory rather than a path
  supplied per call, so "which agent" is a first-class argument and directories not in
  your config cannot be reached at all.
- **Permission default.** `allow_edits` is false unless asked for. That server defaults
  to `bypassPermissions` for backwards compatibility, with a `permissionMode` argument
  to opt out.

It is also Python rather than JavaScript, and macOS only, where that server is
cross-platform. If you want a mature, cross-platform way to run a Claude Code prompt
from an MCP client, use theirs.

## Requirements

macOS, Python 3.10+, `mcp` (2.x or 1.x, the import is version-guarded), and the
`claude` CLI on `PATH`.
