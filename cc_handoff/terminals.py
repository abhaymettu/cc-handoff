from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

MAC_APPS = {
    "ghostty": "/Applications/Ghostty.app",
    "kitty": "/Applications/kitty.app",
    "wezterm": "/Applications/WezTerm.app",
    "alacritty": "/Applications/Alacritty.app",
    "iterm": "/Applications/iTerm.app",
    "terminal": "/System/Applications/Utilities/Terminal.app",
}

# Executable inside each .app bundle, for the emulators that do not put a CLI on
# PATH unless the user symlinks one by hand. iTerm and Terminal need no binary:
# they are driven through AppleScript.
BUNDLE_BIN = {
    "ghostty": "Contents/MacOS/ghostty",
    "kitty": "Contents/MacOS/kitty",
    "wezterm": "Contents/MacOS/wezterm",
    "alacritty": "Contents/MacOS/alacritty",
}

APPLESCRIPT = {"iterm", "terminal"}

# Verified by hand on macOS 15 / Ghostty 1.x. The rest are written from each
# emulator's documented flags but have not been run; see README.
TESTED = {"ghostty", "terminal"}


class TerminalError(Exception):
    pass


def _osa_quote(s: str) -> str:
    """Quote for an AppleScript string literal. A raw newline is a syntax error."""
    out = (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return '"' + out + '"'


def launcher(name: str) -> str | None:
    """The executable that can actually start `name`, or None if there isn't one.

    An .app bundle on disk is not enough: kitty, WezTerm and Alacritty ship their
    CLI inside the bundle and do not put it on PATH.
    """
    if name in APPLESCRIPT:
        app = MAC_APPS.get(name)
        return "osascript" if app and Path(app).is_dir() else None
    exe = shutil.which(name)
    if exe:
        return exe
    app, rel = MAC_APPS.get(name), BUNDLE_BIN.get(name)
    if app and rel:
        inner = Path(app) / rel
        if inner.is_file():
            return str(inner)
    return None


def _app_installed(name: str) -> bool:
    return launcher(name) is not None


def installed() -> list[str]:
    return [n for n in MAC_APPS if _app_installed(n)]


def detect() -> str:
    """$CC_HANDOFF_TERMINAL, then whatever is running, then whatever is installed."""
    forced = os.environ.get("CC_HANDOFF_TERMINAL")
    if forced:
        if forced not in MAC_APPS:
            raise TerminalError(
                f"CC_HANDOFF_TERMINAL={forced!r} is not one of: {', '.join(MAC_APPS)}"
            )
        return forced

    running = (os.environ.get("TERM_PROGRAM") or "").lower()
    for name, needle in (
        ("ghostty", "ghostty"), ("iterm", "iterm"), ("wezterm", "wezterm"),
        ("kitty", "kitty"), ("alacritty", "alacritty"), ("terminal", "apple_terminal"),
    ):
        if needle in running and _app_installed(name):
            return name

    # Tested recipes first. Never auto-select an untested one over a working one.
    for name in ("ghostty", "terminal", "iterm", "kitty", "wezterm", "alacritty"):
        if _app_installed(name):
            return name
    raise TerminalError(
        "no supported terminal found. Set CC_HANDOFF_TERMINAL to one of: "
        + ", ".join(MAC_APPS)
    )


def sessions_in(cwd: Path, cli: str = "claude") -> list[int]:
    """PIDs of agent sessions already running with `cwd` as their working directory."""
    try:
        pids = subprocess.run(
            ["pgrep", "-x", Path(cli).name],
            capture_output=True, text=True, timeout=5,
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return []
    if not pids:
        return []

    try:
        out = subprocess.run(
            ["lsof", "-a", "-d", "cwd", "-Fpn", "-p", ",".join(pids)],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []

    target, found, pid = str(cwd.resolve()), [], None
    for line in out.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None and line[1:] == target:
            found.append(pid)
    return found


def _argv(name: str, cwd: Path, command: list[str]) -> list[str]:
    d = str(cwd)
    exe = launcher(name)
    if exe is None:
        raise TerminalError(
            f"{name} has no launchable binary. The .app may be present but its CLI is "
            f"not on PATH and not at {MAC_APPS.get(name)}/{BUNDLE_BIN.get(name, '')}."
        )

    if name == "ghostty":
        # Ghostty's own help: "On macOS, launching the terminal emulator from the
        # CLI is not supported ... use open -na Ghostty.app". Running the bundle
        # binary directly starts a whole new instance per call, which restores
        # every saved tab and re-triggers macOS exec prompts.
        # --window-save-state=never keeps a fresh window fresh.
        return [
            "open", "-na", MAC_APPS["ghostty"], "--args",
            "--window-save-state=never", f"--working-directory={d}", "-e", *command,
        ]

    if name == "kitty":
        return [exe, "--directory", d, "--", *command]

    if name == "wezterm":
        return [exe, "start", "--cwd", d, "--", *command]

    if name == "alacritty":
        return [exe, "--working-directory", d, "-e", *command]

    if name in ("iterm", "terminal"):
        # Both only take a shell string via AppleScript, so this is the one path
        # where quoting matters. shlex.quote every element, then escape for osascript.
        line = f"cd {shlex.quote(d)} && {shlex.join(command)}"
        app = "iTerm" if name == "iterm" else "Terminal"
        script = (
            f'tell application {_osa_quote(app)}\n'
            f"  activate\n"
            f"  do script {_osa_quote(line)}\n"
            f"end tell"
        )
        return ["osascript", "-e", script]

    raise TerminalError(f"unknown terminal {name!r}")


def spawn(cwd: Path, command: list[str], terminal: str | None = None) -> tuple[str, list[str]]:
    """Open a window in `cwd` running `command`. Returns (terminal, argv)."""
    if sys.platform != "darwin":
        raise TerminalError("only macOS is supported today; PRs welcome.")
    name = terminal or detect()
    if name not in MAC_APPS:
        raise TerminalError(f"unknown terminal {name!r}. One of: {', '.join(MAC_APPS)}")
    if not _app_installed(name):
        raise TerminalError(f"{name} is not installed. Installed: {', '.join(installed()) or 'none'}")

    argv = _argv(name, cwd, command)
    if os.environ.get("CC_HANDOFF_DRY_RUN"):
        return name, argv
    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as e:
        raise TerminalError(f"could not launch {name}: {e}") from e
    return name, argv
