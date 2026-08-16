"""Push a hostile brief through the wire and confirm it lands on disk byte-for-byte.

CC_HANDOFF_CLI=echo so nothing real is launched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

NASTY = (
    'single \'quotes\' and "double quotes"\n'
    "backticks: `whoami` and `echo pwned`\n"
    "substitution: $(whoami) and ${HOME} and $HOME\n"
    "semicolons; && || | > >> < \n"
    "backslashes: \\ \\\\ \\n literal\n"
    "applescript bait: \" & do shell script \"whoami\" & \"\n"
    "unicode: éèê 你好 \U0001f600\n"
    "trailing spaces   \n"
)


def main() -> int:
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
          "params": {"name": "open_in_claude_code", "arguments": {"brief": NASTY}}})
    resp = read()

    proc.stdin.close()
    proc.wait(timeout=10)

    if "error" in resp:
        print("tools/call error:", json.dumps(resp["error"])[:600])
        return 1

    handoff = profile_dir / ".claude" / "HANDOFF.md"
    if not handoff.is_file():
        print(f"FAIL {handoff} was not written")
        return 1

    got = handoff.read_text(encoding="utf-8")
    print(f"wrote {handoff}")
    print(f"expected {len(NASTY.encode())} bytes, got {len(got.encode())} bytes")

    if got != NASTY:
        print("FAIL content differs")
        for i, (a, b) in enumerate(zip(NASTY, got)):
            if a != b:
                print(f"  first diff at {i}: {a!r} != {b!r}")
                break
        return 1

    if os.environ.get("USER", "\0") in got.replace("${HOME}", "").replace("$HOME", ""):
        print("FAIL a substitution appears to have been expanded")
        return 1

    print("PASS HANDOFF.md is byte-identical; no substitution ran")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
