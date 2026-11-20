"""runner.py — orchestrate one nightly run across N issues.

This module is the main control loop.  It ties together config, github,
agent, safety, and shell into a single ``run_all()`` call.

Data models
-----------
``RunEvent``  — the outcome record for one issue in a nightly run.
``RunLog``    — the complete record for one nightly run (header + all events).

Public functions
----------------
``run_issue(issue, config, ghost_name)``
    Process a single issue end-to-end and return a ``RunEvent``.

``run_all(config) -> RunLog``
    Fetch issues, loop over them, write the diary, return the ``RunLog``.

Design decisions (see design.md Decisions section)
---------------------------------------------------
- D-08  ``run_issue`` accepts an explicit *ghost_name* so the caller controls
  ghost assignment, keeping the function pure of global state.
- D-09  Per-issue exceptions that fall through (unexpected crashes in mocked
  or real code) are caught at the ``run_all`` level and recorded as
  ``outcome="agent_error"``.  The run always continues to the next issue.
- D-10  ``run_issue`` receives the *repo* parameter as a plain string.
  Determining the repo name is the caller's responsibility; ``run_all``
  resolves it via ``gh repo view``.
"""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Literal

from nightshift import agent as agent_module
from nightshift import diary as diary_module
from nightshift import github as github_module
from nightshift.config import NightShiftConfig
from nightshift.github import Issue
from nightshift.safety import (
    BranchExistsError,
    DiffStats,
    OverLimitError,
    check_diff_limits,
    make_branch_name,
    prepare_branch,
)
from nightshift.shell import ShellError, run as shell_run

logger = logging.getLogger(__name__)

# Outcome literals (matches design.md data model)
Outcome = Literal[
    "pr_opened",
    "test_failed",
    "timeout",
    "over_limit",
    "skipped",
    "agent_error",
]

# Maximum characters stored in test_output / agent_output on a RunEvent.
_MAX_SNIPPET = 2_000


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class RunEvent:
    """The outcome record for one issue processed during a nightly run."""

    issue_number: int
    issue_title: str
    ghost_name: str
    branch: str
    outcome: Outcome
    pr_url: str | None
    diff_stats: DiffStats | None
    test_output: str | None       # truncated to _MAX_SNIPPET chars
    agent_output: str | None      # truncated to _MAX_SNIPPET chars
    duration_seconds: float
    note: str                     # one-line in-character diary note


@dataclass
class RunLog:
    """The complete record for one nightly run."""

    date: date
    start_time: datetime
    end_time: datetime
    repo: str
    dry_run: bool
    events: list[RunEvent] = field(default_factory=list)

    # Convenience properties used by the diary template.

    @property
    def total_issues(self) -> int:
        return len(self.events)

    @property
    def total_prs(self) -> int:
        return sum(1 for e in self.events if e.outcome == "pr_opened")


# ---------------------------------------------------------------------------
# In-character notes
# ---------------------------------------------------------------------------

_NOTES: dict[str, str] = {
    "pr_opened": "slipped into the codebase, left a tidy fix, and vanished before dawn.",
    "test_failed": "tried valiantly but the tests refused to pass — left a note instead.",
    "timeout": "ran out of time before finishing the haunting.",
    "over_limit": "got a little carried away and touched too many files.",
    "skipped": "found this issue already claimed — drifted on to the next.",
    "agent_error": "encountered something unexpected and had to retreat.",
}


def _make_note(ghost_name: str, outcome: Outcome) -> str:
    return f"{ghost_name} {_NOTES.get(outcome, 'completed the night shift.')}"


# ---------------------------------------------------------------------------
# Single-issue runner (T-15)
# ---------------------------------------------------------------------------


