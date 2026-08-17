from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

HOME = Path.home()

CONFIG_PATH = Path(
    os.environ.get("CC_HANDOFF_CONFIG", HOME / ".config" / "cc-handoff" / "config.toml")
).expanduser()

DESKTOP_CONFIG = (
    HOME / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
)

SCAN_ROOTS = [
    HOME,
    HOME / "code",
    HOME / "Desktop",
    HOME / "Documents",
    HOME / "Projects",
    HOME / "src",
    # iCloud Drive: Obsidian vaults and similar live here, and the generic
    # Library skip below would otherwise hide them.
    HOME / "Library" / "Mobile Documents",
]

SCAN_DEPTH = 3

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "env", ".env", "dist", "build", "target", ".next", ".nuxt", ".cache",
    "Library", "Applications", ".Trash", "site-packages", ".tox", ".mypy_cache",
    ".pytest_cache", "vendor", "Pods", ".gradle", ".terraform", "Downloads",
    "Movies", "Music", "Pictures", "Public",
}

MARKER = "CLAUDE.md"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Profile:
    name: str
    path: Path
    gist: str = ""


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "profile"


def _gist(claude_md: Path, limit: int = 120) -> str:
    try:
        text = claude_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "<!--", "---", "```")):
            continue
        if len(line) > limit:
            line = line[: limit - 1].rstrip() + "…"
        return line
    return ""


def _walk(root: Path, depth: int):
    if not root.is_dir():
        return
    stack = [(root, 0)]
    while stack:
        d, level = stack.pop()
        try:
            entries = list(d.iterdir())
        except (OSError, PermissionError):
            continue
        if any(e.name == MARKER and e.is_file() for e in entries):
            yield d
        if level >= depth:
            continue
        for e in entries:
            if (
                e.is_dir()
                and not e.is_symlink()
                and not e.name.startswith(".")
                and e.name not in SKIP_DIRS
            ):
                stack.append((e, level + 1))


CLAUDE_JSON = HOME / ".claude.json"

_TEMP_HINTS = ("/private/tmp/", "/var/folders/", "/tmp/", "/.claude/worktrees/")

_SHELL_RC = [
    HOME / ".zshrc", HOME / ".bashrc", HOME / ".bash_profile",
    HOME / ".profile", HOME / ".config" / "zsh" / ".zshrc",
]

_PROFILE_ARRAY = re.compile(r"CLAUDE_PROFILES\s*=\s*\((.*?)\)", re.DOTALL)
_PAIR = re.compile(r"""(\w[\w-]*)\s+["']?([^"'\s][^"'\n]*?)["']?\s*(?=\n|$)""")


def from_shell() -> dict[str, Path]:
    """Names the user already picked, if they keep a CLAUDE_PROFILES map in a shell rc."""
    out: dict[str, Path] = {}
    for rc in _SHELL_RC:
        try:
            text = rc.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = _PROFILE_ARRAY.search(text)
        if not m:
            continue
        for name, raw in _PAIR.findall(m.group(1)):
            p = Path(os.path.expandvars(raw.strip())).expanduser()
            if p.is_dir():
                out.setdefault(name, p)
    return out


