from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__, config, terminals


def _plan(args: argparse.Namespace) -> dict:
    """Everything setup would do, decided but not yet written."""
    existing: dict[str, config.Profile] = {}
    prev_default = None
    unreadable = None
    if config.CONFIG_PATH.is_file():
        try:
            existing, prev_default = config.load()
        except config.ConfigError as e:
            unreadable = str(e)

    if existing and not args.rescan:
        profiles = sorted(existing.values(), key=lambda p: p.name)
        source, added = "kept from existing config", []
    else:
        found = config.discover(limit=args.limit)
        merged = {p.name: p for p in found}
        merged.update(existing)
        profiles = sorted(merged.values(), key=lambda p: p.name)
        added = [p.name for p in profiles if p.name not in existing]
        source = "discovered" if not existing else "existing plus newly discovered"

    default = args.default or prev_default
    term, term_error = args.terminal, None
    if not term:
        try:
            term = terminals.detect()
        except terminals.TerminalError as e:
            term_error = str(e)

    desktop = config.DESKTOP_CONFIG
    registered = False
    if desktop.is_file():
        try:
            registered = "cc-handoff" in (
                json.loads(desktop.read_text(encoding="utf-8")).get("mcpServers") or {}
            )
        except (OSError, json.JSONDecodeError):
            registered = False

    return {
        "config_path": str(config.CONFIG_PATH),
        "config_exists": config.CONFIG_PATH.is_file(),
        "config_unreadable": unreadable,
        "profile_source": source,
        "profiles": [
            {
                "name": p.name,
                "path": str(p.path),
                "gist": p.gist,
                "exists": p.path.is_dir(),
                "new": p.name in added,
            }
            for p in profiles
        ],
        "default_profile": default,
        "default_valid": (default in {p.name for p in profiles}) if default else None,
        "terminal": term,
        "terminal_tested": term in terminals.TESTED if term else None,
        "terminal_error": term_error,
        "terminals_installed": terminals.installed(),
        "desktop_config": {
            "path": str(desktop),
            "exists": desktop.is_file(),
            "already_registered": registered,
            "will_register": not args.no_register,
            "interpreter": sys.executable,
        },
    }


def _setup(args: argparse.Namespace) -> int:
    plan = _plan(args)

    if args.json:
        plan["dry_run"] = args.dry_run
        print(json.dumps(plan, indent=2))
        return 0 if (plan["profiles"] and not plan["terminal_error"]) else 1

    if plan["config_unreadable"]:
        print(f"Ignoring unreadable config: {plan['config_unreadable']}", file=sys.stderr)
    if not plan["profiles"]:
        print("No directories with a CLAUDE.md found. Nothing to configure.", file=sys.stderr)
        return 1

    print(f"{len(plan['profiles'])} profile(s), {plan['profile_source']}:")
    for p in plan["profiles"]:
        mark = "+" if p["new"] else " "
        missing = "" if p["exists"] else "  [MISSING]"
        print(f"{mark} {p['name']:26} {p['path']}{missing}")
    if plan["profile_source"] == "kept from existing config":
        print("(pass --rescan to look for new ones)")

    if plan["default_profile"] and not plan["default_valid"]:
        print(f"\ndefault_profile {plan['default_profile']!r} is not among the profiles.",
              file=sys.stderr)
        return 1
    if plan["terminal_error"]:
        print(f"\n{plan['terminal_error']}", file=sys.stderr)
        return 1
    if plan["terminal"] not in terminals.MAC_APPS:
        print(f"\nUnknown terminal {plan['terminal']!r}. One of: "
              f"{', '.join(terminals.MAC_APPS)}", file=sys.stderr)
        return 1

    note = "" if plan["terminal_tested"] else "  (untested recipe)"
    print(f"\nTerminal: {plan['terminal']}{note}")
    print(f"Default profile: {plan['default_profile'] or 'none set'}")

    if args.dry_run:
        print(f"\nDry run. Would write {plan['config_path']}")
        if plan["desktop_config"]["will_register"]:
            print(f"Would register cc-handoff in {plan['desktop_config']['path']}")
        return 0

    profiles = [
        config.Profile(p["name"], Path(p["path"]), p["gist"]) for p in plan["profiles"]
    ]
    path = config.write_config(profiles, plan["default_profile"], plan["terminal"])
    print(f"\nWrote {path}")

    if args.no_register:
        print("Skipped Claude Desktop registration (--no-register).")
        return 0

    try:
        target, backup = config.register_desktop()
    except config.ConfigError as e:
        print(f"\nCould not register with Claude Desktop: {e}", file=sys.stderr)
        return 1
    print(f"Registered cc-handoff in {target}")
    if backup:
        print(f"Backed up the previous file to {backup}")
    print("Restart Claude Desktop to pick it up.")
    return 0


