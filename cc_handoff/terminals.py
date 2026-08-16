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

# Verified by hand on macOS 15 / Ghostty 1.x. The rest are written from each
# emulator's documented flags but have not been run; see README.
TESTED = {"ghostty", "terminal"}


class TerminalError(Exception):
    pass


def _osa_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _app_installed(name: str) -> bool:
    if shutil.which(name):
        return True
    app = MAC_APPS.get(name)
    return bool(app and Path(app).is_dir())


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

    for name in ("ghostty", "kitty", "wezterm", "alacritty", "iterm", "terminal"):
        if _app_installed(name):
            return name
    raise TerminalError(
        "no supported terminal found. Set CC_HANDOFF_TERMINAL to one of: "
        + ", ".join(MAC_APPS)
    )


def _argv(name: str, cwd: Path, command: list[str]) -> list[str]:
    d = str(cwd)
    exe = shutil.which(name)

    if name == "ghostty":
        if exe:
            return [exe, f"--working-directory={d}", "-e", *command]
        # Ghostty ships no CLI when installed as a bundle; go through the binary
        # inside the app rather than `open -na`, which drops argv after -e.
        inner = Path(MAC_APPS["ghostty"]) / "Contents" / "MacOS" / "ghostty"
        if inner.is_file():
            return [str(inner), f"--working-directory={d}", "-e", *command]
        raise TerminalError("Ghostty found but no runnable binary inside the bundle.")

    if name == "kitty":
        return [exe or "kitty", "--directory", d, "--", *command]

    if name == "wezterm":
        return [exe or "wezterm", "start", "--cwd", d, "--", *command]

    if name == "alacritty":
        return [exe or "alacritty", "--working-directory", d, "-e", *command]

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
