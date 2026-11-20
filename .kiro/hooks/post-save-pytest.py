#!/usr/bin/env python3
"""post-save-pytest.py — run the pytest suite when a Python file under src/ is saved.

This script is called by Kiro as a postToolUse hook on fs_write.  It reads
the hook event JSON from stdin, checks whether the written path is under
src/, and if so runs pytest.

Exit codes:
  0 — Hook ran successfully (output added to agent context).
  Other — Hook failed; stderr shown as a warning to the user.

Usage in .kiro/agents/<agent>.json:
  "postToolUse": [
    {
      "matcher": "fs_write",
      "command": "python .kiro/hooks/post-save-pytest.py"
    }
  ]
"""

from __future__ import annotations

import json
import subprocess
import sys


def main() -> int:
    # Read the hook event from stdin
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("Warning: could not parse hook event JSON", file=sys.stderr)
        return 1

    # Determine the path(s) written.  The fs_write tool_input contains
    # an "operations" list, each with a "path" key.
    tool_input = event.get("tool_input", {})
    operations = tool_input.get("operations", [])
    written_paths = [op.get("path", "") for op in operations if op.get("path")]

    # Only run pytest if at least one .py file under src/ was written
    relevant = [
        p for p in written_paths
        if p.endswith(".py") and ("src/" in p.replace("\\", "/") or "src\\" in p)
    ]
    if not relevant:
        return 0

    print(f"Night Shift: Python file(s) under src/ saved — running pytest...")
    result = subprocess.run(
        ["python", "-m", "pytest", "--tb=short", "-q"],
        capture_output=True,
        text=True,
    )
    combined = result.stdout + ("\n" + result.stderr if result.stderr else "")
    # Print last 60 lines so the agent sees the summary without being overwhelmed
    lines = combined.strip().splitlines()
    print("\n".join(lines[-60:]))
    return 0  # Always exit 0 — the agent reads pytest output from stdout


if __name__ == "__main__":
    sys.exit(main())
