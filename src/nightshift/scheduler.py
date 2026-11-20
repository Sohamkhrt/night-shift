"""scheduler.py — OS-level schedule management for Night Shift.

Exposes a ``Scheduler`` protocol with two concrete implementations:

* ``CronScheduler``          — Linux / macOS via ``crontab -l`` / ``crontab -``
* ``TaskSchedulerScheduler`` — Windows via ``schtasks.exe``

A ``KiroCrewScheduler`` stub is included but not wired; see the class
docstring for the integration hook.

Usage
-----
Use ``get_scheduler()`` to obtain the right implementation for the current
platform, then call ``install()``, ``uninstall()``, or ``status()``.

Windows scheduled task command
-------------------------------
On Windows the task runs::

    uv run --directory <install_dir> nightshift run --config <config_path>

``<install_dir>`` defaults to the directory containing this file's package
(``Path(__file__).parent.parent.parent`` relative to ``src/nightshift/``,
i.e. the repo root) and can be overridden with the *install_dir* parameter.
``<config_path>`` is the absolute path to ``nightshift.toml`` and defaults to
``<install_dir>/nightshift.toml``.

This ensures the task always runs with the correct ``uv`` environment
regardless of which directory the Task Scheduler invokes it from.  See
design.md Decisions for the full rationale.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Marker comment written into the crontab entry so Night Shift can find it.
_CRON_MARKER = "# nightshift"

#: Task name used by schtasks on Windows.
_TASK_NAME = "NightShift"

# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Scheduler(Protocol):
    """Minimal interface for OS-level schedule management."""

    def install(self, command: str, cron_expr: str) -> None:
        """Install the schedule entry.

        Parameters
        ----------
        command:
            The shell command to run (e.g. ``"nightshift run"``).
        cron_expr:
            A five-field cron expression (e.g. ``"0 1 * * *"``).
            Ignored on Windows (the time is parsed from *cron_expr* instead).
        """
        ...

    def uninstall(self) -> None:
        """Remove the schedule entry installed by :meth:`install`."""
        ...

    def status(self) -> str:
        """Return a human-readable string describing the current schedule."""
        ...


# ---------------------------------------------------------------------------
# CronScheduler (Linux / macOS)
# ---------------------------------------------------------------------------


class CronScheduler:
    """Manage a crontab entry on Linux / macOS.

    The entry is identified by the ``# nightshift`` trailing marker so it can
    be located and removed without touching other crontab entries.

    Implementation notes
    --------------------
    * Reads the current crontab with ``crontab -l`` (exit 0 or 1; exit 1 is
      treated as an empty crontab on systems that report "no crontab for
      user").
    * Writes the modified crontab back with ``crontab -``.
    * All subprocess calls go through :func:`_cron_run` which accepts an
      optional *_subprocess_run* override for unit testing.
    """

    def install(
        self,
        command: str,
        cron_expr: str,
        *,
        _subprocess_run: _SubprocessRunType | None = None,
    ) -> None:
        """Add (or replace) a Night Shift crontab entry.

        Parameters
        ----------
        command:
            The command to schedule (e.g. ``"nightshift run"``).
        cron_expr:
            Five-field cron expression (e.g. ``"0 1 * * *"``).
        _subprocess_run:
            Inject a fake ``subprocess.run`` for testing.
        """
        _run = _subprocess_run or subprocess.run

        existing = _read_crontab(_run)
        # Remove any existing nightshift line first (idempotent install)
        filtered = [line for line in existing if _CRON_MARKER not in line]
        new_line = f"{cron_expr} {command} {_CRON_MARKER}"
        filtered.append(new_line)
        _write_crontab(filtered, _run)

    def uninstall(
        self,
        *,
        _subprocess_run: _SubprocessRunType | None = None,
    ) -> None:
        """Remove the Night Shift crontab entry.

        Does nothing if no entry is found (idempotent).
        """
        _run = _subprocess_run or subprocess.run

        existing = _read_crontab(_run)
        filtered = [line for line in existing if _CRON_MARKER not in line]
        if len(filtered) == len(existing):
            # Nothing to remove
            return
        _write_crontab(filtered, _run)

    def status(
        self,
        *,
        _subprocess_run: _SubprocessRunType | None = None,
    ) -> str:
        """Return a string describing the current cron schedule.

        Returns one of:
        * ``"Night Shift cron entry: <full crontab line>"`` — when installed.
        * ``"Night Shift is not scheduled (no crontab entry found)."`` — when
          not installed.
        """
        _run = _subprocess_run or subprocess.run

        existing = _read_crontab(_run)
        for line in existing:
            if _CRON_MARKER in line:
                return f"Night Shift cron entry: {line.strip()}"
        return "Night Shift is not scheduled (no crontab entry found)."


# ---------------------------------------------------------------------------
# TaskSchedulerScheduler (Windows)
# ---------------------------------------------------------------------------


class TaskSchedulerScheduler:
    """Manage a Windows Task Scheduler entry via ``schtasks.exe``.

    The task runs::

        uv run --directory <install_dir> nightshift run --config <config_path>

    so the correct ``uv`` virtual environment is activated regardless of the
    working directory the scheduler invokes the process from.

    Parameters
    ----------
    install_dir:
        Absolute path to the Night Shift repo root.  Defaults to the
        three-level parent of this module (``src/nightshift/`` →
        ``src/`` → repo root).
    config_path:
        Absolute path to ``nightshift.toml``.  Defaults to
        ``<install_dir>/nightshift.toml``.
    """

    def __init__(
        self,
        install_dir: Path | None = None,
        config_path: Path | None = None,
    ) -> None:
        # Default: go three levels up from this file (src/nightshift/scheduler.py)
        self._install_dir: Path = install_dir or Path(__file__).parent.parent.parent.resolve()
        self._config_path: Path = config_path or (self._install_dir / "nightshift.toml")

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def install(
        self,
        command: str,
        cron_expr: str,
        *,
        _subprocess_run: _SubprocessRunType | None = None,
    ) -> None:
        """Create (or replace) the Night Shift scheduled task.

        The ``command`` and ``cron_expr`` parameters are accepted for protocol
        compatibility but ignored; the actual command is always::

            uv run --directory <install_dir> nightshift run --config <config_path>

        and the time is parsed from *cron_expr* (fields ``minute hour``).

        Parameters
        ----------
        command:
            Ignored — the full ``uv run`` command is used instead.
        cron_expr:
            Five-field cron expression; only the first two fields
            (minute, hour) are used to set the task start time.
        _subprocess_run:
            Inject a fake ``subprocess.run`` for testing.
        """
        _run = _subprocess_run or subprocess.run

        minute, hour = _parse_cron_time(cron_expr)
        start_time = f"{int(hour):02d}:{int(minute):02d}"
        task_command = self._build_task_command()

        # /F = force (overwrite if exists)
        _run(
            [
                "schtasks",
                "/Create",
                "/F",
                "/TN",
                _TASK_NAME,
                "/TR",
                task_command,
                "/SC",
                "DAILY",
                "/ST",
                start_time,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def uninstall(
        self,
        *,
        _subprocess_run: _SubprocessRunType | None = None,
    ) -> None:
        """Delete the Night Shift scheduled task.

        Does nothing if the task does not exist (idempotent: tolerates the
        non-zero exit code that ``schtasks /Delete`` returns when the task is
        absent).
        """
        _run = _subprocess_run or subprocess.run

        _run(
            ["schtasks", "/Delete", "/F", "/TN", _TASK_NAME],
            capture_output=True,
            text=True,
            # Do not check return code — schtasks exits non-zero if the task
            # does not exist, which we treat as a no-op.
        )

    def status(
        self,
        *,
        _subprocess_run: _SubprocessRunType | None = None,
    ) -> str:
        """Return a string describing the current Windows scheduled task.

        Returns one of:
        * ``"Night Shift scheduled task '<name>': <schtasks /Query output>"``
          — when installed.
        * ``"Night Shift is not scheduled (task '<name>' not found)."`` —
          when not installed.
        """
        _run = _subprocess_run or subprocess.run

        result = _run(
            ["schtasks", "/Query", "/TN", _TASK_NAME, "/FO", "LIST"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return f"Night Shift scheduled task '{_TASK_NAME}':\n{result.stdout.strip()}"
        return f"Night Shift is not scheduled (task '{_TASK_NAME}' not found)."

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_task_command(self) -> str:
        """Return the full command string for the schtasks /TR argument."""
        return (
            f"uv run --directory {self._install_dir} "
            f"nightshift run --config {self._config_path}"
        )


# ---------------------------------------------------------------------------
# KiroCrewScheduler — stub for the Kiro Crew bonus category
# ---------------------------------------------------------------------------


class KiroCrewScheduler:
    """Stub scheduler that delegates to the Kiro Crew orchestration layer.

    This class is intentionally not wired into the CLI.  It documents the
    integration hook for the Kiro Crew bonus category: a future implementation
    would register Night Shift as a recurring Kiro Crew task instead of using
    the OS scheduler.

    See https://docs.kiro.dev/crew for Kiro Crew documentation.
    """

    def install(self, command: str, cron_expr: str) -> None:  # noqa: ARG002
        raise NotImplementedError(
            "KiroCrewScheduler is not yet implemented.  "
            "See https://docs.kiro.dev/crew for Kiro Crew documentation."
        )

    def uninstall(self) -> None:
        raise NotImplementedError(
            "KiroCrewScheduler is not yet implemented.  "
            "See https://docs.kiro.dev/crew for Kiro Crew documentation."
        )

    def status(self) -> str:
        raise NotImplementedError(
            "KiroCrewScheduler is not yet implemented.  "
            "See https://docs.kiro.dev/crew for Kiro Crew documentation."
        )


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


def get_scheduler(
    install_dir: Path | None = None,
    config_path: Path | None = None,
) -> Scheduler:
    """Return the right :class:`Scheduler` implementation for this platform.

    Parameters
    ----------
    install_dir:
        Passed to :class:`TaskSchedulerScheduler` on Windows.
    config_path:
        Passed to :class:`TaskSchedulerScheduler` on Windows.

    Returns
    -------
    Scheduler
        :class:`CronScheduler` on Linux / macOS,
        :class:`TaskSchedulerScheduler` on Windows.
    """
    if sys.platform == "win32":
        return TaskSchedulerScheduler(install_dir=install_dir, config_path=config_path)
    return CronScheduler()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Type alias for the injectable subprocess.run parameter used in tests.
_SubprocessRunType = Any  # callable matching subprocess.run's signature


def _read_crontab(
    _run: _SubprocessRunType = subprocess.run,
) -> list[str]:
    """Read the current user's crontab, returning lines (without trailing
    newlines).  An empty list is returned when no crontab exists yet.
    """
    result = _run(
        ["crontab", "-l"],
        capture_output=True,
        text=True,
    )
    # Exit code 1 on many systems means "no crontab for user" — treat as empty.
    if result.returncode != 0:
        return []
    return result.stdout.splitlines()


def _write_crontab(
    lines: list[str],
    _run: _SubprocessRunType = subprocess.run,
) -> None:
    """Write *lines* back as the user's crontab via ``crontab -``."""
    content = "\n".join(lines) + "\n"
    _run(
        ["crontab", "-"],
        input=content,
        capture_output=True,
        text=True,
        check=True,
    )


def _parse_cron_time(cron_expr: str) -> tuple[str, str]:
    """Extract (minute, hour) from a five-field cron expression.

    Parameters
    ----------
    cron_expr:
        A string like ``"0 1 * * *"``.

    Returns
    -------
    tuple[str, str]
        ``(minute, hour)`` as strings, e.g. ``("0", "1")``.

    Raises
    ------
    ValueError
        If *cron_expr* does not have at least two fields.
    """
    parts = cron_expr.split()
    if len(parts) < 2:
        raise ValueError(
            f"Invalid cron expression (need at least minute and hour): {cron_expr!r}"
        )
    return parts[0], parts[1]