def _checks() -> list[dict]:
    out: list[dict] = []

    def add(name: str, ok: bool, detail: str, fatal: bool = True) -> None:
        out.append({"check": name, "ok": ok, "detail": detail, "fatal": fatal})

    add("python", sys.version_info >= (3, 10),
        f"{sys.version.split()[0]} at {sys.executable}")

    try:
        import importlib.metadata as md
        import mcp  # noqa: F401
        add("mcp package", True, f"version {md.version('mcp')}")
    except Exception as e:
        add("mcp package", False, f"{e}. Install with: pip install mcp")

    cli = shutil.which(os.environ.get("CC_HANDOFF_CLI", "claude"))
    if cli:
        try:
            v = subprocess.run([cli, "--version"], capture_output=True, text=True,
                               timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            v = "version unknown"
        add("claude CLI", True, f"{v} at {cli}")
    else:
        add("claude CLI", False, "not on PATH. Set CC_HANDOFF_CLI if it is named differently")

    try:
        profiles, default = config.load()
        add("config", True, f"{len(profiles)} profile(s) in {config.CONFIG_PATH}")
        missing = [p.name for p in profiles.values() if not p.path.is_dir()]
        add("profile paths", not missing,
            "all exist" if not missing else f"missing: {', '.join(missing)}")
        add("default profile", bool(default),
            default or "none set, every call must name a profile", fatal=False)
    except config.ConfigError as e:
        add("config", False, str(e))
        add("profile paths", False, "skipped, no config")
        add("default profile", False, "skipped, no config", fatal=False)

    term = config.preferred_terminal()
    installed = terminals.installed()
    if term:
        add("terminal", term in installed,
            f"{term} pinned in config" + ("" if term in installed else ", but not installed"))
    else:
        try:
            add("terminal", True, f"{terminals.detect()} detected, not pinned in config")
        except terminals.TerminalError as e:
            add("terminal", False, str(e))

    desktop = config.DESKTOP_CONFIG
    if not desktop.is_file():
        add("Claude Desktop", False, f"no config at {desktop}", fatal=False)
    else:
        try:
            entry = (json.loads(desktop.read_text(encoding="utf-8")).get("mcpServers")
                     or {}).get("cc-handoff")
        except (OSError, json.JSONDecodeError) as e:
            entry = None
            add("Claude Desktop", False, f"unreadable: {e}")
        if entry:
            same = Path(entry.get("command", "")) == Path(sys.executable)
            add("Claude Desktop", True,
                "registered" + ("" if same else
                                f", but points at {entry.get('command')} not {sys.executable}"))
        elif desktop.is_file():
            add("Claude Desktop", False, "not registered. Run: cc_handoff setup")
    return out


def _doctor(args: argparse.Namespace) -> int:
    checks = _checks()
    failed = [c for c in checks if not c["ok"] and c["fatal"]]
    if args.json:
        print(json.dumps({"ok": not failed, "version": __version__, "checks": checks}, indent=2))
        return 1 if failed else 0
    for c in checks:
        mark = "ok  " if c["ok"] else ("FAIL" if c["fatal"] else "warn")
        print(f"{mark}  {c['check']:16} {c['detail']}")
    print("\n" + ("Ready." if not failed else f"{len(failed)} problem(s) to fix above."))
    return 1 if failed else 0


def _profiles(args: argparse.Namespace) -> int:
    try:
        profiles, default = config.load()
    except config.ConfigError as e:
        print(e, file=sys.stderr)
        return 1
    for p in sorted(profiles.values(), key=lambda p: p.name):
        mark = "*" if p.name == default else " "
        missing = "" if p.path.is_dir() else "  [MISSING]"
        print(f"{mark} {p.name:26} {p.path}{missing}")
    return 0


def _terminals(args: argparse.Namespace) -> int:
    found = terminals.installed()
    for name in terminals.MAC_APPS:
        state = "installed" if name in found else "-"
        note = "tested" if name in terminals.TESTED else "untested"
        print(f"{name:12} {state:10} {note}")
    try:
        print(f"\nWould use: {terminals.detect()}")
    except terminals.TerminalError as e:
        print(f"\n{e}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cc-handoff")
    sub = parser.add_subparsers(dest="cmd")

    s = sub.add_parser("setup", help="discover profiles and register with Claude Desktop")
    s.add_argument("--default", help="profile to use when none is named")
    s.add_argument("--terminal", help="pin a terminal instead of detecting one")
    s.add_argument("--rescan", action="store_true",
                   help="look for new profiles; never drops ones you kept")
    s.add_argument("--limit", type=int, default=12,
                   help="how many profiles to keep, most-used first (default 12)")
    s.add_argument("--no-register", action="store_true", help="write the config only")
    s.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    s.add_argument("--json", action="store_true", help="emit the plan as JSON")
    s.set_defaults(func=_setup)

    d = sub.add_parser("doctor", help="check whether the install actually works")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=_doctor)

    sub.add_parser("profiles", help="list configured profiles").set_defaults(func=_profiles)
    sub.add_parser("terminals", help="show terminal support on this machine").set_defaults(
        func=_terminals
    )

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        from .server import main as serve

        serve()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
