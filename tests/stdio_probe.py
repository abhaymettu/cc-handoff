"""Speak MCP over a real pipe to a real subprocess. No in-process shortcuts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXPECTED = {"list_profiles", "ask_claude_code", "handoff_to_terminal", "open_in_claude_code"}


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, "-m", "cc_handoff"],
        cwd=REPO,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    def send(obj: dict) -> None:
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def read() -> dict:
        while True:
            line = proc.stdout.readline()
            if not line:
                raise SystemExit(f"server closed stdout. stderr:\n{proc.stderr.read()}")
            line = line.strip()
            if line:
                return json.loads(line)

    send({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "stdio-probe", "version": "0"},
        },
    })
    init = read()
    print("initialize ->", json.dumps(init["result"]["serverInfo"]))
    print("protocolVersion ->", init["result"]["protocolVersion"])

    send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tools = read()["result"]["tools"]

    names = {t["name"] for t in tools}
    print(f"\ntools/list -> {len(tools)} tools")
    for t in sorted(tools, key=lambda t: t["name"]):
        props = t["inputSchema"].get("properties", {})
        required = t["inputSchema"].get("required", [])
        args = ", ".join(
            f"{k}{'' if k in required else '?'}:{v.get('type', v.get('anyOf', '?'))}"
            for k, v in props.items()
        )
        print(f"  {t['name']}({args})")

    proc.stdin.close()
    proc.wait(timeout=10)

    missing, extra = EXPECTED - names, names - EXPECTED
    if missing or extra:
        print(f"\nFAIL missing={sorted(missing)} unexpected={sorted(extra)}")
        return 1
    print("\nPASS all four tools present with schemas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
