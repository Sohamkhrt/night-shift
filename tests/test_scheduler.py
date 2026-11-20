"""test_scheduler.py — tests for scheduler.py (T-24, T-25, T-26, T-27).

Coverage
--------
T-24 — CronScheduler:
    install  — adds a crontab line with the nightshift marker.
    install  — replaces an existing nightshift crontab line (idempotent).
    install  — preserves unrelated crontab lines.
    uninstall — removes the nightshift crontab line.
    uninstall — is idempotent when no line is present.
    uninstall — preserves unrelated crontab lines.
    status   — reports the installed entry.
    status   — reports "not scheduled" when absent.

T-24 — CronScheduler subprocess error handling:
    install  — propagates CalledProcessError from crontab -
    empty crontab (exit code 1) treated as empty list.

T-25 — TaskSchedulerScheduler:
    install  — calls schtasks /Create with correct /TN, /TR, /ST.
    install  — parses HH:MM from cron_expr correctly.
    uninstall — calls schtasks /Delete /F /TN NightShift.
    uninstall — tolerates non-zero exit from schtasks /Delete (task absent).
    status   — returns task details when schtasks /Query succeeds.
    status   — returns "not scheduled" when schtasks /Query fails.
    _build_task_command — includes uv run --directory and --config.

T-24/T-25 — Protocol conformance:
    CronScheduler satisfies the Scheduler protocol.
    TaskSchedulerScheduler satisfies the Scheduler protocol.
    KiroCrewScheduler satisfies the Scheduler protocol.

T-25 — _parse_cron_time:
    valid five-field expression returns (minute, hour).
    valid two-field expression returns (minute, hour).
    invalid (too few fields) raises ValueError.

T-26 — KiroCrewScheduler:
    install raises NotImplementedError.
    uninstall raises NotImplementedError.
    status raises NotImplementedError.
    error messages mention Kiro Crew docs URL.

T-27 — get_scheduler():
    returns CronScheduler on non-Windows platform.
    returns TaskSchedulerScheduler on Windows platform.

T-27 — CLI: nightshift schedule install:
    exits 0 on success and prints confirmation.
    passes cron_expr built from --time to scheduler.install.
    exits 1 on bad --time format.
    exits 1 when scheduler.install raises.
    --time 01:00 produces cron_expr "0 1 * * *".
    --time 30:00 (invalid hour) exits 1.

T-27 — CLI: nightshift schedule remove:
    exits 0 on success and prints confirmation.
    exits 1 when scheduler.uninstall raises.

T-27 — CLI: nightshift schedule status:
    exits 0 and prints scheduler.status() output.
    exits 1 when scheduler.status raises.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from typer.testing import CliRunner

from nightshift.cli import app
from nightshift.scheduler import (
    _CRON_MARKER,
    _TASK_NAME,
    _parse_cron_time,
    CronScheduler,
    KiroCrewScheduler,
    Scheduler,
    TaskSchedulerScheduler,
    _read_crontab,
    _write_crontab,
    get_scheduler,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

cli_runner = CliRunner()


def _proc(stdout: str = "", returncode: int = 0) -> CompletedProcess:
    """Return a fake CompletedProcess with the given stdout and return code."""
    return CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _make_subprocess_run(responses: list[CompletedProcess]) -> MagicMock:
    """Return a mock subprocess.run that yields responses in order."""
    mock = MagicMock(side_effect=responses)
    return mock


# ---------------------------------------------------------------------------
# T-24 — _read_crontab / _write_crontab helpers
# ---------------------------------------------------------------------------


class TestReadCrontab:
    def test_returns_empty_list_on_nonzero_exit(self) -> None:
        fake_run = _make_subprocess_run([_proc(returncode=1, stdout="")])
        result = _read_crontab(fake_run)
        assert result == []

    def test_returns_lines_on_success(self) -> None:
        fake_run = _make_subprocess_run([_proc(stdout="0 2 * * * backup\n# comment\n")])
        result = _read_crontab(fake_run)
        assert result == ["0 2 * * * backup", "# comment"]

    def test_calls_crontab_minus_l(self) -> None:
        fake_run = _make_subprocess_run([_proc()])
        _read_crontab(fake_run)
        fake_run.assert_called_once()
        cmd = fake_run.call_args[0][0]
        assert cmd == ["crontab", "-l"]

    def test_empty_stdout_returns_empty_list(self) -> None:
        fake_run = _make_subprocess_run([_proc(stdout="")])
        result = _read_crontab(fake_run)
        assert result == []


class TestWriteCrontab:
    def test_calls_crontab_minus(self) -> None:
        fake_run = _make_subprocess_run([_proc()])
        _write_crontab(["0 1 * * * nightshift run # nightshift"], fake_run)
        fake_run.assert_called_once()
        cmd = fake_run.call_args[0][0]
        assert cmd == ["crontab", "-"]

    def test_passes_lines_as_input(self) -> None:
        fake_run = _make_subprocess_run([_proc()])
        _write_crontab(["line1", "line2"], fake_run)
        kwargs = fake_run.call_args[1]
        assert "line1" in kwargs["input"]
        assert "line2" in kwargs["input"]

    def test_input_ends_with_newline(self) -> None:
        fake_run = _make_subprocess_run([_proc()])
        _write_crontab(["a", "b"], fake_run)
        kwargs = fake_run.call_args[1]
        assert kwargs["input"].endswith("\n")


# ---------------------------------------------------------------------------
# T-24 — CronScheduler
# ---------------------------------------------------------------------------


class TestCronSchedulerInstall:
    def _scheduler(self) -> CronScheduler:
        return CronScheduler()

    def test_adds_line_with_marker(self) -> None:
        # Empty crontab, then write call
        fake_run = _make_subprocess_run([_proc(stdout=""), _proc()])
        s = self._scheduler()
        s.install("nightshift run", "0 1 * * *", _subprocess_run=fake_run)
        write_input = fake_run.call_args_list[1][1]["input"]
        assert _CRON_MARKER in write_input
        assert "nightshift run" in write_input

    def test_cron_expr_included_in_line(self) -> None:
        fake_run = _make_subprocess_run([_proc(stdout=""), _proc()])
        s = self._scheduler()
        s.install("nightshift run", "30 2 * * *", _subprocess_run=fake_run)
        write_input = fake_run.call_args_list[1][1]["input"]
        assert "30 2 * * *" in write_input

    def test_replaces_existing_nightshift_line(self) -> None:
        existing = f"0 1 * * * nightshift run {_CRON_MARKER}\n"
        fake_run = _make_subprocess_run([_proc(stdout=existing), _proc()])
        s = self._scheduler()
        s.install("nightshift run", "0 2 * * *", _subprocess_run=fake_run)
        write_input = fake_run.call_args_list[1][1]["input"]
        # Old line removed, new line added
        assert "0 1 * * *" not in write_input
        assert "0 2 * * *" in write_input
        # Only one nightshift marker
        assert write_input.count(_CRON_MARKER) == 1

    def test_preserves_unrelated_lines(self) -> None:
        existing = f"0 3 * * * backup_job\n"
        fake_run = _make_subprocess_run([_proc(stdout=existing), _proc()])
        s = self._scheduler()
        s.install("nightshift run", "0 1 * * *", _subprocess_run=fake_run)
        write_input = fake_run.call_args_list[1][1]["input"]
        assert "backup_job" in write_input

    def test_calls_crontab_l_then_crontab_minus(self) -> None:
        fake_run = _make_subprocess_run([_proc(stdout=""), _proc()])
        s = self._scheduler()
        s.install("nightshift run", "0 1 * * *", _subprocess_run=fake_run)
        cmds = [c[0][0] for c in fake_run.call_args_list]
        assert cmds[0] == ["crontab", "-l"]
        assert cmds[1] == ["crontab", "-"]


class TestCronSchedulerUninstall:
    def _scheduler(self) -> CronScheduler:
        return CronScheduler()

    def test_removes_nightshift_line(self) -> None:
        existing = f"0 1 * * * nightshift run {_CRON_MARKER}\n"
        fake_run = _make_subprocess_run([_proc(stdout=existing), _proc()])
        s = self._scheduler()
        s.uninstall(_subprocess_run=fake_run)
        write_input = fake_run.call_args_list[1][1]["input"]
        assert _CRON_MARKER not in write_input

    def test_preserves_unrelated_lines_on_uninstall(self) -> None:
        existing = f"0 3 * * * backup {_CRON_MARKER}\n0 1 * * * other_job\n".replace(
            f" {_CRON_MARKER}", ""
        ) + f"0 3 * * * backup {_CRON_MARKER}\n"
        lines = f"0 1 * * * other_job\n0 3 * * * ns run {_CRON_MARKER}\n"
        fake_run = _make_subprocess_run([_proc(stdout=lines), _proc()])
        s = self._scheduler()
        s.uninstall(_subprocess_run=fake_run)
        write_input = fake_run.call_args_list[1][1]["input"]
        assert "other_job" in write_input
        assert _CRON_MARKER not in write_input

    def test_no_write_when_nothing_to_remove(self) -> None:
        """When no nightshift line exists, crontab - is NOT called."""
        fake_run = _make_subprocess_run([_proc(stdout="0 3 * * * backup\n")])
        s = self._scheduler()
        s.uninstall(_subprocess_run=fake_run)
        # Only one call (crontab -l), no second call (crontab -)
        assert fake_run.call_count == 1

    def test_idempotent_on_empty_crontab(self) -> None:
        fake_run = _make_subprocess_run([_proc(returncode=1, stdout="")])
        s = self._scheduler()
        # Should not raise, should not call write
        s.uninstall(_subprocess_run=fake_run)
        assert fake_run.call_count == 1


class TestCronSchedulerStatus:
    def _scheduler(self) -> CronScheduler:
        return CronScheduler()

    def test_reports_installed_entry(self) -> None:
        line = f"0 1 * * * nightshift run {_CRON_MARKER}"
        fake_run = _make_subprocess_run([_proc(stdout=line + "\n")])
        s = self._scheduler()
        result = s.status(_subprocess_run=fake_run)
        assert _CRON_MARKER in result or "cron entry" in result.lower()
        assert "0 1 * * *" in result

    def test_reports_not_scheduled_when_absent(self) -> None:
        fake_run = _make_subprocess_run([_proc(stdout="0 3 * * * backup\n")])
        s = self._scheduler()
        result = s.status(_subprocess_run=fake_run)
        assert "not scheduled" in result.lower()

    def test_reports_not_scheduled_on_empty_crontab(self) -> None:
        fake_run = _make_subprocess_run([_proc(returncode=1, stdout="")])
        s = self._scheduler()
        result = s.status(_subprocess_run=fake_run)
        assert "not scheduled" in result.lower()


# ---------------------------------------------------------------------------
# T-25 — TaskSchedulerScheduler
# ---------------------------------------------------------------------------


class TestTaskSchedulerSchedulerInstall:
    def _scheduler(self, install_dir: Path | None = None, config_path: Path | None = None) -> TaskSchedulerScheduler:
        d = install_dir or Path("/opt/night-shift")
        c = config_path or (d / "nightshift.toml")
        return TaskSchedulerScheduler(install_dir=d, config_path=c)

    def test_calls_schtasks_create(self) -> None:
        fake_run = _make_subprocess_run([_proc()])
        s = self._scheduler()
        s.install("nightshift run", "0 1 * * *", _subprocess_run=fake_run)
        cmd = fake_run.call_args[0][0]
        assert "schtasks" in cmd
        assert "/Create" in cmd

    def test_task_name_in_command(self) -> None:
        fake_run = _make_subprocess_run([_proc()])
        s = self._scheduler()
        s.install("nightshift run", "0 1 * * *", _subprocess_run=fake_run)
        cmd = fake_run.call_args[0][0]
        assert _TASK_NAME in cmd

    def test_start_time_01_00(self) -> None:
        fake_run = _make_subprocess_run([_proc()])
        s = self._scheduler()
        s.install("nightshift run", "0 1 * * *", _subprocess_run=fake_run)
        cmd = fake_run.call_args[0][0]
        st_index = cmd.index("/ST")
        assert cmd[st_index + 1] == "01:00"

    def test_start_time_30_14(self) -> None:
        fake_run = _make_subprocess_run([_proc()])
        s = self._scheduler()
        s.install("nightshift run", "30 14 * * *", _subprocess_run=fake_run)
        cmd = fake_run.call_args[0][0]
        st_index = cmd.index("/ST")
        assert cmd[st_index + 1] == "14:30"

    def test_force_flag_present(self) -> None:
        fake_run = _make_subprocess_run([_proc()])
        s = self._scheduler()
        s.install("nightshift run", "0 1 * * *", _subprocess_run=fake_run)
        cmd = fake_run.call_args[0][0]
        assert "/F" in cmd

    def test_task_run_contains_uv_run(self) -> None:
        fake_run = _make_subprocess_run([_proc()])
        s = self._scheduler(install_dir=Path("/my/repo"))
        s.install("nightshift run", "0 1 * * *", _subprocess_run=fake_run)
        cmd = fake_run.call_args[0][0]
        tr_index = cmd.index("/TR")
        task_run = cmd[tr_index + 1]
        assert "uv run" in task_run

    def test_task_run_contains_directory(self) -> None:
        fake_run = _make_subprocess_run([_proc()])
        install_dir = Path("/my/night-shift")
        s = self._scheduler(install_dir=install_dir)
        s.install("nightshift run", "0 1 * * *", _subprocess_run=fake_run)
        cmd = fake_run.call_args[0][0]
        tr_index = cmd.index("/TR")
        task_run = cmd[tr_index + 1]
        assert str(install_dir) in task_run

    def test_task_run_contains_config_path(self) -> None:
        fake_run = _make_subprocess_run([_proc()])
        install_dir = Path("/my/night-shift")
        config_path = install_dir / "nightshift.toml"
        s = self._scheduler(install_dir=install_dir, config_path=config_path)
        s.install("nightshift run", "0 1 * * *", _subprocess_run=fake_run)
        cmd = fake_run.call_args[0][0]
        tr_index = cmd.index("/TR")
        task_run = cmd[tr_index + 1]
        assert str(config_path) in task_run

    def test_calls_check_true(self) -> None:
        fake_run = _make_subprocess_run([_proc()])
        s = self._scheduler()
        s.install("nightshift run", "0 1 * * *", _subprocess_run=fake_run)
        kwargs = fake_run.call_args[1]
        assert kwargs.get("check") is True


class TestTaskSchedulerSchedulerUninstall:
    def _scheduler(self) -> TaskSchedulerScheduler:
        return TaskSchedulerScheduler(
            install_dir=Path("/opt/night-shift"),
            config_path=Path("/opt/night-shift/nightshift.toml"),
        )

    def test_calls_schtasks_delete(self) -> None:
        fake_run = _make_subprocess_run([_proc()])
        s = self._scheduler()
        s.uninstall(_subprocess_run=fake_run)
        cmd = fake_run.call_args[0][0]
        assert "schtasks" in cmd
        assert "/Delete" in cmd
        assert _TASK_NAME in cmd

    def test_force_flag_present(self) -> None:
        fake_run = _make_subprocess_run([_proc()])
        s = self._scheduler()
        s.uninstall(_subprocess_run=fake_run)
        cmd = fake_run.call_args[0][0]
        assert "/F" in cmd

    def test_does_not_raise_on_nonzero_exit(self) -> None:
        """schtasks /Delete returns non-zero when task does not exist; treat as no-op."""
        fake_run = _make_subprocess_run([_proc(returncode=1)])
        s = self._scheduler()
        # Should not raise
        s.uninstall(_subprocess_run=fake_run)

    def test_does_not_pass_check_true(self) -> None:
        """check= must NOT be True so a missing task does not raise."""
        fake_run = _make_subprocess_run([_proc()])
        s = self._scheduler()
        s.uninstall(_subprocess_run=fake_run)
        kwargs = fake_run.call_args[1]
        assert kwargs.get("check") is not True


class TestTaskSchedulerSchedulerStatus:
    def _scheduler(self) -> TaskSchedulerScheduler:
        return TaskSchedulerScheduler(
            install_dir=Path("/opt/night-shift"),
            config_path=Path("/opt/night-shift/nightshift.toml"),
        )

    def test_reports_task_details_on_success(self) -> None:
        output = "TaskName: NightShift\nStatus: Ready\nNext Run: 01:00"
        fake_run = _make_subprocess_run([_proc(stdout=output)])
        s = self._scheduler()
        result = s.status(_subprocess_run=fake_run)
        assert _TASK_NAME in result
        assert "Ready" in result

    def test_reports_not_scheduled_on_nonzero_exit(self) -> None:
        fake_run = _make_subprocess_run([_proc(returncode=1, stdout="")])
        s = self._scheduler()
        result = s.status(_subprocess_run=fake_run)
        assert "not scheduled" in result.lower()

    def test_calls_schtasks_query(self) -> None:
        fake_run = _make_subprocess_run([_proc(stdout="x")])
        s = self._scheduler()
        s.status(_subprocess_run=fake_run)
        cmd = fake_run.call_args[0][0]
        assert "schtasks" in cmd
        assert "/Query" in cmd
        assert _TASK_NAME in cmd


class TestBuildTaskCommand:
    def test_contains_uv_run_directory(self) -> None:
        install_dir = Path("/srv/night-shift")
        config_path = install_dir / "nightshift.toml"
        s = TaskSchedulerScheduler(install_dir=install_dir, config_path=config_path)
        cmd = s._build_task_command()
        assert "uv run" in cmd
        assert "--directory" in cmd
        assert str(install_dir) in cmd

    def test_contains_nightshift_run(self) -> None:
        s = TaskSchedulerScheduler(
            install_dir=Path("/srv/ns"),
            config_path=Path("/srv/ns/nightshift.toml"),
        )
        assert "nightshift run" in s._build_task_command()

    def test_contains_config_flag(self) -> None:
        install_dir = Path("/srv/ns")
        config_path = install_dir / "my-config.toml"
        s = TaskSchedulerScheduler(install_dir=install_dir, config_path=config_path)
        cmd = s._build_task_command()
        assert "--config" in cmd
        assert str(config_path) in cmd


# ---------------------------------------------------------------------------
# T-25 — _parse_cron_time
# ---------------------------------------------------------------------------


class TestParseCronTime:
    def test_five_field_expression(self) -> None:
        assert _parse_cron_time("0 1 * * *") == ("0", "1")

    def test_two_field_expression(self) -> None:
        assert _parse_cron_time("30 14") == ("30", "14")

    def test_nonzero_minute(self) -> None:
        assert _parse_cron_time("15 3 * * *") == ("15", "3")

    def test_raises_on_single_field(self) -> None:
        with pytest.raises(ValueError, match="Invalid cron"):
            _parse_cron_time("0")

    def test_raises_on_empty_string(self) -> None:
        with pytest.raises(ValueError, match="Invalid cron"):
            _parse_cron_time("")


# ---------------------------------------------------------------------------
# T-26 — KiroCrewScheduler
# ---------------------------------------------------------------------------


class TestKiroCrewScheduler:
    def test_install_raises_not_implemented(self) -> None:
        s = KiroCrewScheduler()
        with pytest.raises(NotImplementedError):
            s.install("nightshift run", "0 1 * * *")

    def test_uninstall_raises_not_implemented(self) -> None:
        s = KiroCrewScheduler()
        with pytest.raises(NotImplementedError):
            s.uninstall()

    def test_status_raises_not_implemented(self) -> None:
        s = KiroCrewScheduler()
        with pytest.raises(NotImplementedError):
            s.status()

    def test_install_error_message_mentions_docs(self) -> None:
        s = KiroCrewScheduler()
        with pytest.raises(NotImplementedError, match="kiro.dev"):
            s.install("nightshift run", "0 1 * * *")


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestSchedulerProtocol:
    def test_cron_scheduler_satisfies_protocol(self) -> None:
        assert isinstance(CronScheduler(), Scheduler)

    def test_task_scheduler_satisfies_protocol(self) -> None:
        s = TaskSchedulerScheduler(
            install_dir=Path("/opt"),
            config_path=Path("/opt/nightshift.toml"),
        )
        assert isinstance(s, Scheduler)

    def test_kiro_crew_scheduler_satisfies_protocol(self) -> None:
        assert isinstance(KiroCrewScheduler(), Scheduler)


# ---------------------------------------------------------------------------
# T-27 — get_scheduler()
# ---------------------------------------------------------------------------


class TestGetScheduler:
    def test_returns_cron_scheduler_on_linux(self) -> None:
        with patch("nightshift.scheduler.sys") as mock_sys:
            mock_sys.platform = "linux"
            s = get_scheduler()
        assert isinstance(s, CronScheduler)

    def test_returns_cron_scheduler_on_darwin(self) -> None:
        with patch("nightshift.scheduler.sys") as mock_sys:
            mock_sys.platform = "darwin"
            s = get_scheduler()
        assert isinstance(s, CronScheduler)

    def test_returns_task_scheduler_on_win32(self) -> None:
        with patch("nightshift.scheduler.sys") as mock_sys:
            mock_sys.platform = "win32"
            s = get_scheduler()
        assert isinstance(s, TaskSchedulerScheduler)

    def test_passes_config_path_to_task_scheduler(self) -> None:
        cfg = Path("/my/config.toml")
        with patch("nightshift.scheduler.sys") as mock_sys:
            mock_sys.platform = "win32"
            s = get_scheduler(config_path=cfg)
        assert isinstance(s, TaskSchedulerScheduler)
        assert s._config_path == cfg


# ---------------------------------------------------------------------------
# T-27 — CLI: nightshift schedule install
# ---------------------------------------------------------------------------


class TestScheduleInstallCli:
    """Tests for ``nightshift schedule install`` CLI subcommand."""

    _SCHEDULER_MODULE = "nightshift.scheduler"
    _GET_SCHEDULER = "nightshift.cli.get_scheduler"

    def _invoke(self, *args: str):
        return cli_runner.invoke(app, ["schedule", "install", *args])

    def test_exits_0_on_success(self) -> None:
        mock_scheduler = MagicMock()
        with patch(self._GET_SCHEDULER, return_value=mock_scheduler):
            result = self._invoke()
        assert result.exit_code == 0

    def test_prints_confirmation(self) -> None:
        mock_scheduler = MagicMock()
        with patch(self._GET_SCHEDULER, return_value=mock_scheduler):
            result = self._invoke("--time", "01:00")
        assert "01:00" in result.output or "scheduled" in result.output.lower()

    def test_install_called_with_cron_expr_01_00(self) -> None:
        mock_scheduler = MagicMock()
        with patch(self._GET_SCHEDULER, return_value=mock_scheduler):
            self._invoke("--time", "01:00")
        mock_scheduler.install.assert_called_once()
        _, cron_expr = mock_scheduler.install.call_args[0]
        assert cron_expr == "0 1 * * *"

    def test_install_called_with_cron_expr_30_02(self) -> None:
        mock_scheduler = MagicMock()
        with patch(self._GET_SCHEDULER, return_value=mock_scheduler):
            self._invoke("--time", "02:30")
        _, cron_expr = mock_scheduler.install.call_args[0]
        assert cron_expr == "30 2 * * *"

    def test_bad_time_format_exits_1(self) -> None:
        result = self._invoke("--time", "noon")
        assert result.exit_code == 1

    def test_bad_time_no_colon_exits_1(self) -> None:
        result = self._invoke("--time", "0100")
        assert result.exit_code == 1

    def test_invalid_hour_exits_1(self) -> None:
        result = self._invoke("--time", "30:00")
        assert result.exit_code == 1

    def test_invalid_minute_exits_1(self) -> None:
        result = self._invoke("--time", "00:60")
        assert result.exit_code == 1

    def test_scheduler_exception_exits_1(self) -> None:
        mock_scheduler = MagicMock()
        mock_scheduler.install.side_effect = RuntimeError("crontab failed")
        with patch(self._GET_SCHEDULER, return_value=mock_scheduler):
            result = self._invoke()
        assert result.exit_code == 1

    def test_scheduler_exception_prints_error(self) -> None:
        mock_scheduler = MagicMock()
        mock_scheduler.install.side_effect = RuntimeError("crontab failed")
        with patch(self._GET_SCHEDULER, return_value=mock_scheduler):
            result = self._invoke()
        combined = result.output + (result.stderr or "")
        assert "crontab failed" in combined

    def test_get_scheduler_called(self) -> None:
        """get_scheduler() is called once per invocation."""
        mock_scheduler = MagicMock()
        with patch(self._GET_SCHEDULER, return_value=mock_scheduler) as mock_get:
            self._invoke()
        mock_get.assert_called_once()


# ---------------------------------------------------------------------------
# T-27 — CLI: nightshift schedule remove
# ---------------------------------------------------------------------------


class TestScheduleRemoveCli:
    """Tests for ``nightshift schedule remove`` CLI subcommand."""

    _GET_SCHEDULER = "nightshift.cli.get_scheduler"

    def _invoke(self) -> Any:
        return cli_runner.invoke(app, ["schedule", "remove"])

    def test_exits_0_on_success(self) -> None:
        mock_scheduler = MagicMock()
        with patch(self._GET_SCHEDULER, return_value=mock_scheduler):
            result = self._invoke()
        assert result.exit_code == 0

    def test_prints_confirmation(self) -> None:
        mock_scheduler = MagicMock()
        with patch(self._GET_SCHEDULER, return_value=mock_scheduler):
            result = self._invoke()
        assert "removed" in result.output.lower() or "schedule" in result.output.lower()

    def test_uninstall_called(self) -> None:
        mock_scheduler = MagicMock()
        with patch(self._GET_SCHEDULER, return_value=mock_scheduler):
            self._invoke()
        mock_scheduler.uninstall.assert_called_once()

    def test_exception_exits_1(self) -> None:
        mock_scheduler = MagicMock()
        mock_scheduler.uninstall.side_effect = RuntimeError("schtasks failed")
        with patch(self._GET_SCHEDULER, return_value=mock_scheduler):
            result = self._invoke()
        assert result.exit_code == 1

    def test_exception_prints_error(self) -> None:
        mock_scheduler = MagicMock()
        mock_scheduler.uninstall.side_effect = RuntimeError("schtasks failed")
        with patch(self._GET_SCHEDULER, return_value=mock_scheduler):
            result = self._invoke()
        combined = result.output + (result.stderr or "")
        assert "schtasks failed" in combined


# ---------------------------------------------------------------------------
# T-27 — CLI: nightshift schedule status
# ---------------------------------------------------------------------------


class TestScheduleStatusCli:
    """Tests for ``nightshift schedule status`` CLI subcommand."""

    _GET_SCHEDULER = "nightshift.cli.get_scheduler"

    def _invoke(self) -> Any:
        return cli_runner.invoke(app, ["schedule", "status"])

    def test_exits_0_on_success(self) -> None:
        mock_scheduler = MagicMock()
        mock_scheduler.status.return_value = "Night Shift cron entry: 0 1 * * * nightshift run # nightshift"
        with patch(self._GET_SCHEDULER, return_value=mock_scheduler):
            result = self._invoke()
        assert result.exit_code == 0

    def test_prints_scheduler_status_output(self) -> None:
        status_text = "Night Shift is not scheduled (no crontab entry found)."
        mock_scheduler = MagicMock()
        mock_scheduler.status.return_value = status_text
        with patch(self._GET_SCHEDULER, return_value=mock_scheduler):
            result = self._invoke()
        assert status_text in result.output

    def test_status_called(self) -> None:
        mock_scheduler = MagicMock()
        mock_scheduler.status.return_value = "ok"
        with patch(self._GET_SCHEDULER, return_value=mock_scheduler):
            self._invoke()
        mock_scheduler.status.assert_called_once()

    def test_exception_exits_1(self) -> None:
        mock_scheduler = MagicMock()
        mock_scheduler.status.side_effect = RuntimeError("unexpected error")
        with patch(self._GET_SCHEDULER, return_value=mock_scheduler):
            result = self._invoke()
        assert result.exit_code == 1

    def test_exception_prints_error(self) -> None:
        mock_scheduler = MagicMock()
        mock_scheduler.status.side_effect = RuntimeError("unexpected error")
        with patch(self._GET_SCHEDULER, return_value=mock_scheduler):
            result = self._invoke()
        combined = result.output + (result.stderr or "")
        assert "unexpected error" in combined
