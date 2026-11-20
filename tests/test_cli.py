"""Tests for the Phase 6 CLI wiring (T-21, T-22) and lock file (T-23).

Coverage
--------
T-21 — ``nightshift run``:
    - auth failure exits with code 1 and prints an error.
    - config error exits with code 1.
    - LockError exits with code 1.
    - Successful run prints per-issue summary and diary path.
    - ``--dry-run`` flag is forwarded to runner (config.dry_run is True).
    - ``--dry-run`` banner is printed when dry_run is active.
    - run_all return value drives output (issue count, PR count).

T-22 — ``nightshift status``:
    - Config error exits with code 1.
    - gh failure exits with code 1.
    - Lists labeled issues with number and title.
    - Shows "no issues" message when list is empty.
    - Loads and prints last run summary.
    - Shows "no run logs" when runs dir is absent.

T-23 — Lock file (``acquire_lock`` / ``release_lock`` / ``LockError``):
    - acquire_lock creates the lock file.
    - acquire_lock raises LockError when lock already exists.
    - release_lock removes the lock file.
    - release_lock is idempotent (no error if file absent).
    - run_all releases lock on normal return.
    - run_all releases lock even when _run_all_inner raises.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from nightshift.cli import app
from nightshift.config import DiaryConfig, NightShiftConfig
from nightshift.github import Issue
from nightshift.runner import (
    DEFAULT_LOCK_PATH,
    LockError,
    RunEvent,
    RunLog,
    acquire_lock,
    release_lock,
)
from nightshift.safety import DiffStats
from nightshift.shell import ShellResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

runner = CliRunner()


def make_config(dry_run: bool = False) -> NightShiftConfig:
    return NightShiftConfig(
        test_command="pytest",
        label="night-shift",
        max_issues=5,
        max_minutes=15,
        max_files=20,
        max_lines=500,
        dry_run=dry_run,
        diary=DiaryConfig(ghost_names=["Casper", "Spook", "Wraith", "Phantom", "Specter"]),
    )


def make_issue(number: int = 1, title: str = "Fix something") -> Issue:
    return Issue(
        number=number,
        title=title,
        body="It is broken.",
        labels=["night-shift"],
        created_at=dt.datetime(2024, 11, 1, tzinfo=dt.timezone.utc),
    )


def make_run_log(
    *,
    dry_run: bool = False,
    events: list[RunEvent] | None = None,
    date: dt.date | None = None,
) -> RunLog:
    now = dt.datetime(2024, 11, 20, 1, 0, 0, tzinfo=dt.timezone.utc)
    return RunLog(
        date=date or dt.date(2024, 11, 20),
        start_time=now,
        end_time=now.replace(hour=1, minute=15),
        repo="owner/repo",
        dry_run=dry_run,
        events=events or [],
    )


def make_run_event(
    number: int = 1,
    title: str = "Fix something",
    outcome: str = "pr_opened",
    pr_url: str | None = "https://github.com/owner/repo/pull/10",
) -> RunEvent:
    return RunEvent(
        issue_number=number,
        issue_title=title,
        ghost_name="Casper",
        branch=f"night-shift/{number}-fix-something",
        outcome=outcome,  # type: ignore[arg-type]
        pr_url=pr_url,
        diff_stats=DiffStats(files_changed=2, lines_added=10, lines_removed=3),
        test_output="passed",
        agent_output="done",
        duration_seconds=42.0,
        note="Casper slipped in and fixed things.",
    )


# ---------------------------------------------------------------------------
# T-21 — nightshift run
# ---------------------------------------------------------------------------


class TestRunCommand:
    """Tests for the ``nightshift run`` CLI command."""

    # validate_auth is imported at module level in cli.py, so patch the
    # cli module's reference.  config.load and runner.run_all are imported
    # inside the function body, so patch the source module directly.
    _VALIDATE_AUTH = "nightshift.cli.validate_auth"
    _CONFIG_LOAD = "nightshift.config.load"
    _RUN_ALL = "nightshift.runner.run_all"

    def _invoke(self, *args: str) -> "Result":
        return runner.invoke(app, ["run", *args])

    def test_auth_failure_exits_1(self) -> None:
        from nightshift.github import GitHubAuthError
        with patch(self._VALIDATE_AUTH, side_effect=GitHubAuthError("not logged in")):
            result = self._invoke()
        assert result.exit_code == 1
        assert "Error" in result.output or "Error" in (result.stderr or "")

    def test_auth_failure_prints_error_message(self) -> None:
        from nightshift.github import GitHubAuthError
        with patch(self._VALIDATE_AUTH, side_effect=GitHubAuthError("not logged in")):
            result = self._invoke()
        combined = result.output + (result.stderr or "")
        assert "not logged in" in combined

    def test_config_error_exits_1(self) -> None:
        from nightshift.config import ConfigError
        with (
            patch(self._VALIDATE_AUTH),
            patch(self._CONFIG_LOAD, side_effect=ConfigError("bad config")),
        ):
            result = self._invoke()
        assert result.exit_code == 1

    def test_config_error_prints_message(self) -> None:
        from nightshift.config import ConfigError
        with (
            patch(self._VALIDATE_AUTH),
            patch(self._CONFIG_LOAD, side_effect=ConfigError("bad config")),
        ):
            result = self._invoke()
        combined = result.output + (result.stderr or "")
        assert "bad config" in combined

    def test_lock_error_exits_1(self) -> None:
        with (
            patch(self._VALIDATE_AUTH),
            patch(self._CONFIG_LOAD, return_value=make_config()),
            patch(self._RUN_ALL, side_effect=LockError(Path(".nightshift/locks/run.lock"))),
        ):
            result = self._invoke()
        assert result.exit_code == 1

    def test_lock_error_prints_message(self) -> None:
        with (
            patch(self._VALIDATE_AUTH),
            patch(self._CONFIG_LOAD, return_value=make_config()),
            patch(self._RUN_ALL, side_effect=LockError(Path(".nightshift/locks/run.lock"))),
        ):
            result = self._invoke()
        combined = result.output + (result.stderr or "")
        assert "lock" in combined.lower()

    def test_successful_run_exits_0(self) -> None:
        log = make_run_log()
        with (
            patch(self._VALIDATE_AUTH),
            patch(self._CONFIG_LOAD, return_value=make_config()),
            patch(self._RUN_ALL, return_value=log),
        ):
            result = self._invoke()
        assert result.exit_code == 0

    def test_successful_run_prints_issue_count(self) -> None:
        events = [make_run_event(1), make_run_event(2, outcome="test_failed", pr_url=None)]
        log = make_run_log(events=events)
        with (
            patch(self._VALIDATE_AUTH),
            patch(self._CONFIG_LOAD, return_value=make_config()),
            patch(self._RUN_ALL, return_value=log),
        ):
            result = self._invoke()
        assert "2" in result.output  # total_issues

    def test_successful_run_prints_pr_count(self) -> None:
        events = [make_run_event(1, outcome="pr_opened")]
        log = make_run_log(events=events)
        with (
            patch(self._VALIDATE_AUTH),
            patch(self._CONFIG_LOAD, return_value=make_config()),
            patch(self._RUN_ALL, return_value=log),
        ):
            result = self._invoke()
        assert "1" in result.output  # total_prs == 1

    def test_per_issue_outcome_printed(self) -> None:
        events = [make_run_event(42, title="Login bug", outcome="pr_opened")]
        log = make_run_log(events=events)
        with (
            patch(self._VALIDATE_AUTH),
            patch(self._CONFIG_LOAD, return_value=make_config()),
            patch(self._RUN_ALL, return_value=log),
        ):
            result = self._invoke()
        assert "42" in result.output
        assert "pr_opened" in result.output

    def test_dry_run_flag_forwarded_to_runner(self) -> None:
        """When --dry-run is passed, run_all receives a config with dry_run=True."""
        log = make_run_log(dry_run=True)
        captured: list[NightShiftConfig] = []

        def capture_config(cfg: NightShiftConfig, **kwargs: object) -> RunLog:
            captured.append(cfg)
            return log

        with (
            patch(self._VALIDATE_AUTH),
            patch(self._CONFIG_LOAD, return_value=make_config(dry_run=False)),
            patch(self._RUN_ALL, side_effect=capture_config),
        ):
            result = self._invoke("--dry-run")

        assert result.exit_code == 0
        assert captured[0].dry_run is True

    def test_dry_run_banner_printed(self) -> None:
        log = make_run_log(dry_run=True)
        with (
            patch(self._VALIDATE_AUTH),
            patch(self._CONFIG_LOAD, return_value=make_config()),
            patch(self._RUN_ALL, return_value=log),
        ):
            result = self._invoke("--dry-run")
        assert "dry-run" in result.output.lower() or "dry_run" in result.output.lower()

    def test_no_dry_run_flag_config_dry_run_false_honored(self) -> None:
        """Without --dry-run, the config value is passed through unchanged."""
        log = make_run_log()
        captured: list[NightShiftConfig] = []

        def capture_config(cfg: NightShiftConfig, **kwargs: object) -> RunLog:
            captured.append(cfg)
            return log

        with (
            patch(self._VALIDATE_AUTH),
            patch(self._CONFIG_LOAD, return_value=make_config(dry_run=False)),
            patch(self._RUN_ALL, side_effect=capture_config),
        ):
            result = self._invoke()

        assert result.exit_code == 0
        assert captured[0].dry_run is False

    def test_diary_path_printed_when_exists(self, tmp_path: Path) -> None:
        """If the diary file exists, its path is printed."""
        log_date = dt.date(2024, 11, 20)
        log = make_run_log(date=log_date)

        # Create the diary file in the tmp working directory
        diary_dir = tmp_path / ".nightshift" / "diary"
        diary_dir.mkdir(parents=True)
        (diary_dir / "2024-11-20.html").write_text("<html/>")

        import os
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            with (
                patch(self._VALIDATE_AUTH),
                patch(self._CONFIG_LOAD, return_value=make_config()),
                patch(self._RUN_ALL, return_value=log),
            ):
                result = self._invoke()
        finally:
            os.chdir(old_cwd)

        assert "diary" in result.output.lower() or "2024-11-20" in result.output


# ---------------------------------------------------------------------------
# T-22 — nightshift status
# ---------------------------------------------------------------------------


class TestStatusCommand:
    """Tests for the ``nightshift status`` CLI command."""

    # Same rationale as TestRunCommand: imports are deferred, patch at source.
    _CONFIG_LOAD = "nightshift.config.load"
    _LIST_ISSUES = "nightshift.github.list_labeled_issues"

    def _invoke(self, *args: str) -> "Result":
        return runner.invoke(app, ["status", *args])

    def test_config_error_exits_1(self) -> None:
        from nightshift.config import ConfigError
        with patch(self._CONFIG_LOAD, side_effect=ConfigError("bad")):
            result = self._invoke()
        assert result.exit_code == 1

    def test_gh_failure_exits_1(self) -> None:
        from nightshift.shell import ShellError
        with (
            patch(self._CONFIG_LOAD, return_value=make_config()),
            patch(self._LIST_ISSUES, side_effect=RuntimeError("gh failed")),
        ):
            result = self._invoke()
        assert result.exit_code == 1

    def test_gh_failure_prints_error(self) -> None:
        with (
            patch(self._CONFIG_LOAD, return_value=make_config()),
            patch(self._LIST_ISSUES, side_effect=RuntimeError("connection refused")),
        ):
            result = self._invoke()
        combined = result.output + (result.stderr or "")
        assert "connection refused" in combined

    def test_lists_issues_with_number_and_title(self) -> None:
        issues = [make_issue(42, "Login bug"), make_issue(7, "Dark mode")]
        with (
            patch(self._CONFIG_LOAD, return_value=make_config()),
            patch(self._LIST_ISSUES, return_value=issues),
        ):
            result = self._invoke()
        assert "42" in result.output
        assert "Login bug" in result.output
        assert "7" in result.output
        assert "Dark mode" in result.output

    def test_no_issues_message(self) -> None:
        with (
            patch(self._CONFIG_LOAD, return_value=make_config()),
            patch(self._LIST_ISSUES, return_value=[]),
        ):
            result = self._invoke()
        assert result.exit_code == 0
        assert "no open issues" in result.output.lower() or "no issue" in result.output.lower()

    def test_shows_last_run_summary(self, tmp_path: Path) -> None:
        """When a run log exists on disk, its summary is shown."""
        # Write a minimal run log to a tmp runs dir
        log_date = dt.date(2024, 11, 19)
        events = [make_run_event(1, "Some issue", outcome="pr_opened")]
        log = make_run_log(date=log_date, events=events)

        log_dict = {
            "date": log_date.isoformat(),
            "start_time": log.start_time.isoformat(),
            "end_time": log.end_time.isoformat(),
            "repo": log.repo,
            "dry_run": log.dry_run,
            "events": [
                {
                    "issue_number": e.issue_number,
                    "issue_title": e.issue_title,
                    "ghost_name": e.ghost_name,
                    "branch": e.branch,
                    "outcome": e.outcome,
                    "pr_url": e.pr_url,
                    "diff_stats": {
                        "files_changed": e.diff_stats.files_changed,
                        "lines_added": e.diff_stats.lines_added,
                        "lines_removed": e.diff_stats.lines_removed,
                    } if e.diff_stats else None,
                    "test_output": e.test_output,
                    "agent_output": e.agent_output,
                    "duration_seconds": e.duration_seconds,
                    "note": e.note,
                }
                for e in events
            ],
        }

        runs_dir = tmp_path / ".nightshift" / "runs"
        runs_dir.mkdir(parents=True)
        (runs_dir / "2024-11-19.json").write_text(json.dumps(log_dict))

        import os
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            with (
                patch(self._CONFIG_LOAD, return_value=make_config()),
                patch(self._LIST_ISSUES, return_value=[]),
            ):
                result = self._invoke()
        finally:
            os.chdir(old_cwd)

        assert result.exit_code == 0
        assert "2024-11-19" in result.output
        assert "pr_opened" in result.output

    def test_no_run_logs_message(self, tmp_path: Path) -> None:
        """When no run log exists, a helpful message is shown."""
        import os
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            with (
                patch(self._CONFIG_LOAD, return_value=make_config()),
                patch(self._LIST_ISSUES, return_value=[]),
            ):
                result = self._invoke()
        finally:
            os.chdir(old_cwd)

        assert result.exit_code == 0
        assert "no run log" in result.output.lower() or "no run" in result.output.lower()

    def test_exits_0_on_success(self) -> None:
        with (
            patch(self._CONFIG_LOAD, return_value=make_config()),
            patch(self._LIST_ISSUES, return_value=[]),
        ):
            result = self._invoke()
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# T-23 — Lock file unit tests
# ---------------------------------------------------------------------------


class TestAcquireLock:
    """Tests for ``runner.acquire_lock``."""

    def test_creates_lock_file(self, tmp_path: Path) -> None:
        lock = tmp_path / "run.lock"
        acquire_lock(lock)
        assert lock.exists()

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        lock = tmp_path / "locks" / "nested" / "run.lock"
        acquire_lock(lock)
        assert lock.exists()

    def test_raises_lock_error_if_already_locked(self, tmp_path: Path) -> None:
        lock = tmp_path / "run.lock"
        lock.touch()
        with pytest.raises(LockError) as exc_info:
            acquire_lock(lock)
        assert exc_info.value.lock_path == lock

    def test_lock_error_message_contains_path(self, tmp_path: Path) -> None:
        lock = tmp_path / "run.lock"
        lock.touch()
        with pytest.raises(LockError) as exc_info:
            acquire_lock(lock)
        assert str(lock) in str(exc_info.value)

    def test_lock_error_has_lock_path_attribute(self, tmp_path: Path) -> None:
        lock = tmp_path / "run.lock"
        lock.touch()
        with pytest.raises(LockError) as exc_info:
            acquire_lock(lock)
        assert exc_info.value.lock_path == lock


class TestReleaseLock:
    """Tests for ``runner.release_lock``."""

    def test_removes_lock_file(self, tmp_path: Path) -> None:
        lock = tmp_path / "run.lock"
        lock.touch()
        release_lock(lock)
        assert not lock.exists()

    def test_idempotent_when_already_absent(self, tmp_path: Path) -> None:
        lock = tmp_path / "run.lock"
        # File does not exist — should not raise
        release_lock(lock)

    def test_lock_gone_after_acquire_then_release(self, tmp_path: Path) -> None:
        lock = tmp_path / "run.lock"
        acquire_lock(lock)
        assert lock.exists()
        release_lock(lock)
        assert not lock.exists()

    def test_can_reacquire_after_release(self, tmp_path: Path) -> None:
        lock = tmp_path / "run.lock"
        acquire_lock(lock)
        release_lock(lock)
        # Should not raise
        acquire_lock(lock)
        assert lock.exists()


class TestRunAllLocking:
    """Tests that ``run_all`` acquires and releases the lock correctly."""

    _RUN_INNER = "nightshift.runner._run_all_inner"

    def test_run_all_releases_lock_on_success(self, tmp_path: Path) -> None:
        from nightshift.runner import run_all
        lock = tmp_path / "run.lock"

        fake_log = make_run_log()
        with patch(self._RUN_INNER, return_value=fake_log):
            run_all(make_config(), lock_path=lock)

        # Lock should be gone after a successful run
        assert not lock.exists()

    def test_run_all_releases_lock_on_exception(self, tmp_path: Path) -> None:
        from nightshift.runner import run_all
        lock = tmp_path / "run.lock"

        with (
            patch(self._RUN_INNER, side_effect=RuntimeError("unexpected crash")),
            pytest.raises(RuntimeError),
        ):
            run_all(make_config(), lock_path=lock)

        # Lock must be released even after a crash
        assert not lock.exists()

    def test_run_all_raises_lock_error_if_already_locked(self, tmp_path: Path) -> None:
        from nightshift.runner import run_all
        lock = tmp_path / "run.lock"
        lock.touch()  # simulate a concurrent run

        with pytest.raises(LockError):
            run_all(make_config(), lock_path=lock)

    def test_run_all_lock_exists_during_run(self, tmp_path: Path) -> None:
        """The lock file should exist while _run_all_inner is executing."""
        from nightshift.runner import run_all
        lock = tmp_path / "run.lock"
        observed: list[bool] = []

        def check_lock(*_: object, **__: object) -> RunLog:
            observed.append(lock.exists())
            return make_run_log()

        with patch(self._RUN_INNER, side_effect=check_lock):
            run_all(make_config(), lock_path=lock)

        assert observed == [True], "Lock file should exist during _run_all_inner"


# ---------------------------------------------------------------------------
# LockError dataclass
# ---------------------------------------------------------------------------


class TestLockError:
    def test_is_runtime_error(self, tmp_path: Path) -> None:
        lock = tmp_path / "run.lock"
        err = LockError(lock)
        assert isinstance(err, RuntimeError)

    def test_lock_path_attribute(self, tmp_path: Path) -> None:
        lock = tmp_path / "run.lock"
        err = LockError(lock)
        assert err.lock_path == lock

    def test_str_contains_delete_hint(self, tmp_path: Path) -> None:
        lock = tmp_path / "run.lock"
        err = LockError(lock)
        # Should tell the user how to recover
        assert "delete" in str(err).lower() or "remove" in str(err).lower()
