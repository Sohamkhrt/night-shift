#!/usr/bin/env python3
"""post-save-spec-reminder.py — remind to update tasks.md when a spec file changes.

Called by Kiro as a postToolUse hook on fs_write.  When the written file is
under .kiro/specs/, it prints a reminder to update tasks.md so it stays in
sync with the requirements/design documents.

Exit codes:
  0 — Hook ran successfully (reminder added to agent context).
  Other — Hook failed; stderr shown as a warning to the user.

Usage in .kiro/agents/<agent>.json:
  "postToolUse": [
    {
      "matcher": "fs_write",
      "command": "python .kiro/hooks/post-save-spec-reminder.py"
    }
  ]
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    # Read the hook event from stdin
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("Warning: could not parse hook event JSON", file=sys.stderr)
        return 1

    tool_input = event.get("tool_input", {})
    operations = tool_input.get("operations", [])
    written_paths = [op.get("path", "") for op in operations if op.get("path")]

    # Normalize separators for cross-platform matching
    spec_paths = [
        p for p in written_paths
        if ".kiro/specs" in p.replace("\\", "/") or ".kiro\\specs" in p
    ]
    if not spec_paths:
        return 0

    for path in spec_paths:
        print(
            f"📋 Spec file changed: {path}\n"
            f"   Remember to update .kiro/specs/night-shift-core/tasks.md if any\n"
            f"   requirements, design decisions, or task status have changed."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
