"""Tests for nightshift.shell."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from nightshift.shell import ShellError, ShellResult, run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A cross-platform echo command we can rely on without a real shell
_TRUE_CMD = [sys.executable, "-c", "import sys; sys.exit(0)"]
_FALSE_CMD = [sys.executable, "-c", "import sys; sys.exit(1)"]
_ECHO_CMD = [sys.executable, "-c", "print('hello night shift')"]
_STDERR_CMD = [
    sys.executable,
    "-c",
    "import sys; sys.stderr.write('err output\\n')",
]
_TIMEOUT_CMD = [sys.executable, "-c", "import time; time.sleep(10)"]
_CWD_CMD = [sys.executable, "-c", "import os, pathlib; print(pathlib.Path.cwd())"]
_STDIN_CMD = [sys.executable, "-c", "import sys; print(sys.stdin.read().strip())"]


# ---------------------------------------------------------------------------
# ShellResult
# ---------------------------------------------------------------------------


class TestShellResult:
    def test_output_combines_stdout_and_stderr(self) -> None:
        result = ShellResult(
            cmd=["fake"],
            returncode=0,
            stdout="out\n",
            stderr="err\n",
        )
        assert "out" in result.output
        assert "err" in result.output

    def test_output_empty_when_both_empty(self) -> None:
        result = ShellResult(cmd=["fake"], returncode=0, stdout="", stderr="")
        assert result.output == ""

    def test_output_stdout_only(self) -> None:
        result = ShellResult(cmd=["fake"], returncode=0, stdout="hello", stderr="")
        assert result.output == "hello"

    def test_output_stderr_only(self) -> None:
        result = ShellResult(cmd=["fake"], returncode=0, stdout="", stderr="world")
        assert result.output == "world"


# ---------------------------------------------------------------------------
# ShellError
# ---------------------------------------------------------------------------


class TestShellError:
    def test_message_contains_returncode(self) -> None:
        result = ShellResult(cmd=["bad", "cmd"], returncode=42, stdout="", stderr="boom")
        err = ShellError(result)
        assert "42" in str(err)

    def test_message_contains_command(self) -> None:
        result = ShellResult(cmd=["bad", "cmd"], returncode=1, stdout="", stderr="")
        err = ShellError(result)
        assert "bad cmd" in str(err)

    def test_result_attribute(self) -> None:
        result = ShellResult(cmd=["x"], returncode=2, stdout="o", stderr="e")
        err = ShellError(result)
        assert err.result is result


# ---------------------------------------------------------------------------
# run() — success cases
# ---------------------------------------------------------------------------


class TestRunSuccess:
    def test_returns_shell_result(self) -> None:
        result = run(_TRUE_CMD)
        assert isinstance(result, ShellResult)

    def test_returncode_zero(self) -> None:
        result = run(_TRUE_CMD)
        assert result.returncode == 0

    def test_captures_stdout(self) -> None:
        result = run(_ECHO_CMD)
        assert "hello night shift" in result.stdout

    def test_captures_stderr(self) -> None:
        result = run(_STDERR_CMD)
        assert "err output" in result.stderr

    def test_cmd_stored_on_result(self) -> None:
        result = run(_ECHO_CMD)
        assert result.cmd == _ECHO_CMD

    def test_cwd_passed_to_subprocess(self, tmp_path: Path) -> None:
        result = run(_CWD_CMD, cwd=tmp_path)
        # Path comparison is case-insensitive on Windows
        assert Path(result.stdout.strip()).resolve() == tmp_path.resolve()

    def test_stdin_passed(self) -> None:
        result = run(_STDIN_CMD, input="ghost")
        assert "ghost" in result.stdout

    def test_check_false_no_raise_on_nonzero(self) -> None:
        result = run(_FALSE_CMD, check=False)
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# run() — failure cases
# ---------------------------------------------------------------------------


class TestRunFailure:
    def test_raises_shell_error_on_nonzero(self) -> None:
        with pytest.raises(ShellError) as exc_info:
            run(_FALSE_CMD)
        assert exc_info.value.result.returncode != 0

    def test_shell_error_has_result(self) -> None:
        with pytest.raises(ShellError) as exc_info:
            run(_FALSE_CMD)
        assert isinstance(exc_info.value.result, ShellResult)

    def test_raises_timeout_expired(self) -> None:
        with pytest.raises(subprocess.TimeoutExpired):
            run(_TIMEOUT_CMD, timeout=1)

    def test_accepts_only_list_commands(self) -> None:
        """run() raises TypeError immediately when cmd is not a list.

        Passing a plain string is a programmer error.  The check is enforced
        before any subprocess is spawned so the behaviour is identical on all
        platforms (no Windows-vs-POSIX ambiguity).
        """
        with pytest.raises(TypeError):
            run("echo hello")  # type: ignore[arg-type]
