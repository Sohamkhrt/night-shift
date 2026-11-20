"""safety.py — branch naming, change limits, and dry-run enforcement.

Design decisions (see design.md Decisions section):
- ``make_branch_name`` is a pure function (no I/O) so it can be tested with
  Hypothesis without any subprocess mocking.
- ``prepare_branch`` checks ``git branch --list`` rather than ``git show-ref``
  because it works identically on all platforms without additional parsing.
- ``check_diff_limits`` parses ``git diff --stat HEAD`` rather than
  ``--staged`` because we want to capture all uncommitted changes after the
  agent runs (the agent may or may not stage its changes).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from nightshift.shell import ShellError, run

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROTECTED_BRANCHES = {"main", "master"}
_MAX_SLUG_LENGTH = 40


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class DiffStats:
    """Line and file counts from ``git diff --stat``."""

    files_changed: int
    lines_added: int
    lines_removed: int

    @property
    def total_lines(self) -> int:
        return self.lines_added + self.lines_removed


class OverLimitError(ValueError):
    """Raised when ``check_diff_limits`` finds the agent exceeded a limit."""

    def __init__(self, stats: DiffStats, max_files: int, max_lines: int) -> None:
        self.stats = stats
        self.max_files = max_files
        self.max_lines = max_lines
        reasons: list[str] = []
        if stats.files_changed > max_files:
            reasons.append(
                f"{stats.files_changed} files changed (limit: {max_files})"
            )
        if stats.total_lines > max_lines:
            reasons.append(
                f"{stats.total_lines} lines changed (limit: {max_lines})"
            )
        super().__init__(
            "Agent exceeded change limits: " + "; ".join(reasons)
        )


# ---------------------------------------------------------------------------
# Branch naming (pure — no I/O)
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Convert *text* to a lowercase, hyphen-separated git-ref-safe slug.

    Rules applied in order:
    1. Lowercase.
    2. Replace any character that is not alphanumeric or hyphen with a hyphen.
    3. Collapse consecutive hyphens to one.
    4. Strip leading and trailing hyphens.
    5. Truncate to ``_MAX_SLUG_LENGTH`` characters.
    6. If the result is empty after sanitisation, fall back to ``"issue"``.
    """
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    slug = slug[:_MAX_SLUG_LENGTH]
    slug = slug.strip("-")  # strip again after truncation
    return slug or "issue"


def make_branch_name(prefix: str, issue_number: int, issue_title: str) -> str:
    """Return a git branch name for *issue_number* with the given *prefix*.

    The name has the form::

        {prefix}{issue_number}-{slug}

    where *slug* is a sanitised, lowercase, hyphen-separated version of
    *issue_title*, truncated to ``_MAX_SLUG_LENGTH`` characters.

    This function is **pure**: it has no side effects and always returns the
    same result for the same inputs.  It is designed to be tested with
    Hypothesis.

    Parameters
    ----------
    prefix:
        Branch prefix, e.g. ``"night-shift/"``.
    issue_number:
        GitHub issue number.
    issue_title:
        Issue title (may contain arbitrary Unicode).

    Returns
    -------
    str
        A valid git ref name that is safe to push to GitHub.
    """
    slug = _slugify(issue_title)
    branch = f"{prefix}{issue_number}-{slug}"
    return branch


# ---------------------------------------------------------------------------
# Branch preparation (requires git)
# ---------------------------------------------------------------------------


class BranchExistsError(RuntimeError):
    """Raised when a branch with the target name already exists locally."""

    def __init__(self, branch: str) -> None:
        self.branch = branch
        super().__init__(
            f"Branch '{branch}' already exists. "
            "Skipping this issue to avoid overwriting previous work."
        )


def _default_branch() -> str:
    """Return the name of the default branch (main or master)."""
    try:
        result = run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            check=False,
        )
        if result.returncode == 0:
            # e.g. "refs/remotes/origin/main\n"
            return result.stdout.strip().split("/")[-1]
    except Exception:
        pass

    # Fall back: check whether 'main' or 'master' exists
    for name in ("main", "master"):
        result = run(["git", "branch", "--list", name], check=False)
        if result.stdout.strip():
            return name

    return "main"


def prepare_branch(branch_name: str) -> str:
    """Check out a new branch *branch_name* from the current HEAD.

    Before creating, verifies:
    - The branch name is not a protected branch (``main`` / ``master``).
    - No local branch with *branch_name* already exists.

    Parameters
    ----------
    branch_name:
        The full branch name (output of :func:`make_branch_name`).

    Returns
    -------
    str
        The branch name on success.

    Raises
    ------
    ValueError
        If *branch_name* would overwrite a protected branch.
    BranchExistsError
        If a branch with *branch_name* already exists locally.
    ShellError
        If ``git checkout -b`` fails for another reason.
    """
    base = branch_name.split("/")[-1] if "/" in branch_name else branch_name
    if base in _PROTECTED_BRANCHES or branch_name in _PROTECTED_BRANCHES:
        raise ValueError(
            f"Refusing to create branch '{branch_name}': "
            "Night Shift never pushes to main or master."
        )

    # Check for existing local branch
    result = run(["git", "branch", "--list", branch_name], check=False)
    if result.stdout.strip():
        raise BranchExistsError(branch_name)

    run(["git", "checkout", "-b", branch_name])
    logger.info("Created and checked out branch '%s'", branch_name)
    return branch_name


# ---------------------------------------------------------------------------
# Diff limit checking
# ---------------------------------------------------------------------------


def _parse_diff_stat(stat_output: str) -> DiffStats:
    """Parse the summary line from ``git diff --stat``.

    The summary line looks like::

        3 files changed, 42 insertions(+), 7 deletions(-)

    or for a single file::

        1 file changed, 5 insertions(+)

    Returns :class:`DiffStats` with counts (0 if a component is absent).
    """
    if not stat_output.strip():
        return DiffStats(files_changed=0, lines_added=0, lines_removed=0)

    # Find the summary line — it's the last non-empty line
    lines = [l for l in stat_output.splitlines() if l.strip()]
    summary = lines[-1]

    files_changed = 0
    lines_added = 0
    lines_removed = 0

    m = re.search(r"(\d+) files? changed", summary)
    if m:
        files_changed = int(m.group(1))

    m = re.search(r"(\d+) insertions?\(\+\)", summary)
    if m:
        lines_added = int(m.group(1))

    m = re.search(r"(\d+) deletions?\(-\)", summary)
    if m:
        lines_removed = int(m.group(1))

    return DiffStats(
        files_changed=files_changed,
        lines_added=lines_added,
        lines_removed=lines_removed,
    )


def check_diff_limits(max_files: int, max_lines: int) -> DiffStats:
    """Run ``git diff --stat HEAD`` and enforce *max_files* / *max_lines*.

    Parameters
    ----------
    max_files:
        Maximum number of files the agent is allowed to change.
    max_lines:
        Maximum total lines (insertions + deletions) allowed.

    Returns
    -------
    DiffStats
        The actual diff statistics.

    Raises
    ------
    OverLimitError
        If either limit is exceeded.
    """
    result = run(["git", "diff", "--stat", "HEAD"])
    stats = _parse_diff_stat(result.stdout)

    logger.info(
        "Diff stats: %d files, %d insertions, %d deletions",
        stats.files_changed,
        stats.lines_added,
        stats.lines_removed,
    )

    if stats.files_changed > max_files or stats.total_lines > max_lines:
        raise OverLimitError(stats, max_files, max_lines)

    return stats
