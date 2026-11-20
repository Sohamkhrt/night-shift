"""Tests for nightshift.diary.

Coverage:
  T-17 — save(): JSON file created, round-trip readable.
  T-18 — template existence and basic structure (HTML headers, outcome badges).
  T-19 — render(): known RunLog → HTML contains issue number and ghost name.
         Property test: arbitrary RunLog never raises.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from nightshift.diary import load_log, render, save
from nightshift.runner import DiffStats, RunEvent, RunLog


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_OUTCOME_STRATEGY = st.sampled_from(
    ["pr_opened", "test_failed", "timeout", "over_limit", "skipped", "agent_error"]
)

_GHOST_NAMES = ["Casper", "Spook", "Wraith", "Phantom", "Specter"]

_OPT_TEXT = st.one_of(st.none(), st.text(max_size=200))

_DIFF_STATS_STRATEGY = st.one_of(
    st.none(),
    st.builds(
        DiffStats,
        files_changed=st.integers(min_value=0, max_value=100),
        lines_added=st.integers(min_value=0, max_value=10000),
        lines_removed=st.integers(min_value=0, max_value=10000),
    ),
)

_RUN_EVENT_STRATEGY = st.builds(
    RunEvent,
    issue_number=st.integers(min_value=1, max_value=9999),
    issue_title=st.text(min_size=1, max_size=100),
    ghost_name=st.sampled_from(_GHOST_NAMES),
    branch=st.text(min_size=1, max_size=60, alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="-/")),
    outcome=_OUTCOME_STRATEGY,
    pr_url=st.one_of(st.none(), st.just("https://github.com/owner/repo/pull/1")),
    diff_stats=_DIFF_STATS_STRATEGY,
    test_output=_OPT_TEXT,
    agent_output=_OPT_TEXT,
    duration_seconds=st.floats(min_value=0.0, max_value=3600.0, allow_nan=False, allow_infinity=False),
    note=st.text(max_size=200),
)

_RUN_LOG_STRATEGY = st.builds(
    RunLog,
    date=st.dates(min_value=date(2024, 1, 1), max_value=date(2030, 12, 31)),
    start_time=st.just(datetime(2024, 11, 1, 1, 0, 0, tzinfo=timezone.utc)),
    end_time=st.just(datetime(2024, 11, 1, 1, 30, 0, tzinfo=timezone.utc)),
    repo=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="-/")),
    dry_run=st.booleans(),
    events=st.lists(_RUN_EVENT_STRATEGY, min_size=0, max_size=5),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_diff_stats(files: int = 2, added: int = 10, removed: int = 3) -> DiffStats:
    return DiffStats(files_changed=files, lines_added=added, lines_removed=removed)


def make_event(
    number: int = 42,
    title: str = "Fix the login bug",
    ghost_name: str = "Casper",
    outcome: str = "pr_opened",
    pr_url: str | None = "https://github.com/owner/repo/pull/10",
    diff_stats: DiffStats | None = None,
) -> RunEvent:
    return RunEvent(
        issue_number=number,
        issue_title=title,
        ghost_name=ghost_name,
        branch=f"night-shift/{number}-fix-the-login-bug",
        outcome=outcome,  # type: ignore[arg-type]
        pr_url=pr_url,
        diff_stats=diff_stats or make_diff_stats(),
        test_output="1 passed",
        agent_output="agent completed successfully",
        duration_seconds=42.5,
        note=f"{ghost_name} slipped in and fixed the issue.",
    )


def make_run_log(
    events: list[RunEvent] | None = None,
    dry_run: bool = False,
    run_date: date | None = None,
) -> RunLog:
    d = run_date or date(2024, 11, 1)
    return RunLog(
        date=d,
        start_time=datetime(2024, 11, 1, 1, 0, 0, tzinfo=timezone.utc),
        end_time=datetime(2024, 11, 1, 1, 30, 0, tzinfo=timezone.utc),
        repo="owner/repo",
        dry_run=dry_run,
        events=events or [],
    )


# ---------------------------------------------------------------------------
# T-17 — save(): file is created and round-trips
# ---------------------------------------------------------------------------


class TestSave:
    def test_creates_file(self, tmp_path: Path) -> None:
        log = make_run_log()
        path = save(log, runs_dir=tmp_path)
        assert path.exists()

    def test_file_named_by_date(self, tmp_path: Path) -> None:
        log = make_run_log(run_date=date(2024, 11, 20))
        path = save(log, runs_dir=tmp_path)
        assert path.name == "2024-11-20.json"

    def test_file_is_valid_json(self, tmp_path: Path) -> None:
        log = make_run_log(events=[make_event()])
        path = save(log, runs_dir=tmp_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_json_contains_date(self, tmp_path: Path) -> None:
        log = make_run_log(run_date=date(2024, 11, 1))
        path = save(log, runs_dir=tmp_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["date"] == "2024-11-01"

    def test_json_contains_events(self, tmp_path: Path) -> None:
        log = make_run_log(events=[make_event(42), make_event(99)])
        path = save(log, runs_dir=tmp_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["events"]) == 2

    def test_json_contains_repo(self, tmp_path: Path) -> None:
        log = make_run_log()
        path = save(log, runs_dir=tmp_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["repo"] == "owner/repo"

    def test_json_dry_run_flag(self, tmp_path: Path) -> None:
        log = make_run_log(dry_run=True)
        path = save(log, runs_dir=tmp_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["dry_run"] is True

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "nested" / "dir"
        log = make_run_log()
        path = save(log, runs_dir=nested)
        assert path.exists()


class TestRoundTrip:
    def test_round_trip_no_events(self, tmp_path: Path) -> None:
        original = make_run_log()
        save(original, runs_dir=tmp_path)
        loaded = load_log(original.date, runs_dir=tmp_path)
        assert loaded.date == original.date
        assert loaded.repo == original.repo
        assert loaded.dry_run == original.dry_run
        assert len(loaded.events) == 0

    def test_round_trip_with_events(self, tmp_path: Path) -> None:
        events = [make_event(1, "Issue One", "Casper", "pr_opened")]
        original = make_run_log(events=events)
        save(original, runs_dir=tmp_path)
        loaded = load_log(original.date, runs_dir=tmp_path)
        assert len(loaded.events) == 1
        e = loaded.events[0]
        assert e.issue_number == 1
        assert e.issue_title == "Issue One"
        assert e.ghost_name == "Casper"
        assert e.outcome == "pr_opened"

    def test_round_trip_diff_stats(self, tmp_path: Path) -> None:
        stats = DiffStats(files_changed=5, lines_added=100, lines_removed=20)
        events = [make_event(diff_stats=stats)]
        original = make_run_log(events=events)
        save(original, runs_dir=tmp_path)
        loaded = load_log(original.date, runs_dir=tmp_path)
        ds = loaded.events[0].diff_stats
        assert ds is not None
        assert ds.files_changed == 5
        assert ds.lines_added == 100
        assert ds.lines_removed == 20

    def test_round_trip_null_diff_stats(self, tmp_path: Path) -> None:
        event = make_event(diff_stats=None)
        event = RunEvent(
            issue_number=event.issue_number,
            issue_title=event.issue_title,
            ghost_name=event.ghost_name,
            branch=event.branch,
            outcome=event.outcome,
            pr_url=event.pr_url,
            diff_stats=None,
            test_output=event.test_output,
            agent_output=event.agent_output,
            duration_seconds=event.duration_seconds,
            note=event.note,
        )
        original = make_run_log(events=[event])
        save(original, runs_dir=tmp_path)
        loaded = load_log(original.date, runs_dir=tmp_path)
        assert loaded.events[0].diff_stats is None

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_log(date(2099, 1, 1), runs_dir=tmp_path)


# ---------------------------------------------------------------------------
# T-19 — render(): known RunLog → HTML structure
# ---------------------------------------------------------------------------


class TestRender:
    def test_creates_html_file(self, tmp_path: Path) -> None:
        log = make_run_log(events=[make_event()])
        path = render(log, diary_dir=tmp_path)
        assert path.exists()
        assert path.suffix == ".html"

    def test_file_named_by_date(self, tmp_path: Path) -> None:
        log = make_run_log(run_date=date(2024, 11, 20))
        path = render(log, diary_dir=tmp_path)
        assert path.name == "2024-11-20.html"

    def test_html_contains_issue_number(self, tmp_path: Path) -> None:
        log = make_run_log(events=[make_event(number=42)])
        path = render(log, diary_dir=tmp_path)
        html = path.read_text(encoding="utf-8")
        assert "42" in html

    def test_html_contains_ghost_name(self, tmp_path: Path) -> None:
        log = make_run_log(events=[make_event(ghost_name="Casper")])
        path = render(log, diary_dir=tmp_path)
        html = path.read_text(encoding="utf-8")
        assert "Casper" in html

    def test_html_contains_issue_title(self, tmp_path: Path) -> None:
        log = make_run_log(events=[make_event(title="Fix the login bug")])
        path = render(log, diary_dir=tmp_path)
        html = path.read_text(encoding="utf-8")
        assert "Fix the login bug" in html

    def test_html_contains_run_date(self, tmp_path: Path) -> None:
        log = make_run_log(run_date=date(2024, 11, 1))
        path = render(log, diary_dir=tmp_path)
        html = path.read_text(encoding="utf-8")
        assert "2024-11-01" in html

    def test_html_is_valid_html_skeleton(self, tmp_path: Path) -> None:
        log = make_run_log()
        path = render(log, diary_dir=tmp_path)
        html = path.read_text(encoding="utf-8")
        assert "<html" in html.lower()
        assert "</html>" in html.lower()
        assert "<body" in html.lower()

    def test_html_contains_ghost_diary_heading(self, tmp_path: Path) -> None:
        log = make_run_log()
        path = render(log, diary_dir=tmp_path)
        html = path.read_text(encoding="utf-8")
        assert "Ghost Diary" in html

    def test_html_outcome_badge_present(self, tmp_path: Path) -> None:
        log = make_run_log(events=[make_event(outcome="pr_opened")])
        path = render(log, diary_dir=tmp_path)
        html = path.read_text(encoding="utf-8")
        # The badge class is badge-pr_opened
        assert "pr_opened" in html or "pr opened" in html

    def test_html_pr_url_link_present(self, tmp_path: Path) -> None:
        url = "https://github.com/owner/repo/pull/10"
        log = make_run_log(events=[make_event(pr_url=url)])
        path = render(log, diary_dir=tmp_path)
        html = path.read_text(encoding="utf-8")
        assert url in html

    def test_html_no_events_shows_quiet_night(self, tmp_path: Path) -> None:
        log = make_run_log(events=[])
        path = render(log, diary_dir=tmp_path)
        html = path.read_text(encoding="utf-8")
        assert "quiet" in html.lower()

    def test_html_dry_run_flagged(self, tmp_path: Path) -> None:
        log = make_run_log(dry_run=True)
        path = render(log, diary_dir=tmp_path)
        html = path.read_text(encoding="utf-8")
        assert "dry" in html.lower()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "diary"
        log = make_run_log()
        path = render(log, diary_dir=nested)
        assert path.exists()

    def test_multiple_events_all_appear(self, tmp_path: Path) -> None:
        events = [
            make_event(1, "First Issue", "Casper"),
            make_event(2, "Second Issue", "Spook"),
        ]
        log = make_run_log(events=events)
        path = render(log, diary_dir=tmp_path)
        html = path.read_text(encoding="utf-8")
        assert "First Issue" in html
        assert "Second Issue" in html
        assert "Casper" in html
        assert "Spook" in html


# ---------------------------------------------------------------------------
# T-19 — Property test: arbitrary RunLog never raises
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(run_log=_RUN_LOG_STRATEGY)
def test_render_never_raises(run_log: RunLog, tmp_path: Path) -> None:
    """Rendering any arbitrarily constructed RunLog must not raise an exception."""
    # Each hypothesis example gets the same tmp_path; use a sub-dir per run to
    # avoid collisions between examples (Hypothesis reuses the fixture).
    diary_dir = tmp_path / run_log.date.isoformat()
    render(run_log, diary_dir=diary_dir)


# ---------------------------------------------------------------------------
# Property test: ghost assignment always in roster
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    issue_number=st.integers(min_value=0, max_value=10_000_000),
    ghost_names=st.lists(
        st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Lu", "Ll"))),
        min_size=1,
        max_size=10,
    ),
)
def test_ghost_assignment_always_in_roster(issue_number: int, ghost_names: list[str]) -> None:
    """Ghost assignment (issue_number % len(ghost_names)) always gives a valid roster entry."""
    ghost = ghost_names[issue_number % len(ghost_names)]
    assert ghost in ghost_names


# ---------------------------------------------------------------------------
# Property test: rendered HTML always contains the run date
# ---------------------------------------------------------------------------


@settings(max_examples=50, deadline=None)
@given(
    run_date=st.dates(min_value=date(2024, 1, 1), max_value=date(2030, 12, 31)),
)
def test_html_always_contains_date(run_date: date, tmp_path: Path) -> None:
    """The rendered HTML must always contain the run date as a string."""
    log = RunLog(
        date=run_date,
        start_time=datetime(2024, 1, 1, 1, 0, 0, tzinfo=timezone.utc),
        end_time=datetime(2024, 1, 1, 1, 30, 0, tzinfo=timezone.utc),
        repo="owner/repo",
        dry_run=False,
        events=[],
    )
    diary_dir = tmp_path / run_date.isoformat()
    path = render(log, diary_dir=diary_dir)
    html = path.read_text(encoding="utf-8")
    assert run_date.isoformat() in html
