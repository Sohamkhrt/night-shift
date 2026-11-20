#!/usr/bin/env python3
"""post-save-diary-render.py — verify diary.html.j2 still renders when edited.

Called by Kiro as a postToolUse hook on fs_write.  When the written file is
templates/diary.html.j2, it does a quick Jinja2 render with minimal fixture
data to confirm the template is syntactically valid.

Exit codes:
  0 — Hook ran successfully; render check passed (or skipped for unrelated files).
  Other — Hook failed; stderr shown as a warning to the user.

Usage in .kiro/agents/<agent>.json:
  "postToolUse": [
    {
      "matcher": "fs_write",
      "command": "python .kiro/hooks/post-save-diary-render.py"
    }
  ]
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path


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

    # Only run when the diary template itself was saved
    diary_paths = [
        p for p in written_paths
        if "diary.html.j2" in p
    ]
    if not diary_paths:
        return 0

    try:
        from jinja2 import Environment, FileSystemLoader, TemplateError

        template_path = Path(diary_paths[0])
        env = Environment(loader=FileSystemLoader(str(template_path.parent)))
        template = env.get_template(template_path.name)

        # Render with minimal fixture data that exercises every block
        fixture = {
            "run_log": {
                "date": date.today(),
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc),
                "repo": "owner/night-shift",
                "dry_run": False,
                "total_issues": 1,
                "total_prs": 1,
                "events": [
                    {
                        "issue_number": 1,
                        "issue_title": "Test issue",
                        "ghost_name": "Casper",
                        "branch": "night-shift/1-test-issue",
                        "outcome": "pr_opened",
                        "pr_url": "https://github.com/owner/repo/pull/1",
                        "diff_stats": None,
                        "test_output": "1 passed",
                        "agent_output": "Done.",
                        "duration_seconds": 42.0,
                        "note": "Casper slipped in and left a tidy fix.",
                    }
                ],
            }
        }
        template.render(**fixture)
        print("✅ diary.html.j2 renders successfully.")

    except ImportError:
        print("⚠️  Jinja2 not available; skipping template render check.")
    except TemplateError as exc:
        print(f"❌ diary.html.j2 render failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"❌ Unexpected error in diary render check: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
