from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

try:
    from mcp.server import MCPServer as _Server  # mcp >= 2.0
except ImportError:  # pragma: no cover
    from mcp.server.fastmcp import FastMCP as _Server  # mcp 1.x

from . import terminals
from . import __version__
from .config import ConfigError, Profile, load, preferred_terminal, resolve

CLI = os.environ.get("CC_HANDOFF_CLI", "claude")
TIMEOUT = int(os.environ.get("CC_HANDOFF_TIMEOUT", "600"))

server = _Server(
    "cc-handoff",
    version=__version__,
    instructions=(
        "Routes work from this chat into Claude Code. Every tool runs inside a named "
        "profile (a directory with its own CLAUDE.md). Call list_profiles first if the "
        "user has not named one. Use ask_claude_code for work you want an answer to, "
        "and handoff_to_terminal to move that same session onto the user's screen."
    ),
)


def _cli() -> str:
    path = shutil.which(CLI)
    if not path:
        raise RuntimeError(f"{CLI!r} is not on PATH. Set CC_HANDOFF_CLI.")
    return path


def _profile(name: str | None) -> Profile:
    try:
        return resolve(name)
    except ConfigError as e:
        raise RuntimeError(str(e)) from e


def _terminal(explicit: str | None) -> str | None:
    return explicit or preferred_terminal()


@server.tool()
def list_profiles() -> dict:
    """List the profiles work can be routed to. Each is a directory with its own CLAUDE.md."""
    try:
        profiles, default = load()
    except ConfigError as e:
        raise RuntimeError(str(e)) from e
    return {
        "default": default,
        "profiles": [
            {
                "name": p.name,
                "path": str(p.path),
                "gist": p.gist,
                "exists": p.path.is_dir(),
            }
            for p in sorted(profiles.values(), key=lambda p: p.name)
        ],
    }


@server.tool()
def ask_claude_code(
    prompt: str,
    profile: str | None = None,
    allow_edits: bool = False,
) -> dict:
    """Run a prompt through Claude Code headlessly in a profile and return the answer.

    Set allow_edits only when the user has asked for files to be changed. The returned
    session_id can be passed to handoff_to_terminal to continue the same session on screen.
    """
    prof = _profile(profile)
    argv = [_cli(), "-p", prompt, "--output-format", "json"]
    if allow_edits:
        argv += ["--permission-mode", "acceptEdits"]

    try:
        proc = subprocess.run(
            argv,
            cwd=prof.path,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{CLI} timed out after {TIMEOUT}s in profile {prof.name!r}.")

    if proc.returncode != 0:
        raise RuntimeError(
            f"{CLI} exited {proc.returncode} in profile {prof.name!r}: "
            f"{(proc.stderr or proc.stdout or '').strip()[:2000]}"
        )

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {
            "profile": prof.name,
            "cwd": str(prof.path),
            "session_id": None,
            "result": proc.stdout.strip(),
            "allow_edits": allow_edits,
        }

    return {
        "profile": prof.name,
        "cwd": str(prof.path),
        "session_id": data.get("session_id"),
        "result": data.get("result"),
        "is_error": data.get("is_error"),
        "cost_usd": data.get("total_cost_usd"),
        "allow_edits": allow_edits,
    }


@server.tool()
def handoff_to_terminal(
    session_id: str,
    profile: str | None = None,
    terminal: str | None = None,
) -> dict:
    """Reopen a headless session from ask_claude_code in a real terminal window.

    The session keeps its full history, so the user picks up exactly where the
    headless run left off.
    """
    prof = _profile(profile)
    try:
        name, argv = terminals.spawn(
            prof.path, [_cli(), "--resume", session_id], _terminal(terminal)
        )
    except terminals.TerminalError as e:
        raise RuntimeError(str(e)) from e
    return {
        "profile": prof.name,
        "cwd": str(prof.path),
        "terminal": name,
        "session_id": session_id,
        "tested_terminal": name in terminals.TESTED,
        "argv": argv,
    }


@server.tool()
def open_in_claude_code(
    brief: str,
    profile: str | None = None,
    terminal: str | None = None,
    new_window: bool = False,
) -> dict:
    """Write a brief to <profile>/.claude/HANDOFF.md and open Claude Code there.

    Use for work the user should drive themselves. The brief is written verbatim;
    it is never passed through a shell.

    If a session is already open in that profile, no second window is opened. Tell
    the user to switch to it and say "reread HANDOFF.md". Pass new_window to open
    one anyway.
    """
    prof = _profile(profile)
    handoff = prof.path / ".claude" / "HANDOFF.md"
    handoff.parent.mkdir(parents=True, exist_ok=True)
    handoff.write_text(brief, encoding="utf-8")

    if not new_window:
        open_pids = terminals.sessions_in(prof.path, CLI)
        if open_pids:
            return {
                "profile": prof.name,
                "cwd": str(prof.path),
                "handoff_file": str(handoff),
                "bytes_written": len(brief.encode("utf-8")),
                "opened_window": False,
                "existing_sessions": open_pids,
                "next_step": (
                    f"A Claude Code session is already open in {prof.name!r}. "
                    "Tell the user to switch to that window and say "
                    "'reread .claude/HANDOFF.md' rather than opening another one."
                ),
            }

    kickoff = (
        f"Read {handoff.relative_to(prof.path)} and carry out what it asks. "
        "It was written by a Claude Desktop chat handing this work to you."
    )
    try:
        name, argv = terminals.spawn(prof.path, [_cli(), kickoff], _terminal(terminal))
    except terminals.TerminalError as e:
        raise RuntimeError(f"wrote {handoff}, but could not open a terminal: {e}") from e

    return {
        "profile": prof.name,
        "cwd": str(prof.path),
        "handoff_file": str(handoff),
        "bytes_written": len(brief.encode("utf-8")),
        "opened_window": True,
        "terminal": name,
        "tested_terminal": name in terminals.TESTED,
    }


def main() -> None:
    server.run("stdio")
