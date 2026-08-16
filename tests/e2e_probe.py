"""ask_claude_code -> handoff_to_terminal, through the wire, in a throwaway profile.

Spends real tokens: it invokes the claude CLI twice.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SECRET = "8471"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="cc-handoff-e2e-"))
    profile_dir = tmp / "throwaway repo"
    profile_dir.mkdir()
    (profile_dir / "CLAUDE.md").write_text("Throwaway profile for the end-to-end test.\n")
    subprocess.run(["git", "init", "-q"], cwd=profile_dir, check=True)

    cfg = tmp / "config.toml"
    cfg.write_text(
        'default_profile = "throwaway"\n\n[profiles]\n'
        f"throwaway = {json.dumps(str(profile_dir))}\n"
    )

    env = {**os.environ, "CC_HANDOFF_CONFIG": str(cfg), "CC_HANDOFF_TERMINAL": "ghostty", "CC_HANDOFF_DRY_RUN": "1"}
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

    def call(name, args, rid):
        send({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
              "params": {"name": name, "arguments": args}})
        r = read()
        if "error" in r:
            raise SystemExit(f"{name} failed: {json.dumps(r['error'])[:800]}")
        sc = r["result"].get("structuredContent")
        if sc is None:
            sc = json.loads(r["result"]["content"][0]["text"])
        return sc

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                     "clientInfo": {"name": "e2e-probe", "version": "0"}}})
    read()
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    print("list_profiles ->", json.dumps(call("list_profiles", {}, 2))[:200])

    ask = call("ask_claude_code",
               {"prompt": f"Remember the number {SECRET}. What is 2+2?"}, 3)
    print("\nask_claude_code ->")
    print("  profile   :", ask["profile"])
    print("  session_id:", ask["session_id"])
    print("  result    :", repr(ask["result"])[:200])

    if not ask["session_id"]:
        print("FAIL no session_id returned")
        return 1

    hand = call("handoff_to_terminal", {"session_id": ask["session_id"]}, 4)
    print("\nhandoff_to_terminal ->")
    print("  terminal:", hand["terminal"], "(tested)" if hand["tested_terminal"] else "(UNTESTED)")
    print("  argv    :", hand["argv"])

    proc.stdin.close()
    proc.wait(timeout=10)

    if "--resume" not in hand["argv"] or ask["session_id"] not in hand["argv"]:
        print("FAIL --resume/session_id missing from spawn argv")
        return 1
    if str(profile_dir) not in " ".join(hand["argv"]) and hand["cwd"] != str(profile_dir):
        print("FAIL terminal did not target the profile directory")
        return 1

    print(f"\nPASS session {ask['session_id']} handed to {hand['terminal']} via --resume")
    print(f"A window should be open in: {profile_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
