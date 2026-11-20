"""diary.py — collect run events, serialise them to JSON, and render the Ghost Diary HTML.

Public API
----------
``save(run_log) -> Path``
    Serialise *run_log* to ``.nightshift/runs/YYYY-MM-DD.json``.

``load_log(date) -> RunLog``
    Load a saved ``RunLog`` from the JSON log for *date*.

``render(run_log) -> Path``
    Render the Jinja2 template to ``.nightshift/diary/YYYY-MM-DD.html``.

``quiet_night(date) -> Path``
    Render an empty "quiet night" diary for *date* (no run log exists).

Design decisions (see design.md Decisions section)
---------------------------------------------------
- D-11  ``DiffStats`` is serialised as a nested ``{"files": …, "added": …,
  "removed": …}`` dict for JSON clarity.  The field names deliberately differ
  from the dataclass attribute names so the JSON schema is explicit.
- D-12  All datetimes are stored as ISO-8601 strings with the ``+00:00`` UTC
  offset so they round-trip unambiguously on every platform.
- D-13  The Jinja2 template is loaded from the package's ``templates/``
  directory via ``importlib.resources`` so it works both when installed as a
  wheel and when run from the source tree with ``uv run``.
- D-14  ``render()`` creates the output directory if it does not exist
  (``parents=True, exist_ok=True``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from nightshift.runner import DiffStats, RunEvent, RunLog

logger = logging.getLogger(__name__)

# Relative to the repo root (the working directory when nightshift runs).
_RUNS_DIR = Path(".nightshift") / "runs"
_DIARY_DIR = Path(".nightshift") / "diary"

# Location of the Jinja2 template, relative to this file.
_TEMPLATES_DIR = Path(__file__).parent / "templates"


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _diff_stats_to_dict(stats: DiffStats | None) -> dict[str, int] | None:
    if stats is None:
        return None
    return {
        "files_changed": stats.files_changed,
        "lines_added": stats.lines_added,
        "lines_removed": stats.lines_removed,
    }


def _diff_stats_from_dict(d: dict[str, int] | None) -> DiffStats | None:
    if d is None:
        return None
    return DiffStats(
        files_changed=d["files_changed"],
        lines_added=d["lines_added"],
        lines_removed=d["lines_removed"],
    )


def _event_to_dict(event: RunEvent) -> dict[str, Any]:
    return {
        "issue_number": event.issue_number,
        "issue_title": event.issue_title,
        "ghost_name": event.ghost_name,
        "branch": event.branch,
        "outcome": event.outcome,
        "pr_url": event.pr_url,
        "diff_stats": _diff_stats_to_dict(event.diff_stats),
        "test_output": event.test_output,
        "agent_output": event.agent_output,
        "duration_seconds": event.duration_seconds,
        "note": event.note,
    }


def _event_from_dict(d: dict[str, Any]) -> RunEvent:
    return RunEvent(
        issue_number=d["issue_number"],
        issue_title=d["issue_title"],
        ghost_name=d["ghost_name"],
        branch=d["branch"],
        outcome=d["outcome"],
        pr_url=d.get("pr_url"),
        diff_stats=_diff_stats_from_dict(d.get("diff_stats")),
        test_output=d.get("test_output"),
        agent_output=d.get("agent_output"),
        duration_seconds=d["duration_seconds"],
        note=d["note"],
    )


def _run_log_to_dict(run_log: RunLog) -> dict[str, Any]:
    return {
        "date": run_log.date.isoformat(),
        "start_time": run_log.start_time.isoformat(),
        "end_time": run_log.end_time.isoformat(),
        "repo": run_log.repo,
        "dry_run": run_log.dry_run,
        "events": [_event_to_dict(e) for e in run_log.events],
    }


def _run_log_from_dict(d: dict[str, Any]) -> RunLog:
    return RunLog(
        date=date.fromisoformat(d["date"]),
        start_time=datetime.fromisoformat(d["start_time"]),
        end_time=datetime.fromisoformat(d["end_time"]),
        repo=d["repo"],
        dry_run=d["dry_run"],
        events=[_event_from_dict(e) for e in d.get("events", [])],
    )


# ---------------------------------------------------------------------------
# Public API — persistence
# ---------------------------------------------------------------------------


def save(run_log: RunLog, runs_dir: Path | None = None) -> Path:
    """Serialise *run_log* to a dated JSON file.

    Parameters
    ----------
    run_log:
        The completed ``RunLog`` to persist.
    runs_dir:
        Override the output directory (default: ``.nightshift/runs/``).
        Useful in tests.

    Returns
    -------
    Path
        The path to the written JSON file.
    """
    output_dir = runs_dir or _RUNS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    path = output_dir / f"{run_log.date.isoformat()}.json"
    path.write_text(
        json.dumps(_run_log_to_dict(run_log), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved run log to %s", path)
    return path


def load_log(for_date: date, runs_dir: Path | None = None) -> RunLog:
    """Load the ``RunLog`` for *for_date* from the JSON log directory.

    Parameters
    ----------
    for_date:
        The date of the run to load.
    runs_dir:
        Override the directory to search (default: ``.nightshift/runs/``).

    Returns
    -------
    RunLog

    Raises
    ------
    FileNotFoundError
        If no log exists for *for_date*.
    """
    directory = runs_dir or _RUNS_DIR
    path = directory / f"{for_date.isoformat()}.json"
    if not path.exists():
        raise FileNotFoundError(f"No run log found for {for_date}: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    return _run_log_from_dict(raw)


# ---------------------------------------------------------------------------
# Public API — rendering
# ---------------------------------------------------------------------------


def render(run_log: RunLog, diary_dir: Path | None = None) -> Path:
    """Render the Ghost Diary HTML for *run_log*.

    Parameters
    ----------
    run_log:
        The ``RunLog`` to render.
    diary_dir:
        Override the output directory (default: ``.nightshift/diary/``).

    Returns
    -------
    Path
        The path to the rendered HTML file.
    """
    output_dir = diary_dir or _DIARY_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=True,
    )
    template = env.get_template("diary.html.j2")
    html = template.render(run_log=run_log)

    path = output_dir / f"{run_log.date.isoformat()}.html"
    path.write_text(html, encoding="utf-8")
    logger.info("Rendered Ghost Diary to %s", path)
    return path


def quiet_night(for_date: date, diary_dir: Path | None = None) -> Path:
    """Render a "quiet night" diary for a date with no run log.

    Parameters
    ----------
    for_date:
        The date to render.
    diary_dir:
        Override the output directory.

    Returns
    -------
    Path
        The path to the rendered HTML file.
    """
    now = datetime.now(timezone.utc)
    empty_log = RunLog(
        date=for_date,
        start_time=now,
        end_time=now,
        repo="unknown",
        dry_run=False,
        events=[],
    )
    return render(empty_log, diary_dir=diary_dir)
