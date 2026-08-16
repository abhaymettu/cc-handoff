from __future__ import annotations

import argparse
import sys

from . import config, terminals


def _setup(args: argparse.Namespace) -> int:
    profiles = config.discover()
    if not profiles:
        print("No directories with a CLAUDE.md found. Nothing to configure.", file=sys.stderr)
        return 1

    print(f"Found {len(profiles)} profile(s):")
    for p in profiles:
        print(f"  {p.name:26} {p.path}")

    default = args.default
    if default and default not in {p.name for p in profiles}:
        print(f"\n--default {default!r} is not among the discovered profiles.", file=sys.stderr)
        return 1

    path = config.write_config(profiles, default)
    print(f"\nWrote {path}")
    print("Prune or rename entries in that file before using it.")

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
    s.add_argument("--no-register", action="store_true", help="write the config only")
    s.set_defaults(func=_setup)

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
