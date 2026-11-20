"""Tests for nightshift.runner.

Coverage:
  T-15 — run_issue(): verify correct RunEvent.outcome for each scenario
          (pr_opened, test_failed, timeout, over_limit, skipped, agent_error).
  T-16 — run_all(): multi-issue run with mixed outcomes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from nightshift.config import DiaryConfig, NightShiftConfig
from nightshift.github import Issue
from nightshift.runner import RunEvent, RunLog, run_all, run_issue
from nightshift.safety import BranchExistsError, DiffStats, OverLimitError
from nightshift.shell import ShellError, ShellResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_issue(
    number: int = 1,
    title: str = "Fix something",
    body: str = "It is broken.",
    labels: list[str] | None = None,
) -> Issue:
    return Issue(
        number=number,
        title=title,
        body=body,
        labels=labels or ["night-shift"],
        created_at=datetime(2024, 11, 1, tzinfo=timezone.utc),
    )


def make_config(
    dry_run: bool = False,
    max_minutes: int = 15,
    max_files: int = 20,
    max_lines: int = 500,
    test_command: str = "pytest",
    ghost_names: list[str] | None = None,
) -> NightShiftConfig:
    return NightShiftConfig(
        test_command=test_command,
        max_minutes=max_minutes,
        max_files=max_files,
        max_lines=max_lines,
        dry_run=dry_run,
        diary=DiaryConfig(ghost_names=ghost_names or ["Casper", "Spook", "Wraith"]),
    )


def make_shell_result(stdout: str = "", returncode: int = 0) -> ShellResult:
    return ShellResult(cmd=["pytest"], returncode=returncode, stdout=stdout, stderr="")


def make_agent_result(
    success: bool = True,
    output: str = "agent completed",
    timed_out: bool = False,
) -> MagicMock:
    """Return a mock AgentResult."""
    r = MagicMock()
    r.success = success
    r.output = output
    r.timed_out = timed_out
    r.duration_seconds = 1.0
    return r


def make_diff_stats(files: int = 2, added: int = 10, removed: int = 3) -> DiffStats:
    return DiffStats(files_changed=files, lines_added=added, lines_removed=removed)


# ---------------------------------------------------------------------------
# Base patch context for run_issue
# ---------------------------------------------------------------------------
# We mock at module level so the patches apply to the imported names inside runner.py.

_PREPARE_BRANCH = "nightshift.runner.prepare_branch"
_AGENT_RUN = "nightshift.runner.agent_module.run"
_CHECK_DIFF = "nightshift.runner.check_diff_limits"
_SHELL_RUN = "nightshift.runner.shell_run"
_GITHUB_OPEN_PR = "nightshift.runner.github_module.open_pr"
_GITHUB_COMMENT = "nightshift.runner.github_module.comment_on_issue"


# ---------------------------------------------------------------------------
# T-15 — run_issue: outcome == "pr_opened"
# ---------------------------------------------------------------------------


class TestRunIssuePrOpened:
    def _run(self, dry_run: bool = False) -> RunEvent:
        config = make_config(dry_run=dry_run)
        issue = make_issue()
        with (
            patch(_PREPARE_BRANCH, return_value="night-shift/1-fix-something"),
            patch(_AGENT_RUN, return_value=make_agent_result(success=True)),
            patch(_CHECK_DIFF, return_value=make_diff_stats()),
            patch(_SHELL_RUN, return_value=make_shell_result(returncode=0)),
            patch(_GITHUB_OPEN_PR, return_value="https://github.com/owner/repo/pull/10"),
            patch(_GITHUB_COMMENT),
        ):
            return run_issue(issue, config, "Casper")

    def test_outcome_pr_opened(self) -> None:
        event = self._run()
        assert event.outcome == "pr_opened"

    def test_pr_url_set(self) -> None:
        event = self._run()
        assert event.pr_url == "https://github.com/owner/repo/pull/10"

    def test_diff_stats_set(self) -> None:
        event = self._run()
        assert event.diff_stats is not None
        assert event.diff_stats.files_changed == 2

    def test_ghost_name_in_event(self) -> None:
        event = self._run()
        assert event.ghost_name == "Casper"

    def test_issue_number_in_event(self) -> None:
        event = self._run()
        assert event.issue_number == 1

    def test_note_contains_ghost_name(self) -> None:
        event = self._run()
        assert "Casper" in event.note

    def test_dry_run_skips_open_pr(self) -> None:
        config = make_config(dry_run=True)
        issue = make_issue()
        with (
            patch(_PREPARE_BRANCH, return_value="night-shift/1-fix-something"),
            patch(_AGENT_RUN, return_value=make_agent_result(success=True)),
            patch(_CHECK_DIFF, return_value=make_diff_stats()),
            patch(_SHELL_RUN, return_value=make_shell_result(returncode=0)),
            patch(_GITHUB_OPEN_PR) as mock_pr,
            patch(_GITHUB_COMMENT),
        ):
            event = run_issue(issue, config, "Casper")
        # In dry-run mode open_pr is not called
        mock_pr.assert_not_called()
        assert event.outcome == "pr_opened"
        assert event.pr_url is None


# ---------------------------------------------------------------------------
# T-15 — run_issue: outcome == "test_failed"
# ---------------------------------------------------------------------------


class TestRunIssueTestFailed:
    def _run(self, dry_run: bool = False) -> RunEvent:
        config = make_config(dry_run=dry_run)
        issue = make_issue()
        with (
            patch(_PREPARE_BRANCH, return_value="night-shift/1-fix-something"),
            patch(_AGENT_RUN, return_value=make_agent_result(success=True)),
            patch(_CHECK_DIFF, return_value=make_diff_stats()),
            patch(_SHELL_RUN, return_value=make_shell_result(returncode=1, stdout="FAILED tests/")),
            patch(_GITHUB_OPEN_PR),
            patch(_GITHUB_COMMENT),
        ):
            return run_issue(issue, config, "Spook")

    def test_outcome_test_failed(self) -> None:
        assert self._run().outcome == "test_failed"

    def test_pr_url_none(self) -> None:
        assert self._run().pr_url is None

    def test_test_output_captured(self) -> None:
        event = self._run()
        assert "FAILED" in (event.test_output or "")

    def test_comment_posted_when_not_dry_run(self) -> None:
        config = make_config(dry_run=False)
        issue = make_issue()
        with (
            patch(_PREPARE_BRANCH, return_value="night-shift/1-fix-something"),
            patch(_AGENT_RUN, return_value=make_agent_result(success=True)),
            patch(_CHECK_DIFF, return_value=make_diff_stats()),
            patch(_SHELL_RUN, return_value=make_shell_result(returncode=1)),
            patch(_GITHUB_OPEN_PR),
            patch(_GITHUB_COMMENT) as mock_comment,
        ):
            run_issue(issue, config, "Spook")
        mock_comment.assert_called_once()

    def test_comment_not_posted_in_dry_run(self) -> None:
        config = make_config(dry_run=True)
        issue = make_issue()
        with (
            patch(_PREPARE_BRANCH, return_value="night-shift/1-fix-something"),
            patch(_AGENT_RUN, return_value=make_agent_result(success=True)),
            patch(_CHECK_DIFF, return_value=make_diff_stats()),
            patch(_SHELL_RUN, return_value=make_shell_result(returncode=1)),
            patch(_GITHUB_OPEN_PR),
            patch(_GITHUB_COMMENT) as mock_comment,
        ):
            run_issue(issue, config, "Spook")
        mock_comment.assert_not_called()


# ---------------------------------------------------------------------------
# T-15 — run_issue: outcome == "timeout"
# ---------------------------------------------------------------------------


class TestRunIssueTimeout:
    def _run(self) -> RunEvent:
        config = make_config()
        issue = make_issue()
        with (
            patch(_PREPARE_BRANCH, return_value="night-shift/1-fix-something"),
            patch(_AGENT_RUN, return_value=make_agent_result(success=False, timed_out=True, output="partial")),
            patch(_CHECK_DIFF, return_value=make_diff_stats()),
            patch(_SHELL_RUN, return_value=make_shell_result()),
            patch(_GITHUB_OPEN_PR),
            patch(_GITHUB_COMMENT),
        ):
            return run_issue(issue, config, "Wraith")

    def test_outcome_timeout(self) -> None:
        assert self._run().outcome == "timeout"

    def test_pr_url_none(self) -> None:
        assert self._run().pr_url is None

    def test_agent_output_captured(self) -> None:
        event = self._run()
        assert "partial" in (event.agent_output or "")

    def test_diff_stats_none(self) -> None:
        # Diff check is not reached after timeout
        assert self._run().diff_stats is None


# ---------------------------------------------------------------------------
# T-15 — run_issue: outcome == "over_limit"
# ---------------------------------------------------------------------------


class TestRunIssueOverLimit:
    def _run(self) -> RunEvent:
        config = make_config()
        issue = make_issue()
        over_limit_stats = DiffStats(files_changed=50, lines_added=1000, lines_removed=200)
        exc = OverLimitError(over_limit_stats, max_files=20, max_lines=500)
        with (
            patch(_PREPARE_BRANCH, return_value="night-shift/1-fix-something"),
            patch(_AGENT_RUN, return_value=make_agent_result(success=True)),
            patch(_CHECK_DIFF, side_effect=exc),
            patch(_SHELL_RUN, return_value=make_shell_result()),
            patch(_GITHUB_OPEN_PR),
            patch(_GITHUB_COMMENT),
        ):
            return run_issue(issue, config, "Phantom")

    def test_outcome_over_limit(self) -> None:
        assert self._run().outcome == "over_limit"

    def test_pr_url_none(self) -> None:
        assert self._run().pr_url is None

    def test_diff_stats_set(self) -> None:
        event = self._run()
        assert event.diff_stats is not None
        assert event.diff_stats.files_changed == 50


# ---------------------------------------------------------------------------
# T-15 — run_issue: outcome == "skipped"
# ---------------------------------------------------------------------------


class TestRunIssueSkipped:
    def _run(self) -> RunEvent:
        config = make_config()
        issue = make_issue()
        with (
            patch(_PREPARE_BRANCH, side_effect=BranchExistsError("night-shift/1-fix-something")),
            patch(_AGENT_RUN) as mock_agent,
            patch(_CHECK_DIFF),
            patch(_SHELL_RUN),
            patch(_GITHUB_OPEN_PR),
            patch(_GITHUB_COMMENT),
        ):
            event = run_issue(issue, config, "Specter")
        return event

    def test_outcome_skipped(self) -> None:
        assert self._run().outcome == "skipped"

    def test_pr_url_none(self) -> None:
        assert self._run().pr_url is None

    def test_agent_not_called(self) -> None:
        config = make_config()
        issue = make_issue()
        with (
            patch(_PREPARE_BRANCH, side_effect=BranchExistsError("night-shift/1-fix-something")),
            patch(_AGENT_RUN) as mock_agent,
            patch(_CHECK_DIFF),
            patch(_SHELL_RUN),
            patch(_GITHUB_OPEN_PR),
            patch(_GITHUB_COMMENT),
        ):
            run_issue(issue, config, "Specter")
        mock_agent.assert_not_called()


# ---------------------------------------------------------------------------
# T-15 — run_issue: outcome == "agent_error" (branch prepare fails)
# ---------------------------------------------------------------------------


class TestRunIssueAgentError:
    def test_outcome_agent_error_on_shell_error(self) -> None:
        config = make_config()
        issue = make_issue()
        bad_result = ShellResult(cmd=["git"], returncode=1, stdout="", stderr="fatal")
        with (
            patch(_PREPARE_BRANCH, side_effect=ShellError(bad_result)),
            patch(_AGENT_RUN),
            patch(_CHECK_DIFF),
            patch(_SHELL_RUN),
            patch(_GITHUB_OPEN_PR),
            patch(_GITHUB_COMMENT),
        ):
            event = run_issue(issue, config, "Casper")
        assert event.outcome == "agent_error"

    def test_outcome_agent_error_on_nonzero_agent(self) -> None:
        """Agent exits non-zero (not timed out) → agent_error."""
        config = make_config()
        issue = make_issue()
        with (
            patch(_PREPARE_BRANCH, return_value="night-shift/1-fix-something"),
            patch(_AGENT_RUN, return_value=make_agent_result(success=False, timed_out=False)),
            patch(_CHECK_DIFF),
            patch(_SHELL_RUN),
            patch(_GITHUB_OPEN_PR),
            patch(_GITHUB_COMMENT),
        ):
            event = run_issue(issue, config, "Casper")
        assert event.outcome == "agent_error"


# ---------------------------------------------------------------------------
# T-15 — run_issue returns RunEvent with branch name
# ---------------------------------------------------------------------------


class TestRunIssueBranch:
    def test_branch_name_in_event(self) -> None:
        config = make_config()
        issue = make_issue(number=42, title="Fix login bug")
        with (
            patch(_PREPARE_BRANCH, return_value="night-shift/42-fix-login-bug"),
            patch(_AGENT_RUN, return_value=make_agent_result(success=True)),
            patch(_CHECK_DIFF, return_value=make_diff_stats()),
            patch(_SHELL_RUN, return_value=make_shell_result(returncode=0)),
            patch(_GITHUB_OPEN_PR, return_value="https://github.com/pull/1"),
            patch(_GITHUB_COMMENT),
        ):
            event = run_issue(issue, config, "Casper")
        assert "42" in event.branch


# ---------------------------------------------------------------------------
# T-16 — run_all: multi-issue run with mixed outcomes
# ---------------------------------------------------------------------------

_LIST_ISSUES = "nightshift.runner.github_module.list_labeled_issues"
_GET_REPO = "nightshift.runner._get_repo_name"
# _default_branch is imported inside run_all from nightshift.safety, so patch the source
_SAFETY_DEFAULT_BRANCH = "nightshift.safety._default_branch"
_DIARY_SAVE = "nightshift.runner.diary_module.save"
_DIARY_RENDER = "nightshift.runner.diary_module.render"
_RUN_ISSUE = "nightshift.runner.run_issue"


class TestRunAll:
    def _make_event(self, number: int, outcome: str) -> RunEvent:
        return RunEvent(
            issue_number=number,
            issue_title=f"Issue {number}",
            ghost_name="Casper",
            branch=f"night-shift/{number}-issue-{number}",
            outcome=outcome,  # type: ignore[arg-type]
            pr_url=None,
            diff_stats=None,
            test_output=None,
            agent_output=None,
            duration_seconds=1.0,
            note=f"Casper processed issue {number}.",
        )

    def test_returns_run_log(self) -> None:
        config = make_config()
        issues = [make_issue(number=1), make_issue(number=2)]
        events = [self._make_event(1, "pr_opened"), self._make_event(2, "test_failed")]

        with (
            patch(_LIST_ISSUES, return_value=issues),
            patch(_GET_REPO, return_value="owner/repo"),
            patch(_SAFETY_DEFAULT_BRANCH, return_value="main"),
            patch(_RUN_ISSUE, side_effect=events),
            patch(_DIARY_SAVE),
            patch(_DIARY_RENDER),
        ):
            log = run_all(config)

        assert isinstance(log, RunLog)

    def test_run_log_contains_all_events(self) -> None:
        config = make_config()
        issues = [make_issue(number=1), make_issue(number=2), make_issue(number=3)]
        events = [
            self._make_event(1, "pr_opened"),
            self._make_event(2, "test_failed"),
            self._make_event(3, "timeout"),
        ]
        with (
            patch(_LIST_ISSUES, return_value=issues),
            patch(_GET_REPO, return_value="owner/repo"),
            patch(_SAFETY_DEFAULT_BRANCH, return_value="main"),
            patch(_RUN_ISSUE, side_effect=events),
            patch(_DIARY_SAVE),
            patch(_DIARY_RENDER),
        ):
            log = run_all(config)

        assert log.total_issues == 3

    def test_run_log_counts_prs(self) -> None:
        config = make_config()
        issues = [make_issue(number=1), make_issue(number=2)]
        events = [
            self._make_event(1, "pr_opened"),
            self._make_event(2, "pr_opened"),
        ]
        with (
            patch(_LIST_ISSUES, return_value=issues),
            patch(_GET_REPO, return_value="owner/repo"),
            patch(_SAFETY_DEFAULT_BRANCH, return_value="main"),
            patch(_RUN_ISSUE, side_effect=events),
            patch(_DIARY_SAVE),
            patch(_DIARY_RENDER),
        ):
            log = run_all(config)

        assert log.total_prs == 2

    def test_max_issues_respected(self) -> None:
        config = make_config()
        # list_labeled_issues returns 10 but max_issues=5
        config_limited = NightShiftConfig(
            test_command="pytest",
            max_issues=2,
            diary=DiaryConfig(ghost_names=["Casper"]),
        )
        issues = [make_issue(number=i) for i in range(1, 6)]
        events = [self._make_event(i, "pr_opened") for i in range(1, 6)]

        called_numbers: list[int] = []

        def capture_run_issue(issue: Issue, *args, **kwargs) -> RunEvent:  # type: ignore[no-untyped-def]
            called_numbers.append(issue.number)
            return self._make_event(issue.number, "pr_opened")

        with (
            patch(_LIST_ISSUES, return_value=issues),
            patch(_GET_REPO, return_value="owner/repo"),
            patch(_SAFETY_DEFAULT_BRANCH, return_value="main"),
            patch(_RUN_ISSUE, side_effect=capture_run_issue),
            patch(_DIARY_SAVE),
            patch(_DIARY_RENDER),
        ):
            log = run_all(config_limited)

        assert log.total_issues == 2
        assert len(called_numbers) == 2

    def test_no_issues_returns_empty_log(self) -> None:
        config = make_config()
        with (
            patch(_LIST_ISSUES, return_value=[]),
            patch(_GET_REPO, return_value="owner/repo"),
            patch(_SAFETY_DEFAULT_BRANCH, return_value="main"),
            patch(_RUN_ISSUE) as mock_run,
            patch(_DIARY_SAVE),
            patch(_DIARY_RENDER),
        ):
            log = run_all(config)

        assert log.total_issues == 0
        mock_run.assert_not_called()

    def test_unexpected_exception_recorded_as_agent_error(self) -> None:
        """An unexpected crash in run_issue is caught and recorded as agent_error."""
        config = make_config()
        issues = [make_issue(number=1), make_issue(number=2)]

        def boom(issue: Issue, *args, **kwargs) -> RunEvent:  # type: ignore[no-untyped-def]
            if issue.number == 1:
                raise RuntimeError("unexpected crash")
            return self._make_event(2, "pr_opened")

        with (
            patch(_LIST_ISSUES, return_value=issues),
            patch(_GET_REPO, return_value="owner/repo"),
            patch(_SAFETY_DEFAULT_BRANCH, return_value="main"),
            patch(_RUN_ISSUE, side_effect=boom),
            patch(_DIARY_SAVE),
            patch(_DIARY_RENDER),
        ):
            log = run_all(config)

        assert log.total_issues == 2
        outcomes = [e.outcome for e in log.events]
        assert "agent_error" in outcomes
        assert "pr_opened" in outcomes

    def test_diary_save_called(self) -> None:
        config = make_config()
        with (
            patch(_LIST_ISSUES, return_value=[]),
            patch(_GET_REPO, return_value="owner/repo"),
            patch(_SAFETY_DEFAULT_BRANCH, return_value="main"),
            patch(_RUN_ISSUE),
            patch(_DIARY_SAVE) as mock_save,
            patch(_DIARY_RENDER),
        ):
            run_all(config)
        mock_save.assert_called_once()

    def test_diary_render_called(self) -> None:
        config = make_config()
        with (
            patch(_LIST_ISSUES, return_value=[]),
            patch(_GET_REPO, return_value="owner/repo"),
            patch(_SAFETY_DEFAULT_BRANCH, return_value="main"),
            patch(_RUN_ISSUE),
            patch(_DIARY_SAVE),
            patch(_DIARY_RENDER) as mock_render,
        ):
            run_all(config)
        mock_render.assert_called_once()

    def test_diary_failure_does_not_crash_run(self) -> None:
        """Diary save/render errors are non-fatal."""
        config = make_config()
        with (
            patch(_LIST_ISSUES, return_value=[]),
            patch(_GET_REPO, return_value="owner/repo"),
            patch(_SAFETY_DEFAULT_BRANCH, return_value="main"),
            patch(_RUN_ISSUE),
            patch(_DIARY_SAVE, side_effect=OSError("disk full")),
            patch(_DIARY_RENDER),
        ):
            log = run_all(config)  # Must not raise
        assert log is not None

    def test_repo_name_in_log(self) -> None:
        config = make_config()
        with (
            patch(_LIST_ISSUES, return_value=[]),
            patch(_GET_REPO, return_value="myorg/myrepo"),
            patch(_SAFETY_DEFAULT_BRANCH, return_value="main"),
            patch(_RUN_ISSUE),
            patch(_DIARY_SAVE),
            patch(_DIARY_RENDER),
        ):
            log = run_all(config)
        assert log.repo == "myorg/myrepo"

    def test_dry_run_flag_in_log(self) -> None:
        config = make_config(dry_run=True)
        with (
            patch(_LIST_ISSUES, return_value=[]),
            patch(_GET_REPO, return_value="owner/repo"),
            patch(_SAFETY_DEFAULT_BRANCH, return_value="main"),
            patch(_RUN_ISSUE),
            patch(_DIARY_SAVE),
            patch(_DIARY_RENDER),
        ):
            log = run_all(config)
        assert log.dry_run is True
