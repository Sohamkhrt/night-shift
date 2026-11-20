"""Tests for nightshift.agent.

Coverage:
  T-13 — build_prompt: unit tests (prompt contains issue number, title, body).
  T-14 — run(): normal exit, non-zero exit, TimeoutExpired.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from nightshift.agent import AgentResult, build_prompt, run
from nightshift.github import Issue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_issue(
    number: int = 42,
    title: str = "Fix the login bug",
    body: str = "Users cannot log in when the session expires.",
    labels: list[str] | None = None,
) -> Issue:
    return Issue(
        number=number,
        title=title,
        body=body,
        labels=["night-shift"] if labels is None else labels,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# T-13 — build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_contains_issue_number(self) -> None:
        issue = make_issue(number=42)
        prompt = build_prompt(issue)
        assert "42" in prompt

    def test_contains_issue_title(self) -> None:
        issue = make_issue(title="Fix the login bug")
        prompt = build_prompt(issue)
        assert "Fix the login bug" in prompt

    def test_contains_issue_body(self) -> None:
        issue = make_issue(body="Users cannot log in when the session expires.")
        prompt = build_prompt(issue)
        assert "Users cannot log in when the session expires." in prompt

    def test_contains_labels(self) -> None:
        issue = make_issue(labels=["night-shift", "bug"])
        prompt = build_prompt(issue)
        assert "night-shift" in prompt
        assert "bug" in prompt

    def test_no_labels_shows_none(self) -> None:
        issue = make_issue(labels=[])
        prompt = build_prompt(issue)
        assert "(none)" in prompt

    def test_empty_body_shows_fallback(self) -> None:
        issue = make_issue(body="")
        prompt = build_prompt(issue)
        assert "(no body)" in prompt

    def test_none_body_shows_fallback(self) -> None:
        # Issue.body is a str, but guard against None for robustness
        issue = make_issue(body="")
        prompt = build_prompt(issue)
        assert "(no body)" in prompt

    def test_prompt_is_string(self) -> None:
        issue = make_issue()
        prompt = build_prompt(issue)
        assert isinstance(prompt, str)

    def test_prompt_format_number_in_header(self) -> None:
        issue = make_issue(number=99, title="A title")
        prompt = build_prompt(issue)
        assert "Issue #99" in prompt

    def test_different_issues_produce_different_prompts(self) -> None:
        p1 = build_prompt(make_issue(number=1, title="One"))
        p2 = build_prompt(make_issue(number=2, title="Two"))
        assert p1 != p2

    def test_prompt_contains_instruction(self) -> None:
        issue = make_issue()
        prompt = build_prompt(issue)
        # The prompt must ask the agent to implement something
        lower = prompt.lower()
        assert "implement" in lower or "fix" in lower or "satisfy" in lower


# ---------------------------------------------------------------------------
# T-14 — run(): normal exit
# ---------------------------------------------------------------------------


class TestAgentRunSuccess:
    @patch("nightshift.agent.subprocess.run")
    def test_returns_agent_result(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Done.",
            stderr="",
        )
        result = run(make_issue(), max_minutes=1)
        assert isinstance(result, AgentResult)

    @patch("nightshift.agent.subprocess.run")
    def test_success_true_on_zero_exit(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        result = run(make_issue(), max_minutes=1)
        assert result.success is True

    @patch("nightshift.agent.subprocess.run")
    def test_timed_out_false_on_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        result = run(make_issue(), max_minutes=1)
        assert result.timed_out is False

    @patch("nightshift.agent.subprocess.run")
    def test_output_captured(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="agent output here", stderr="")
        result = run(make_issue(), max_minutes=1)
        assert "agent output here" in result.output

    @patch("nightshift.agent.subprocess.run")
    def test_stderr_appended_to_output(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="stdout", stderr="stderr line")
        result = run(make_issue(), max_minutes=1)
        assert "stderr line" in result.output

    @patch("nightshift.agent.subprocess.run")
    def test_duration_seconds_positive(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = run(make_issue(), max_minutes=1)
        assert result.duration_seconds >= 0.0

    @patch("nightshift.agent.subprocess.run")
    def test_output_truncated_to_10k(self, mock_run: MagicMock) -> None:
        big = "x" * 20_000
        mock_run.return_value = MagicMock(returncode=0, stdout=big, stderr="")
        result = run(make_issue(), max_minutes=1)
        assert len(result.output) <= 10_000

    @patch("nightshift.agent.subprocess.run")
    def test_timeout_passed_to_subprocess(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        run(make_issue(), max_minutes=5)
        _, kwargs = mock_run.call_args
        assert kwargs.get("timeout") == 5 * 60

    @patch("nightshift.agent.subprocess.run")
    def test_command_is_kiro_cli(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        run(make_issue(), max_minutes=1)
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "kiro-cli"
        assert "chat" in cmd
        assert "--no-interactive" in cmd

    @patch("nightshift.agent.subprocess.run")
    def test_prompt_sent_as_input(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        issue = make_issue(number=7, title="My issue")
        run(issue, max_minutes=1)
        _, kwargs = mock_run.call_args
        sent_input = kwargs.get("input", "")
        assert "7" in sent_input
        assert "My issue" in sent_input


# ---------------------------------------------------------------------------
# T-14 — run(): non-zero exit
# ---------------------------------------------------------------------------


class TestAgentRunFailure:
    @patch("nightshift.agent.subprocess.run")
    def test_success_false_on_nonzero_exit(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="partial output", stderr="error")
        result = run(make_issue(), max_minutes=1)
        assert result.success is False

    @patch("nightshift.agent.subprocess.run")
    def test_timed_out_false_on_nonzero_exit(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        result = run(make_issue(), max_minutes=1)
        assert result.timed_out is False

    @patch("nightshift.agent.subprocess.run")
    def test_output_captured_on_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=2, stdout="some stdout", stderr="some stderr")
        result = run(make_issue(), max_minutes=1)
        assert "some stdout" in result.output

    @patch("nightshift.agent.subprocess.run")
    def test_does_not_raise_on_nonzero_exit(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=99, stdout="", stderr="")
        # Must not raise — caller reads result.success
        result = run(make_issue(), max_minutes=1)
        assert result is not None


# ---------------------------------------------------------------------------
# T-14 — run(): TimeoutExpired
# ---------------------------------------------------------------------------


class TestAgentRunTimeout:
    @patch("nightshift.agent.subprocess.run")
    def test_timed_out_true_on_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["kiro-cli", "chat", "--no-interactive"],
            timeout=60,
            output=None,
            stderr=None,
        )
        result = run(make_issue(), max_minutes=1)
        assert result.timed_out is True

    @patch("nightshift.agent.subprocess.run")
    def test_success_false_on_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["kiro-cli"],
            timeout=60,
            output=None,
            stderr=None,
        )
        result = run(make_issue(), max_minutes=1)
        assert result.success is False

    @patch("nightshift.agent.subprocess.run")
    def test_does_not_raise_on_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["kiro-cli"],
            timeout=60,
            output=None,
            stderr=None,
        )
        # Must not propagate TimeoutExpired — it is caught internally
        result = run(make_issue(), max_minutes=1)
        assert result is not None

    @patch("nightshift.agent.subprocess.run")
    def test_partial_output_captured_on_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["kiro-cli"],
            timeout=60,
            output="partial stdout",
            stderr="partial stderr",
        )
        result = run(make_issue(), max_minutes=1)
        assert "partial stdout" in result.output

    @patch("nightshift.agent.subprocess.run")
    def test_duration_set_on_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["kiro-cli"],
            timeout=60,
            output=None,
            stderr=None,
        )
        result = run(make_issue(), max_minutes=1)
        assert result.duration_seconds >= 0.0
