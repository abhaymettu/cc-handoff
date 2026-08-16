# cc-handoff

An MCP server that routes work from a Claude Desktop chat into Claude Code — either
headlessly, or by opening a terminal you can take over.

The point is the handoff. You ask a question in chat, it runs headlessly in the right
directory, and when you want to drive it yourself the *same session* opens in a real
terminal with its history intact.

## Profiles

A profile is a directory containing a `CLAUDE.md`. That is the whole definition. Each
one has its own instructions and its own folder-scoped memory, so "which profile" is
really "which agent".

Every tool runs inside a named profile. There is no free-form path parameter — a
directory that is not in your config cannot be touched.

## Install

```sh
git clone https://github.com/abhaymettu/cc-handoff
cd cc-handoff
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m cc_handoff setup --default scratch
```

`setup` walks a few roots for `CLAUDE.md` files, writes `~/.config/cc-handoff/config.toml`,
and registers itself in `claude_desktop_config.json` (backing up whatever was there).
Restart Claude Desktop afterward.

It over-collects on purpose. Open the toml and delete what you do not want:

```toml
default_profile = "scratch"

[profiles]
brain   = "/Users/you/Documents/Brain"
scratch = "/Users/you/scratch"
```

Other commands: `cc_handoff profiles`, `cc_handoff terminals`.

## Tools

| Tool | What it does |
|---|---|
| `list_profiles()` | Names, paths, and a one-line gist from each `CLAUDE.md` |
| `ask_claude_code(prompt, profile, allow_edits=False)` | Headless `claude -p`; returns the answer and a `session_id` |
| `handoff_to_terminal(session_id, profile, terminal)` | Reopens that session in a terminal via `--resume` |
| `open_in_claude_code(brief, profile, terminal)` | Writes `<profile>/.claude/HANDOFF.md`, opens a terminal there |

`allow_edits` defaults to false and must be set deliberately.

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

Selection order: `$CC_HANDOFF_TERMINAL`, then whatever is running (`TERM_PROGRAM`), then
whatever is installed. macOS only for now.

Ghostty is launched through `Ghostty.app/Contents/MacOS/ghostty` rather than `open -na`,
because `open -na` discards argv after `-e`.

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

## Requirements

macOS, Python 3.10+, `mcp` (2.x or 1.x — the import is version-guarded), and the
`claude` CLI on `PATH`.