def run_issue(
    issue: Issue,
    config: NightShiftConfig,
    ghost_name: str,
    *,
    default_branch: str = "main",
) -> RunEvent:
    """Process *issue* end-to-end and return a :class:`RunEvent`.

    Steps:
    1. Compute and check out a new branch.
    2. Run the kiro-cli agent.
    3. Check diff limits (file / line counts).
    4. Run the test command.
    5. Push + open PR (on success, non-dry-run), or post comment (on failure).
    6. Return to *default_branch*.

    Per-step failures are caught and recorded; the caller is not expected to
    handle exceptions from this function.  Any uncaught exception propagates
    to ``run_all``, which wraps it in an ``agent_error`` RunEvent.

    Parameters
    ----------
    issue:
        The GitHub issue to process.
    config:
        The active ``NightShiftConfig``.
    ghost_name:
        Name to assign in the diary (e.g. ``"Casper"``).
    default_branch:
        The branch to restore after processing (default ``"main"``).

    Returns
    -------
    RunEvent
    """
    import time

    start = time.monotonic()

    branch = make_branch_name(config.branch_prefix, issue.number, issue.title)

    # --- Step 1: branch preparation ---
    try:
        prepare_branch(branch)
    except BranchExistsError:
        return RunEvent(
            issue_number=issue.number,
            issue_title=issue.title,
            ghost_name=ghost_name,
            branch=branch,
            outcome="skipped",
            pr_url=None,
            diff_stats=None,
            test_output=None,
            agent_output=None,
            duration_seconds=round(time.monotonic() - start, 2),
            note=_make_note(ghost_name, "skipped"),
        )
    except (ValueError, ShellError) as exc:
        logger.error("Branch preparation failed for issue #%d: %s", issue.number, exc)
        return RunEvent(
            issue_number=issue.number,
            issue_title=issue.title,
            ghost_name=ghost_name,
            branch=branch,
            outcome="agent_error",
            pr_url=None,
            diff_stats=None,
            test_output=None,
            agent_output=str(exc)[:_MAX_SNIPPET],
            duration_seconds=round(time.monotonic() - start, 2),
            note=_make_note(ghost_name, "agent_error"),
        )

    # --- Step 2: run the agent ---
    agent_result = agent_module.run(issue, config.max_minutes)

    if agent_result.timed_out:
        _restore_branch(default_branch)
        return RunEvent(
            issue_number=issue.number,
            issue_title=issue.title,
            ghost_name=ghost_name,
            branch=branch,
            outcome="timeout",
            pr_url=None,
            diff_stats=None,
            test_output=None,
            agent_output=agent_result.output[:_MAX_SNIPPET],
            duration_seconds=round(time.monotonic() - start, 2),
            note=_make_note(ghost_name, "timeout"),
        )

    if not agent_result.success:
        _restore_branch(default_branch)
        return RunEvent(
            issue_number=issue.number,
            issue_title=issue.title,
            ghost_name=ghost_name,
            branch=branch,
            outcome="agent_error",
            pr_url=None,
            diff_stats=None,
            test_output=None,
            agent_output=agent_result.output[:_MAX_SNIPPET],
            duration_seconds=round(time.monotonic() - start, 2),
            note=_make_note(ghost_name, "agent_error"),
        )

    # --- Step 3: diff limit check ---
    try:
        diff_stats = check_diff_limits(config.max_files, config.max_lines)
    except OverLimitError as exc:
        logger.warning("Over-limit for issue #%d: %s", issue.number, exc)
        _post_comment_safe(
            issue.number,
            (
                f"🔴 **Night Shift — Over-limit ({ghost_name})**\n\n"
                f"The ghost touched too many files or lines:\n\n```\n{exc}\n```"
            ),
            dry_run=config.dry_run,
        )
        _restore_branch(default_branch)
        return RunEvent(
            issue_number=issue.number,
            issue_title=issue.title,
            ghost_name=ghost_name,
            branch=branch,
            outcome="over_limit",
            pr_url=None,
            diff_stats=exc.stats,
            test_output=None,
            agent_output=agent_result.output[:_MAX_SNIPPET],
            duration_seconds=round(time.monotonic() - start, 2),
            note=_make_note(ghost_name, "over_limit"),
        )

    # --- Step 4: run tests ---
    test_cmd = config.test_command.split() if isinstance(config.test_command, str) else config.test_command
    try:
        test_result = shell_run(test_cmd, check=False)
        tests_passed = test_result.returncode == 0
        test_output = test_result.output[:_MAX_SNIPPET]
    except Exception as exc:
        tests_passed = False
        test_output = str(exc)[:_MAX_SNIPPET]

    if not tests_passed:
        # Post comment with test output (AC-04.3)
        _post_comment_safe(
            issue.number,
            (
                f"🟡 **Night Shift — Tests failed ({ghost_name})**\n\n"
                f"The ghost attempted a fix on branch `{branch}` but the test suite "
                f"did not pass:\n\n```\n{test_output}\n```"
            ),
            dry_run=config.dry_run,
        )
        _restore_branch(default_branch)
        return RunEvent(
            issue_number=issue.number,
            issue_title=issue.title,
            ghost_name=ghost_name,
            branch=branch,
            outcome="test_failed",
            pr_url=None,
            diff_stats=diff_stats,
            test_output=test_output,
            agent_output=agent_result.output[:_MAX_SNIPPET],
            duration_seconds=round(time.monotonic() - start, 2),
            note=_make_note(ghost_name, "test_failed"),
        )

    # --- Step 5: open PR (or skip for dry_run) ---
    pr_url: str | None = None
    if not config.dry_run:
        try:
            pr_body = (
                f"Closes #{issue.number}\n\n"
                f"**Night Shift — {ghost_name}** worked on this overnight.\n\n"
                f"### Agent summary\n\n```\n{agent_result.output[:_MAX_SNIPPET]}\n```\n\n"
                f"### Test output\n\n```\n{test_output}\n```"
            )
            pr_url = github_module.open_pr(
                branch=branch,
                title=f"[Night Shift] #{issue.number}: {issue.title}",
                body=pr_body,
            )
            logger.info("Opened PR for issue #%d: %s", issue.number, pr_url)
        except (ShellError, Exception) as exc:
            logger.error("Failed to open PR for issue #%d: %s", issue.number, exc)
            # Record as test_failed rather than crashing the run (AC-05.4)
            _restore_branch(default_branch)
            return RunEvent(
                issue_number=issue.number,
                issue_title=issue.title,
                ghost_name=ghost_name,
                branch=branch,
                outcome="agent_error",
                pr_url=None,
                diff_stats=diff_stats,
                test_output=test_output,
                agent_output=agent_result.output[:_MAX_SNIPPET],
                duration_seconds=round(time.monotonic() - start, 2),
                note=_make_note(ghost_name, "agent_error"),
            )

    _restore_branch(default_branch)
    return RunEvent(
        issue_number=issue.number,
        issue_title=issue.title,
        ghost_name=ghost_name,
        branch=branch,
        outcome="pr_opened",
        pr_url=pr_url,
        diff_stats=diff_stats,
        test_output=test_output,
        agent_output=agent_result.output[:_MAX_SNIPPET],
        duration_seconds=round(time.monotonic() - start, 2),
        note=_make_note(ghost_name, "pr_opened"),
    )


