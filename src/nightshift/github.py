"""github.py — thin wrapper around the ``gh`` CLI.

All GitHub operations go through the ``gh`` CLI, which manages authentication.
No direct REST or GraphQL calls.  Every public function in this module calls
``shell.run()`` internally and parses JSON output from ``gh ... --json``.

Required ``gh`` commands:
  gh auth status
  gh issue list --json
  gh issue comment
  gh pr create
  gh pr edit

Authentication: run ``gh auth login`` once, or set ``GH_TOKEN`` in the
environment before invoking Night Shift.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from nightshift.shell import ShellError, run

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Issue:
    """A GitHub issue returned by ``gh issue list``."""

    number: int
    title: str
    body: str
    labels: list[str]
    created_at: datetime

    def __str__(self) -> str:
        return f"#{self.number}: {self.title}"


# ---------------------------------------------------------------------------
# Auth validation
# ---------------------------------------------------------------------------


class GitHubAuthError(RuntimeError):
    """Raised when ``gh auth status`` indicates the user is not authenticated."""


def validate_auth() -> None:
    """Confirm that ``gh auth status`` succeeds.

    Raises
    ------
    GitHubAuthError
        When the ``gh`` CLI is not authenticated or not installed.
    """
    try:
        run(["gh", "auth", "status"])
    except ShellError as exc:
        raise GitHubAuthError(
            "GitHub CLI is not authenticated.  "
            "Run `gh auth login` or set the GH_TOKEN environment variable, "
            "then try again.\n"
            f"Details: {exc}"
        ) from exc
    except FileNotFoundError:
        raise GitHubAuthError(
            "The `gh` CLI was not found on PATH.  "
            "Install it from https://cli.github.com/ and authenticate with `gh auth login`."
        )


# ---------------------------------------------------------------------------
# Issue operations
# ---------------------------------------------------------------------------


def list_labeled_issues(label: str, limit: int = 100) -> list[Issue]:
    """Return open issues carrying *label*, sorted oldest-first.

    Parameters
    ----------
    label:
        The GitHub label to filter by.
    limit:
        Maximum number of issues to fetch from the API.  The caller is
        responsible for applying ``max_issues`` on top of this.

    Returns
    -------
    list[Issue]
        Issues sorted by ``created_at`` ascending (oldest first).
    """
    result = run(
        [
            "gh",
            "issue",
            "list",
            "--label",
            label,
            "--limit",
            str(limit),
            "--state",
            "open",
            "--json",
            "number,title,body,labels,createdAt",
        ]
    )

    raw_issues: list[dict] = json.loads(result.stdout)
    issues: list[Issue] = []
    for item in raw_issues:
        label_names = [lb["name"] for lb in item.get("labels", [])]
        created_at = datetime.fromisoformat(
            item["createdAt"].replace("Z", "+00:00")
        )
        issues.append(
            Issue(
                number=item["number"],
                title=item["title"],
                body=item.get("body") or "",
                labels=label_names,
                created_at=created_at,
            )
        )

    # Oldest first so ``max_issues`` slicing picks the most stale issues
    issues.sort(key=lambda i: i.created_at)
    return issues


def comment_on_issue(issue_number: int, body: str) -> None:
    """Post *body* as a comment on the given issue.

    Parameters
    ----------
    issue_number:
        The GitHub issue number (not the node ID).
    body:
        Markdown text of the comment.
    """
    run(
        [
            "gh",
            "issue",
            "comment",
            str(issue_number),
            "--body",
            body,
        ]
    )
    logger.info("Posted comment on issue #%d", issue_number)


# ---------------------------------------------------------------------------
# Pull-request operations
# ---------------------------------------------------------------------------


def open_pr(branch: str, title: str, body: str) -> str:
    """Push *branch* and open a pull request.

    The branch must already exist locally.  This function pushes it to
    ``origin`` and then calls ``gh pr create``.

    Parameters
    ----------
    branch:
        Local branch name (e.g. ``"night-shift/42-fix-login-bug"``).
    title:
        PR title shown in GitHub.
    body:
        PR body in Markdown.  Should include ``Closes #{issue_number}``.

    Returns
    -------
    str
        The URL of the newly created pull request.
    """
    # Push the branch first
    run(["git", "push", "origin", branch])

    result = run(
        [
            "gh",
            "pr",
            "create",
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
        ]
    )
    pr_url = result.stdout.strip()
    logger.info("Opened PR: %s", pr_url)
    return pr_url


def add_label(pr_number: int, label: str) -> None:
    """Add *label* to an existing pull request.

    Parameters
    ----------
    pr_number:
        The GitHub pull-request number.
    label:
        Label name to apply.  The label must already exist in the repo.
    """
    run(
        [
            "gh",
            "pr",
            "edit",
            str(pr_number),
            "--add-label",
            label,
        ]
    )
    logger.info("Added label '%s' to PR #%d", label, pr_number)
