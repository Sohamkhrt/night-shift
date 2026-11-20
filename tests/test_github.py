"""Tests for nightshift.github.

All tests mock ``nightshift.shell.run`` to avoid calling the real ``gh`` CLI.
This lets us:
  1. Assert the correct gh subcommands are constructed.
  2. Assert JSON parsing is correct.
  3. Test error paths without network access.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from nightshift.github import (
    GitHubAuthError,
    Issue,
    add_label,
    comment_on_issue,
    list_labeled_issues,
    open_pr,
    validate_auth,
)
from nightshift.shell import ShellError, ShellResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_shell_result(stdout: str = "", stderr: str = "", returncode: int = 0) -> ShellResult:
    return ShellResult(cmd=["gh"], returncode=returncode, stdout=stdout, stderr=stderr)


def gh_issues_json(issues: list[dict]) -> str:
    return json.dumps(issues)


_SAMPLE_ISSUE_DICT = {
    "number": 42,
    "title": "Fix the login bug",
    "body": "Users can't log in after the upgrade.",
    "labels": [{"name": "night-shift"}, {"name": "bug"}],
    "createdAt": "2024-10-31T01:00:00Z",
}

_SAMPLE_ISSUE_2_DICT = {
    "number": 7,
    "title": "Update README",
    "body": "README is outdated.",
    "labels": [{"name": "night-shift"}],
    "createdAt": "2024-10-30T00:00:00Z",  # older than issue 42
}


# ---------------------------------------------------------------------------
# Issue dataclass
# ---------------------------------------------------------------------------


class TestIssue:
    def test_str_representation(self) -> None:
        issue = Issue(
            number=42,
            title="Fix the login bug",
            body="...",
            labels=["bug"],
            created_at=datetime(2024, 10, 31, tzinfo=timezone.utc),
        )
        assert "#42" in str(issue)
        assert "Fix the login bug" in str(issue)

    def test_dataclass_fields(self) -> None:
        issue = Issue(
            number=1,
            title="T",
            body="B",
            labels=[],
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        assert issue.number == 1
        assert issue.title == "T"
        assert issue.body == "B"
        assert issue.labels == []


# ---------------------------------------------------------------------------
# validate_auth
# ---------------------------------------------------------------------------


class TestValidateAuth:
    @patch("nightshift.github.run")
    def test_success_calls_gh_auth_status(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result()
        validate_auth()
        mock_run.assert_called_once_with(["gh", "auth", "status"])

    @patch("nightshift.github.run")
    def test_shell_error_raises_github_auth_error(self, mock_run: MagicMock) -> None:
        bad_result = make_shell_result(returncode=1, stderr="not logged in")
        mock_run.side_effect = ShellError(bad_result)
        with pytest.raises(GitHubAuthError):
            validate_auth()

    @patch("nightshift.github.run")
    def test_error_message_helpful(self, mock_run: MagicMock) -> None:
        bad_result = make_shell_result(returncode=1, stderr="not logged in")
        mock_run.side_effect = ShellError(bad_result)
        with pytest.raises(GitHubAuthError) as exc_info:
            validate_auth()
        msg = str(exc_info.value)
        assert "gh auth login" in msg or "GH_TOKEN" in msg

    @patch("nightshift.github.run")
    def test_gh_not_found_raises_github_auth_error(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError("gh not found")
        with pytest.raises(GitHubAuthError):
            validate_auth()

    @patch("nightshift.github.run")
    def test_gh_not_found_message_mentions_install(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError("gh not found")
        with pytest.raises(GitHubAuthError) as exc_info:
            validate_auth()
        assert "cli.github.com" in str(exc_info.value) or "gh" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# list_labeled_issues
# ---------------------------------------------------------------------------


class TestListLabeledIssues:
    @patch("nightshift.github.run")
    def test_calls_gh_issue_list_with_label(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(stdout=gh_issues_json([_SAMPLE_ISSUE_DICT]))
        list_labeled_issues("night-shift")
        cmd = mock_run.call_args[0][0]
        assert "gh" in cmd
        assert "issue" in cmd
        assert "list" in cmd
        assert "--label" in cmd
        assert "night-shift" in cmd

    @patch("nightshift.github.run")
    def test_requests_json_fields(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(stdout=gh_issues_json([_SAMPLE_ISSUE_DICT]))
        list_labeled_issues("night-shift")
        cmd = mock_run.call_args[0][0]
        json_flag_idx = cmd.index("--json")
        fields_str = cmd[json_flag_idx + 1]
        for field in ("number", "title", "body", "labels", "createdAt"):
            assert field in fields_str

    @patch("nightshift.github.run")
    def test_parses_issue_number(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(stdout=gh_issues_json([_SAMPLE_ISSUE_DICT]))
        issues = list_labeled_issues("night-shift")
        assert issues[0].number == 42

    @patch("nightshift.github.run")
    def test_parses_issue_title(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(stdout=gh_issues_json([_SAMPLE_ISSUE_DICT]))
        issues = list_labeled_issues("night-shift")
        assert issues[0].title == "Fix the login bug"

    @patch("nightshift.github.run")
    def test_parses_issue_body(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(stdout=gh_issues_json([_SAMPLE_ISSUE_DICT]))
        issues = list_labeled_issues("night-shift")
        assert "log in" in issues[0].body

    @patch("nightshift.github.run")
    def test_parses_label_names(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(stdout=gh_issues_json([_SAMPLE_ISSUE_DICT]))
        issues = list_labeled_issues("night-shift")
        assert "night-shift" in issues[0].labels
        assert "bug" in issues[0].labels

    @patch("nightshift.github.run")
    def test_parses_created_at_as_datetime(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(stdout=gh_issues_json([_SAMPLE_ISSUE_DICT]))
        issues = list_labeled_issues("night-shift")
        assert isinstance(issues[0].created_at, datetime)
        assert issues[0].created_at.year == 2024

    @patch("nightshift.github.run")
    def test_returns_list_of_issues(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(stdout=gh_issues_json([_SAMPLE_ISSUE_DICT]))
        issues = list_labeled_issues("night-shift")
        assert isinstance(issues, list)
        assert all(isinstance(i, Issue) for i in issues)

    @patch("nightshift.github.run")
    def test_empty_list_when_no_issues(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(stdout=gh_issues_json([]))
        issues = list_labeled_issues("night-shift")
        assert issues == []

    @patch("nightshift.github.run")
    def test_sorted_oldest_first(self, mock_run: MagicMock) -> None:
        # issue 42 created later than issue 7
        mock_run.return_value = make_shell_result(
            stdout=gh_issues_json([_SAMPLE_ISSUE_DICT, _SAMPLE_ISSUE_2_DICT])
        )
        issues = list_labeled_issues("night-shift")
        # Oldest (issue 7) should come first
        assert issues[0].number == 7
        assert issues[1].number == 42

    @patch("nightshift.github.run")
    def test_limit_passed_to_command(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(stdout=gh_issues_json([]))
        list_labeled_issues("night-shift", limit=25)
        cmd = mock_run.call_args[0][0]
        assert "--limit" in cmd
        limit_idx = cmd.index("--limit")
        assert cmd[limit_idx + 1] == "25"

    @patch("nightshift.github.run")
    def test_null_body_becomes_empty_string(self, mock_run: MagicMock) -> None:
        issue_dict = {**_SAMPLE_ISSUE_DICT, "body": None}
        mock_run.return_value = make_shell_result(stdout=gh_issues_json([issue_dict]))
        issues = list_labeled_issues("night-shift")
        assert issues[0].body == ""


# ---------------------------------------------------------------------------
# comment_on_issue
# ---------------------------------------------------------------------------


class TestCommentOnIssue:
    @patch("nightshift.github.run")
    def test_calls_gh_issue_comment(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result()
        comment_on_issue(42, "Test failed.")
        cmd = mock_run.call_args[0][0]
        assert "gh" in cmd
        assert "issue" in cmd
        assert "comment" in cmd

    @patch("nightshift.github.run")
    def test_passes_issue_number(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result()
        comment_on_issue(42, "Some body")
        cmd = mock_run.call_args[0][0]
        assert "42" in cmd

    @patch("nightshift.github.run")
    def test_passes_body(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result()
        comment_on_issue(42, "Night Shift failed.")
        cmd = mock_run.call_args[0][0]
        assert "--body" in cmd
        body_idx = cmd.index("--body")
        assert cmd[body_idx + 1] == "Night Shift failed."

    @patch("nightshift.github.run")
    def test_shell_error_propagates(self, mock_run: MagicMock) -> None:
        bad_result = make_shell_result(returncode=1)
        mock_run.side_effect = ShellError(bad_result)
        with pytest.raises(ShellError):
            comment_on_issue(1, "body")


# ---------------------------------------------------------------------------
# open_pr
# ---------------------------------------------------------------------------


class TestOpenPr:
    @patch("nightshift.github.run")
    def test_pushes_branch_first(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(
            stdout="https://github.com/owner/repo/pull/99\n"
        )
        open_pr("night-shift/42-fix", "Fix #42", "Closes #42")
        # First call must be git push
        first_call = mock_run.call_args_list[0]
        cmd = first_call[0][0]
        assert "git" in cmd
        assert "push" in cmd

    @patch("nightshift.github.run")
    def test_calls_gh_pr_create(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(
            stdout="https://github.com/owner/repo/pull/99\n"
        )
        open_pr("night-shift/42-fix", "Fix #42", "Closes #42")
        commands = [call[0][0] for call in mock_run.call_args_list]
        pr_create_cmd = next(c for c in commands if "pr" in c and "create" in c)
        assert "gh" in pr_create_cmd
        assert "pr" in pr_create_cmd
        assert "create" in pr_create_cmd

    @patch("nightshift.github.run")
    def test_passes_title(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(
            stdout="https://github.com/owner/repo/pull/99\n"
        )
        open_pr("branch", "My Title", "body")
        commands = [call[0][0] for call in mock_run.call_args_list]
        pr_create_cmd = next(c for c in commands if "pr" in c and "create" in c)
        assert "--title" in pr_create_cmd
        title_idx = pr_create_cmd.index("--title")
        assert pr_create_cmd[title_idx + 1] == "My Title"

    @patch("nightshift.github.run")
    def test_returns_pr_url(self, mock_run: MagicMock) -> None:
        url = "https://github.com/owner/repo/pull/99"
        mock_run.return_value = make_shell_result(stdout=url + "\n")
        result = open_pr("branch", "title", "body")
        assert result == url

    @patch("nightshift.github.run")
    def test_passes_head_branch(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(
            stdout="https://github.com/owner/repo/pull/1\n"
        )
        open_pr("night-shift/42-fix", "title", "body")
        commands = [call[0][0] for call in mock_run.call_args_list]
        pr_create_cmd = next(c for c in commands if "pr" in c and "create" in c)
        assert "--head" in pr_create_cmd
        head_idx = pr_create_cmd.index("--head")
        assert pr_create_cmd[head_idx + 1] == "night-shift/42-fix"


# ---------------------------------------------------------------------------
# add_label
# ---------------------------------------------------------------------------


class TestAddLabel:
    @patch("nightshift.github.run")
    def test_calls_gh_pr_edit(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result()
        add_label(99, "night-shift-pr")
        cmd = mock_run.call_args[0][0]
        assert "gh" in cmd
        assert "pr" in cmd
        assert "edit" in cmd

    @patch("nightshift.github.run")
    def test_passes_pr_number(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result()
        add_label(99, "night-shift-pr")
        cmd = mock_run.call_args[0][0]
        assert "99" in cmd

    @patch("nightshift.github.run")
    def test_passes_label_name(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result()
        add_label(99, "night-shift-pr")
        cmd = mock_run.call_args[0][0]
        assert "--add-label" in cmd
        label_idx = cmd.index("--add-label")
        assert cmd[label_idx + 1] == "night-shift-pr"

    @patch("nightshift.github.run")
    def test_shell_error_propagates(self, mock_run: MagicMock) -> None:
        bad_result = make_shell_result(returncode=1)
        mock_run.side_effect = ShellError(bad_result)
        with pytest.raises(ShellError):
            add_label(1, "label")
