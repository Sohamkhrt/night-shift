"""Tests for nightshift.safety.

Coverage:
  T-10 — make_branch_name: unit + property-based tests
  T-11 — prepare_branch: unit tests with mocked shell.run
  T-12 — check_diff_limits / _parse_diff_stat: unit + property-based tests
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, call, patch

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from nightshift.safety import (
    BranchExistsError,
    DiffStats,
    OverLimitError,
    _parse_diff_stat,
    _slugify,
    check_diff_limits,
    make_branch_name,
    prepare_branch,
)
from nightshift.shell import ShellError, ShellResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_shell_result(stdout: str = "", returncode: int = 0) -> ShellResult:
    return ShellResult(cmd=["git"], returncode=returncode, stdout=stdout, stderr="")


# ---------------------------------------------------------------------------
# T-10 — make_branch_name / _slugify: unit tests
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_lowercase(self) -> None:
        assert _slugify("UPPERCASE") == "uppercase"

    def test_spaces_become_hyphens(self) -> None:
        assert _slugify("fix the bug") == "fix-the-bug"

    def test_consecutive_spaces_collapse(self) -> None:
        assert _slugify("fix   the   bug") == "fix-the-bug"

    def test_special_chars_become_hyphens(self) -> None:
        slug = _slugify("fix: bug (critical)!")
        assert " " not in slug
        assert "(" not in slug
        assert ":" not in slug

    def test_no_leading_hyphen(self) -> None:
        slug = _slugify("   leading spaces")
        assert not slug.startswith("-")

    def test_no_trailing_hyphen(self) -> None:
        slug = _slugify("trailing spaces   ")
        assert not slug.endswith("-")

    def test_truncates_to_max_length(self) -> None:
        long_title = "a" * 100
        slug = _slugify(long_title)
        assert len(slug) <= 40

    def test_empty_string_fallback(self) -> None:
        slug = _slugify("")
        assert slug == "issue"

    def test_only_special_chars_fallback(self) -> None:
        slug = _slugify("!@#$%")
        assert slug == "issue"


class TestMakeBranchName:
    def test_basic_branch_name(self) -> None:
        name = make_branch_name("night-shift/", 42, "Fix the login bug")
        assert name == "night-shift/42-fix-the-login-bug"

    def test_contains_prefix(self) -> None:
        name = make_branch_name("bot/", 1, "title")
        assert name.startswith("bot/")

    def test_contains_issue_number(self) -> None:
        name = make_branch_name("ns/", 99, "some title")
        assert "99" in name

    def test_slug_is_lowercase(self) -> None:
        name = make_branch_name("ns/", 1, "UPPERCASE TITLE")
        # Everything after the prefix should be lowercase
        assert name == name.lower()

    def test_no_spaces(self) -> None:
        name = make_branch_name("ns/", 1, "has spaces in title")
        assert " " not in name

    def test_idempotent_same_input_same_output(self) -> None:
        name1 = make_branch_name("ns/", 42, "Fix login bug")
        name2 = make_branch_name("ns/", 42, "Fix login bug")
        assert name1 == name2

    def test_different_issues_different_names(self) -> None:
        n1 = make_branch_name("ns/", 1, "Same title")
        n2 = make_branch_name("ns/", 2, "Same title")
        assert n1 != n2

    def test_unicode_title_no_error(self) -> None:
        name = make_branch_name("ns/", 1, "Ünïcödé títlé")
        assert isinstance(name, str)
        assert len(name) > 0


# ---------------------------------------------------------------------------
# T-10 — Property-based tests for make_branch_name
# ---------------------------------------------------------------------------

_title_strategy = st.text(min_size=0, max_size=200)
_prefix_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="-/"),
    min_size=1,
    max_size=20,
)
_issue_number_strategy = st.integers(min_value=1, max_value=999_999)

# Regex for a reasonable git ref: no spaces, no .., no ^, no ~, no :, no \
_GIT_REF_FORBIDDEN = re.compile(r"[\s\.]{2}|[\^~: \\]|\.lock$|@\{|^-")


def is_valid_git_ref(ref: str) -> bool:
    """Return True if *ref* looks like a valid git branch name."""
    if not ref:
        return False
    if ref.startswith("-"):
        return False
    if ".." in ref:
        return False
    if " " in ref:
        return False
    return True


@settings(max_examples=200)
@given(
    prefix=_prefix_strategy,
    number=_issue_number_strategy,
    title=_title_strategy,
)
def test_make_branch_name_never_equals_main(prefix: str, number: int, title: str) -> None:
    """make_branch_name must never produce 'main' or 'master'."""
    name = make_branch_name(prefix, number, title)
    assert name != "main"
    assert name != "master"


@settings(max_examples=200)
@given(
    prefix=_prefix_strategy,
    number=_issue_number_strategy,
    title=_title_strategy,
)
def test_make_branch_name_no_spaces(prefix: str, number: int, title: str) -> None:
    """Branch names must never contain spaces."""
    name = make_branch_name(prefix, number, title)
    assert " " not in name


@settings(max_examples=200)
@given(
    prefix=_prefix_strategy,
    number=_issue_number_strategy,
    title=_title_strategy,
)
def test_make_branch_name_no_double_dots(prefix: str, number: int, title: str) -> None:
    """Branch names must not contain '..' (invalid git ref)."""
    name = make_branch_name(prefix, number, title)
    assert ".." not in name


@settings(max_examples=200)
@given(
    prefix=_prefix_strategy,
    number=_issue_number_strategy,
    title=_title_strategy,
)
def test_make_branch_name_idempotent(prefix: str, number: int, title: str) -> None:
    """Calling make_branch_name twice with the same input gives the same result."""
    name1 = make_branch_name(prefix, number, title)
    name2 = make_branch_name(prefix, number, title)
    assert name1 == name2


@settings(max_examples=200)
@given(
    prefix=_prefix_strategy,
    number=_issue_number_strategy,
    title=_title_strategy,
)
def test_make_branch_name_contains_number(prefix: str, number: int, title: str) -> None:
    """The issue number must appear in the branch name."""
    name = make_branch_name(prefix, number, title)
    assert str(number) in name


@settings(max_examples=200)
@given(
    prefix=_prefix_strategy,
    number=_issue_number_strategy,
    title=_title_strategy,
)
def test_make_branch_name_starts_with_prefix(prefix: str, number: int, title: str) -> None:
    """Branch name must start with the given prefix."""
    name = make_branch_name(prefix, number, title)
    assert name.startswith(prefix)


# ---------------------------------------------------------------------------
# T-11 — prepare_branch: unit tests
# ---------------------------------------------------------------------------


class TestPrepareBranch:
    @patch("nightshift.safety.run")
    def test_creates_new_branch(self, mock_run: MagicMock) -> None:
        # First call: git branch --list → empty (branch doesn't exist)
        # Second call: git checkout -b → success
        mock_run.side_effect = [
            make_shell_result(stdout=""),           # git branch --list
            make_shell_result(stdout=""),           # git checkout -b
        ]
        result = prepare_branch("night-shift/42-fix-bug")
        assert result == "night-shift/42-fix-bug"

    @patch("nightshift.safety.run")
    def test_calls_git_checkout_b(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            make_shell_result(stdout=""),
            make_shell_result(stdout=""),
        ]
        prepare_branch("night-shift/42-fix-bug")
        checkout_call = mock_run.call_args_list[1]
        cmd = checkout_call[0][0]
        assert "git" in cmd
        assert "checkout" in cmd
        assert "-b" in cmd
        assert "night-shift/42-fix-bug" in cmd

    @patch("nightshift.safety.run")
    def test_raises_branch_exists_error_when_branch_exists(self, mock_run: MagicMock) -> None:
        # git branch --list returns the branch name → it exists
        mock_run.return_value = make_shell_result(
            stdout="  night-shift/42-fix-bug\n"
        )
        with pytest.raises(BranchExistsError):
            prepare_branch("night-shift/42-fix-bug")

    @patch("nightshift.safety.run")
    def test_does_not_create_branch_if_exists(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(stdout="  night-shift/42-fix-bug\n")
        with pytest.raises(BranchExistsError):
            prepare_branch("night-shift/42-fix-bug")
        # Only one call should be made (git branch --list), no checkout
        assert mock_run.call_count == 1

    def test_refuses_main_branch(self) -> None:
        with pytest.raises(ValueError, match="main|master"):
            prepare_branch("main")

    def test_refuses_master_branch(self) -> None:
        with pytest.raises(ValueError, match="main|master"):
            prepare_branch("master")

    @patch("nightshift.safety.run")
    def test_shell_error_propagates_from_checkout(self, mock_run: MagicMock) -> None:
        bad_result = ShellResult(cmd=["git"], returncode=1, stdout="", stderr="fatal")
        mock_run.side_effect = [
            make_shell_result(stdout=""),           # git branch --list OK
            ShellError(bad_result),                 # git checkout -b fails
        ]
        with pytest.raises(ShellError):
            prepare_branch("night-shift/42-fix-bug")

    @patch("nightshift.safety.run")
    def test_checks_exact_branch_name(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            make_shell_result(stdout=""),
            make_shell_result(stdout=""),
        ]
        prepare_branch("night-shift/42-fix-bug")
        list_call = mock_run.call_args_list[0]
        cmd = list_call[0][0]
        assert "night-shift/42-fix-bug" in cmd


# ---------------------------------------------------------------------------
# T-12 — _parse_diff_stat: unit tests
# ---------------------------------------------------------------------------


class TestParseDiffStat:
    def test_full_stat_line(self) -> None:
        output = " 3 files changed, 42 insertions(+), 7 deletions(-)\n"
        stats = _parse_diff_stat(output)
        assert stats.files_changed == 3
        assert stats.lines_added == 42
        assert stats.lines_removed == 7

    def test_single_file_no_deletions(self) -> None:
        output = " 1 file changed, 5 insertions(+)\n"
        stats = _parse_diff_stat(output)
        assert stats.files_changed == 1
        assert stats.lines_added == 5
        assert stats.lines_removed == 0

    def test_single_file_no_insertions(self) -> None:
        output = " 1 file changed, 3 deletions(-)\n"
        stats = _parse_diff_stat(output)
        assert stats.files_changed == 1
        assert stats.lines_added == 0
        assert stats.lines_removed == 3

    def test_empty_output_returns_zeros(self) -> None:
        stats = _parse_diff_stat("")
        assert stats.files_changed == 0
        assert stats.lines_added == 0
        assert stats.lines_removed == 0

    def test_total_lines_property(self) -> None:
        stats = DiffStats(files_changed=1, lines_added=10, lines_removed=5)
        assert stats.total_lines == 15

    def test_multiline_output_uses_summary_line(self) -> None:
        output = (
            " src/foo.py | 10 ++++++++++-\n"
            " src/bar.py | 5  -----\n"
            " 2 files changed, 10 insertions(+), 5 deletions(-)\n"
        )
        stats = _parse_diff_stat(output)
        assert stats.files_changed == 2
        assert stats.lines_added == 10
        assert stats.lines_removed == 5


# ---------------------------------------------------------------------------
# T-12 — check_diff_limits: unit tests
# ---------------------------------------------------------------------------


class TestCheckDiffLimits:
    @patch("nightshift.safety.run")
    def test_within_limits_returns_stats(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(
            stdout=" 3 files changed, 10 insertions(+), 2 deletions(-)\n"
        )
        stats = check_diff_limits(max_files=20, max_lines=500)
        assert isinstance(stats, DiffStats)
        assert stats.files_changed == 3

    @patch("nightshift.safety.run")
    def test_raises_over_limit_error_when_files_exceeded(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(
            stdout=" 25 files changed, 10 insertions(+), 2 deletions(-)\n"
        )
        with pytest.raises(OverLimitError) as exc_info:
            check_diff_limits(max_files=20, max_lines=500)
        assert exc_info.value.stats.files_changed == 25

    @patch("nightshift.safety.run")
    def test_raises_over_limit_error_when_lines_exceeded(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(
            stdout=" 3 files changed, 400 insertions(+), 200 deletions(-)\n"
        )
        with pytest.raises(OverLimitError):
            check_diff_limits(max_files=20, max_lines=500)

    @patch("nightshift.safety.run")
    def test_error_message_mentions_counts(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(
            stdout=" 25 files changed, 10 insertions(+), 2 deletions(-)\n"
        )
        with pytest.raises(OverLimitError) as exc_info:
            check_diff_limits(max_files=20, max_lines=500)
        assert "25" in str(exc_info.value)

    @patch("nightshift.safety.run")
    def test_calls_git_diff_stat_head(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(stdout="")
        check_diff_limits(max_files=20, max_lines=500)
        cmd = mock_run.call_args[0][0]
        assert "git" in cmd
        assert "diff" in cmd
        assert "--stat" in cmd
        assert "HEAD" in cmd

    @patch("nightshift.safety.run")
    def test_no_changes_within_limits(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(stdout="")
        stats = check_diff_limits(max_files=1, max_lines=1)
        assert stats.files_changed == 0
        assert stats.total_lines == 0

    @patch("nightshift.safety.run")
    def test_exactly_at_limit_does_not_raise(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(
            stdout=" 20 files changed, 500 insertions(+), 0 deletions(-)\n"
        )
        stats = check_diff_limits(max_files=20, max_lines=500)
        assert stats.files_changed == 20

    @patch("nightshift.safety.run")
    def test_one_over_file_limit_raises(self, mock_run: MagicMock) -> None:
        mock_run.return_value = make_shell_result(
            stdout=" 21 files changed, 1 insertions(+), 0 deletions(-)\n"
        )
        with pytest.raises(OverLimitError):
            check_diff_limits(max_files=20, max_lines=500)


# ---------------------------------------------------------------------------
# T-12 — Property-based tests for check_diff_limits / DiffStats
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    files=st.integers(min_value=0, max_value=100),
    added=st.integers(min_value=0, max_value=10000),
    removed=st.integers(min_value=0, max_value=10000),
    max_files=st.integers(min_value=1, max_value=200),
    max_lines=st.integers(min_value=1, max_value=20000),
)
def test_no_over_limit_error_when_within_limits(
    files: int,
    added: int,
    removed: int,
    max_files: int,
    max_lines: int,
) -> None:
    """check_diff_limits never raises when both counts are within limits."""
    assume(files <= max_files)
    assume(added + removed <= max_lines)

    # Build a fake diff --stat output.
    # When files==0 there are no changes, so added/removed must also be 0
    # (git would not show insertions/deletions with no files changed).
    if files == 0:
        stat_output = ""
        added = 0
        removed = 0
    else:
        stat_output = (
            f" {files} files changed, {added} insertions(+), {removed} deletions(-)\n"
        )

    with patch("nightshift.safety.run") as mock_run:
        mock_run.return_value = make_shell_result(stdout=stat_output)
        stats = check_diff_limits(max_files=max_files, max_lines=max_lines)

    assert stats.files_changed == files
    assert stats.lines_added == added
    assert stats.lines_removed == removed


@settings(max_examples=100, deadline=None)
@given(
    files=st.integers(min_value=0, max_value=10000),
    added=st.integers(min_value=0, max_value=10000),
    removed=st.integers(min_value=0, max_value=10000),
)
def test_over_limit_error_when_exceeded(
    files: int,
    added: int,
    removed: int,
) -> None:
    """check_diff_limits always raises when at least one count exceeds its limit."""
    max_files = max(0, files - 1)
    max_lines = max(0, added + removed - 1)

    # When files==0 the stat output is "" which parses as (0, 0, 0); if
    # added+removed > 0 the limits wouldn't be exceeded in the parsed stats,
    # so filter those cases out.
    if files == 0:
        assume(False)

    assume(files > max_files or (added + removed) > max_lines)

    stat_output = (
        f" {files} files changed, {added} insertions(+), {removed} deletions(-)\n"
    )

    with patch("nightshift.safety.run") as mock_run:
        mock_run.return_value = make_shell_result(stdout=stat_output)
        with pytest.raises(OverLimitError):
            check_diff_limits(max_files=max_files, max_lines=max_lines)