# ---------------------------------------------------------------------------
# Full run (T-16)
# ---------------------------------------------------------------------------


def run_all(config: NightShiftConfig) -> RunLog:
    """Execute a complete nightly run and return a :class:`RunLog`.

    Steps:
    1. Fetch labeled issues (up to ``config.max_issues``).
    2. Determine repo name.
    3. For each issue, call ``run_issue`` (catching unexpected exceptions).
    4. Render the Ghost Diary.
    5. Return the ``RunLog``.

    Parameters
    ----------
    config:
        The active ``NightShiftConfig``.

    Returns
    -------
    RunLog
    """
    from nightshift import diary as diary_module

    start_time = datetime.now(timezone.utc)

    # Repo name (best-effort; fall back to "unknown")
    repo = _get_repo_name()

    # Determine default branch (best-effort)
    from nightshift.safety import _default_branch  # private but internal
    default_branch = _default_branch()

    # Fetch issues
    issues = github_module.list_labeled_issues(config.label, limit=100)
    issues = issues[: config.max_issues]

    if not issues:
        logger.info("No labeled issues found for label '%s'.", config.label)

    ghost_names = config.diary.ghost_names

    events: list[RunEvent] = []
    for idx, issue in enumerate(issues):
        ghost_name = ghost_names[issue.number % len(ghost_names)]
        logger.info(
            "Processing issue #%d '%s' (ghost: %s)",
            issue.number,
            issue.title,
            ghost_name,
        )
        try:
            event = run_issue(issue, config, ghost_name, default_branch=default_branch)
        except Exception as exc:
            logger.error(
                "Unexpected error processing issue #%d: %s\n%s",
                issue.number,
                exc,
                traceback.format_exc(),
            )
            event = RunEvent(
                issue_number=issue.number,
                issue_title=issue.title,
                ghost_name=ghost_name,
                branch=make_branch_name(config.branch_prefix, issue.number, issue.title),
                outcome="agent_error",
                pr_url=None,
                diff_stats=None,
                test_output=None,
                agent_output=traceback.format_exc()[:_MAX_SNIPPET],
                duration_seconds=0.0,
                note=_make_note(ghost_name, "agent_error"),
            )
        events.append(event)

    end_time = datetime.now(timezone.utc)

    run_log = RunLog(
        date=start_time.date(),
        start_time=start_time,
        end_time=end_time,
        repo=repo,
        dry_run=config.dry_run,
        events=events,
    )

    # Persist and render (T-17, T-19); errors here are non-fatal
    try:
        diary_module.save(run_log)
        diary_module.render(run_log)
    except Exception as exc:
        logger.warning("Diary write/render failed (non-fatal): %s", exc)

    return run_log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _restore_branch(branch: str) -> None:
    """Attempt to check out *branch*, logging any error."""
    try:
        shell_run(["git", "checkout", branch])
    except ShellError as exc:
        logger.warning("Could not restore branch '%s': %s", branch, exc)


def _post_comment_safe(issue_number: int, body: str, *, dry_run: bool) -> None:
    """Post *body* as a comment on *issue_number*, unless *dry_run* is True."""
    if dry_run:
        logger.info("[dry-run] Would post comment on issue #%d", issue_number)
        return
    try:
        github_module.comment_on_issue(issue_number, body)
    except Exception as exc:
        logger.warning("Failed to post comment on issue #%d: %s", issue_number, exc)


def _get_repo_name() -> str:
    """Return ``owner/repo`` via ``gh repo view``, or ``"unknown"`` on error."""
    try:
        result = shell_run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], check=False)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"
