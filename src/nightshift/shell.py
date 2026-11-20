"""shell.py — single subprocess execution point for Night Shift.

All external commands (git, gh, kiro-cli, pytest …) must go through
``shell.run()``.  This keeps logging, error handling, and security policy
in one place.

Never pass ``shell=True`` to subprocess — commands must be lists so that
untrusted values cannot inject extra arguments.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ShellResult:
    """Captured output from a completed subprocess."""

    cmd: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        """Combined stdout and stderr, useful for display."""
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(self.stderr)
        return "\n".join(parts)


class ShellError(RuntimeError):
    """Raised when a subprocess exits with a non-zero return code."""

    def __init__(self, result: ShellResult) -> None:
        self.result = result
        cmd_str = " ".join(result.cmd)
        super().__init__(
            f"Command failed (exit {result.returncode}): {cmd_str}\n"
            f"{result.output}"
        )


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
    check: bool = True,
    input: str | None = None,
) -> ShellResult:
    """Run *cmd* as a subprocess and return a :class:`ShellResult`.

    Parameters
    ----------
    cmd:
        Command as a list of strings.  Never pass a plain string — use
        ``shlex.split`` if you must parse a user-supplied string first.
    cwd:
        Working directory for the subprocess.  ``None`` inherits the
        current process's directory.
    timeout:
        Seconds before the process is killed with ``subprocess.TimeoutExpired``.
        ``None`` means no limit.
    check:
        If ``True`` (the default) and the process exits non-zero,
        :class:`ShellError` is raised.
    input:
        Optional text to write to the process's stdin.

    Returns
    -------
    ShellResult
        The captured output.  ``returncode`` is 0 on success.

    Raises
    ------
    ShellError
        When *check* is ``True`` and the exit code is non-zero.
    subprocess.TimeoutExpired
        When *timeout* is set and the process exceeds it.
    """
    logger.debug("$ %s  (cwd=%s, timeout=%s)", " ".join(cmd), cwd, timeout)

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            timeout=timeout,
            capture_output=True,
            text=True,
            input=input,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Command timed out after %ss: %s", timeout, " ".join(cmd))
        raise

    result = ShellResult(
        cmd=cmd,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )

    if proc.returncode != 0:
        logger.debug(
            "Command exited %d: %s\nstdout: %s\nstderr: %s",
            proc.returncode,
            " ".join(cmd),
            proc.stdout[:500],
            proc.stderr[:500],
        )
        if check:
            raise ShellError(result)

    return result
