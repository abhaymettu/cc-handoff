"""Run the probes. The end-to-end one spends real tokens, so it is opt in.

    python tests/run_all.py              # protocol and quoting
    python tests/run_all.py --with-e2e   # adds ask -> handoff, calls the claude CLI
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

FREE = [
    ("protocol", "stdio_probe.py", "MCP handshake over a real pipe"),
    ("quoting", "quoting_probe.py", "brief on disk, AppleScript escaping"),
]
PAID = [("end to end", "e2e_probe.py", "ask then hand off; spends tokens")]


def main() -> int:
    cases = FREE + (PAID if "--with-e2e" in sys.argv else [])
    if "--with-e2e" not in sys.argv:
        print("(skipping e2e_probe.py, pass --with-e2e to include it)\n")

    results = []
    for label, script, blurb in cases:
        print(f"### {label}: {blurb}")
        r = subprocess.run([sys.executable, str(HERE / script)])
        results.append((label, r.returncode))
        print()

    failed = [label for label, code in results if code != 0]
    for label, code in results:
        print(f"{'PASS' if code == 0 else 'FAIL'}  {label}")
    if failed:
        print(f"\n{len(failed)} failed: {', '.join(failed)}")
        return 1
    print(f"\nAll {len(results)} passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