def from_usage() -> dict[Path, float]:
    """Directories the user actually runs Claude Code in, keyed to when they last did."""
    try:
        data = json.loads(CLAUDE_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[Path, float] = {}
    for raw, meta in (data.get("projects") or {}).items():
        if any(h in raw.rstrip("/") + "/" for h in _TEMP_HINTS):
            continue
        p = Path(raw)
        if p == HOME or not p.is_dir():
            continue
        out[p] = float((meta or {}).get("lastStartTime") or 0)
    return out


def discover(roots: list[Path] | None = None, depth: int = SCAN_DEPTH,
             limit: int | None = None) -> list[Profile]:
    """Find the user's agents however they happen to organise them.

    Three layers, most personal first. A CLAUDE_PROFILES map in a shell rc gives names
    they chose themselves. ~/.claude.json says which directories they actually work in,
    and when. A filesystem scan catches whatever is left. A profile is still a directory
    with its own CLAUDE.md; these layers decide which ones matter and what to call them.
    """
    named = from_shell()
    used = from_usage()

    ranked: dict[Path, float] = {}
    for p in named.values():
        if (p / MARKER).is_file():
            ranked[p] = used.get(p, 0.0) + 1e15  # a name they chose outranks everything
    for p, when in used.items():
        if (p / MARKER).is_file():
            ranked.setdefault(p, when)
    for root in roots if roots is not None else SCAN_ROOTS:
        for d in _walk(root.expanduser(), depth):
            ranked.setdefault(d, used.get(d, 0.0))

    preferred = {v: k for k, v in named.items()}
    ordered = sorted(ranked, key=lambda p: (-ranked[p], str(p)))
    if limit:
        ordered = ordered[:limit]

    by_name: dict[str, Profile] = {}
    for path in ordered:
        name = preferred.get(path) or _slug(path.name)
        if name in by_name:
            name = _slug(f"{path.parent.name}-{name}")
            n = 2
            while name in by_name:
                name, n = f"{_slug(path.name)}-{n}", n + 1
        by_name[name] = Profile(name, path, _gist(path / MARKER))
    return sorted(by_name.values(), key=lambda p: p.name)


def render_config(profiles: list[Profile], default: str | None = None,
                  terminal: str | None = None) -> str:
    lines = ["# cc-handoff. Each profile is a directory with its own CLAUDE.md.", ""]
    if default:
        lines.append(f"default_profile = {json.dumps(default)}")
    if terminal:
        lines.append(f"terminal = {json.dumps(terminal)}  # detected at setup")
    if default or terminal:
        lines.append("")
    lines.append("[profiles]")
    for p in profiles:
        suffix = f"  # {p.gist}" if p.gist else ""
        lines.append(f"{p.name} = {json.dumps(str(p.path))}{suffix}")
    return "\n".join(lines) + "\n"


def write_config(profiles: list[Profile], default: str | None = None,
                 terminal: str | None = None, path: Path = CONFIG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_config(profiles, default, terminal), encoding="utf-8")
    return path


def preferred_terminal(path: Path = CONFIG_PATH) -> str | None:
    """The terminal pinned at setup, if any. $CC_HANDOFF_TERMINAL still wins."""
    if not path.is_file():
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8")).get("terminal")
    except (OSError, tomllib.TOMLDecodeError):
        return None


def load(path: Path = CONFIG_PATH) -> tuple[dict[str, Profile], str | None]:
    if not path.is_file():
        raise ConfigError(
            f"no config at {path}. Run: python -m cc_handoff setup"
        )
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} is not valid TOML: {e}") from e

    raw = data.get("profiles") or {}
    if not isinstance(raw, dict) or not raw:
        raise ConfigError(f"{path} has no [profiles] entries.")

    profiles: dict[str, Profile] = {}
    for name, value in raw.items():
        p = Path(str(value)).expanduser()
        profiles[name] = Profile(name, p, _gist(p / MARKER) if p.is_dir() else "")

    default = data.get("default_profile")
    if default is not None and default not in profiles:
        raise ConfigError(
            f"default_profile {default!r} is not in [profiles]: {', '.join(sorted(profiles))}"
        )
    return profiles, default


def resolve(name: str | None, path: Path = CONFIG_PATH) -> Profile:
    """Turn a requested profile name into a real directory, or refuse."""
    profiles, default = load(path)
    chosen = name or default
    if not chosen:
        raise ConfigError(
            "profile is required (no default_profile set). Choose one of: "
            + ", ".join(sorted(profiles))
        )
    if chosen not in profiles:
        raise ConfigError(
            f"unknown profile {chosen!r}. Choose one of: " + ", ".join(sorted(profiles))
        )
    prof = profiles[chosen]
    if not prof.path.is_dir():
        raise ConfigError(f"profile {chosen!r} points at {prof.path}, which is not a directory.")
    return prof


def register_desktop(python: Path | None = None, path: Path = DESKTOP_CONFIG) -> tuple[Path, Path | None]:
    """Add cc-handoff to claude_desktop_config.json, backing up whatever is there."""
    python = Path(python or sys.executable)
    data: dict = {}
    backup: Path | None = None

    if path.is_file():
        backup = path.with_suffix(path.suffix + ".cc-handoff.bak")
        shutil.copy2(path, backup)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ConfigError(f"{path} is not valid JSON ({e}); left it alone.") from e
        if not isinstance(data, dict):
            raise ConfigError(f"{path} is not a JSON object; left it alone.")

    servers = data.setdefault("mcpServers", {})
    servers["cc-handoff"] = {"command": str(python), "args": ["-m", "cc_handoff"]}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path, backup
