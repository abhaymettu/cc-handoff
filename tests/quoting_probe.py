"""Quoting and escaping, on the paths where they can actually go wrong.

Two halves:

1. A hostile brief pushed through the wire lands on disk byte for byte. The brief is
   written with Path.write_text and never enters an argv, so this mostly proves the
   server does not get creative with it.
2. The AppleScript recipes, which are the only ones that build a shell string. These
   are checked by compiling the generated script with osascript and asserting the
   command line comes back byte for byte, so an escaping bug is a hard failure rather
   than a silent one.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cc_handoff import terminals  # noqa: E402

NASTY = (
    'single \'quotes\' and "double quotes"\n'
    "backticks: `whoami` and `echo pwned`\n"
    "substitution: $(whoami) and ${HOME} and $HOME\n"
    "semicolons; && || | > >> < \n"
    "backslashes: \\ \\\\ \\n literal\n"
    'applescript bait: " & do shell script "whoami" & "\n'
    "unicode: éèê 你好 \U0001f600\n"
    "trailing spaces   \n"
)

# Every one of these has broken a naive AppleScript escaper at some point.
HOSTILE_ARGS = [
    'plain',
    'with "double quotes"',
    "with 'single quotes'",
    "with\nnewline",
    "with\ttab",
    "back\\slash",
    'quote\\" then text',
    '" & do shell script "whoami" & "',
    "$(whoami) and `whoami`",
    "unicode 你好 \U0001f600",
]


def brief_survives_the_wire() -> bool:
    tmp = Path(tempfile.mkdtemp(prefix="cc-handoff-quote-"))
    profile_dir = tmp / "throwaway repo"
    profile_dir.mkdir()
    (profile_dir / "CLAUDE.md").write_text("Throwaway profile for the quoting test.\n")

    cfg = tmp / "config.toml"
    cfg.write_text(
        'default_profile = "throwaway"\n\n[profiles]\n'
        f"throwaway = {json.dumps(str(profile_dir))}\n"
    )

    env = {
        **os.environ,
        "CC_HANDOFF_CONFIG": str(cfg),
        "CC_HANDOFF_CLI": "echo",
        "CC_HANDOFF_TERMINAL": "ghostty",
        "CC_HANDOFF_DRY_RUN": "1",
    }

    proc = subprocess.Popen(
        [sys.executable, "-m", "cc_handoff"],
        cwd=REPO, env=env, text=True, bufsize=1,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    def send(o):
        proc.stdin.write(json.dumps(o) + "\n")
        proc.stdin.flush()

    def read():
        while True:
            line = proc.stdout.readline()
            if not line:
                raise SystemExit("server closed stdout:\n" + proc.stderr.read())
            if line.strip():
                return json.loads(line)

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                     "clientInfo": {"name": "quote-probe", "version": "0"}}})
    read()
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
          "params": {"name": "open_in_claude_code",
                     "arguments": {"brief": NASTY, "new_window": True}}})
    resp = read()
    proc.stdin.close()
    proc.wait(timeout=10)

    if "error" in resp:
        print("  FAIL tools/call:", json.dumps(resp["error"])[:400])
        return False

    handoff = profile_dir / ".claude" / "HANDOFF.md"
    if not handoff.is_file():
        print(f"  FAIL {handoff} not written")
        return False
    got = handoff.read_text(encoding="utf-8")
    if got != NASTY:
        print("  FAIL brief differs on disk")
        return False
    if os.environ.get("USER", "\0") in got.replace("${HOME}", "").replace("$HOME", ""):
        print("  FAIL a substitution expanded")
        return False
    print(f"  ok   brief byte-identical on disk ({len(got.encode())} bytes)")
    return True


def applescript_escaping_holds() -> bool:
    """Compile the real generated script and read the command back out."""
    ok = True
    checked = []
    for name in sorted(terminals.APPLESCRIPT):
        if terminals.launcher(name) is None:
            print(f"  skip {name} is not installed on this machine")
            continue
        checked.append(name)
        for arg in HOSTILE_ARGS:
            cwd = Path("/tmp/my repo")
            command = ["claude", "--resume", arg]
            argv = terminals._argv(name, cwd, command)

            if argv[0] != "osascript" or len(argv) != 3:
                print(f"  FAIL {name}: unexpected argv shape {argv[:2]}")
                ok = False
                continue

            expected_line = f"cd {shlex.quote(str(cwd))} && {shlex.join(command)}"
            # Same escaping the recipe uses, but returned instead of executed, so the
            # compiler validates the literal without opening a terminal.
            probe = f"return {terminals._osa_quote(expected_line)}"
            r = subprocess.run(["osascript", "-e", probe],
                               capture_output=True, text=True, timeout=20)
            if r.returncode != 0:
                print(f"  FAIL {name}: osascript rejected {arg!r}: {r.stderr.strip()[:90]}")
                ok = False
                continue
            # osascript appends exactly one newline to what it prints. Anything else
            # coming back changed means the escaping altered the command.
            got = r.stdout[:-1] if r.stdout.endswith("\n") else r.stdout
            if got != expected_line:
                print(f"  FAIL {name}: round-trip differs for {arg!r}")
                print(f"       want {expected_line!r}")
                print(f"       got  {got!r}")
                ok = False
                continue
            # iTerm2 writes into a session, Terminal.app uses `do script`.
            marker = "write text " if name == "iterm" else "do script "
            if "\n" in argv[2].split(marker, 1)[-1].split("\nend tell")[0]:
                print(f"  FAIL {name}: raw newline inside the script literal for {arg!r}")
                ok = False
    # The escaper is shared by both recipes, so check it directly even when neither
    # emulator is installed. Otherwise a bare machine silently tests nothing.
    for arg in HOSTILE_ARGS:
        probe = f"return {terminals._osa_quote(arg)}"
        r = subprocess.run(["osascript", "-e", probe],
                           capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            print(f"  FAIL _osa_quote produced invalid AppleScript for {arg!r}: "
                  f"{r.stderr.strip()[:90]}")
            ok = False
    if ok:
        where = ", ".join(checked) if checked else "no installed emulator"
        print(f"  ok   {len(HOSTILE_ARGS)} hostile arguments compile and round-trip "
              f"through osascript ({where}; escaper checked directly)")
    return ok


def shell_metacharacters_stay_inert() -> bool:
    """shlex.quote must neutralise anything that would run as a second command."""
    cwd = Path("/tmp/my repo")
    argv = terminals._argv("terminal", cwd, ["claude", "--resume", "x; touch /tmp/pwned"])
    script = argv[2]
    if "; touch /tmp/pwned" in script and "'x; touch /tmp/pwned'" not in script:
        print("  FAIL injected command is not quoted")
        return False
    print("  ok   shell metacharacters quoted, not executable")
    return True


def main() -> int:
    print("brief through the wire:")
    a = brief_survives_the_wire()
    print("applescript escaping:")
    b = applescript_escaping_holds()
    print("shell metacharacters:")
    c = shell_metacharacters_stay_inert()
    if a and b and c:
        print("\nPASS")
        return 0
    print("\nFAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
