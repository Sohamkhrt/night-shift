"""cli.py — Typer application and command definitions for Night Shift.

Entry point: ``nightshift = "nightshift.cli:app"`` in pyproject.toml.

Commands:
  nightshift run       -- kick off (or simulate) a nightly run  (T-21)
  nightshift diary     -- (re-)render the Ghost Diary HTML       (T-20)
  nightshift schedule  -- install/remove/status OS-level schedule
  nightshift status    -- show labeled issues and last run summary (T-22)
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Optional

import typer

from nightshift.github import GitHubAuthError, validate_auth

app = typer.Typer(
    name="nightshift",
    help=(
        "Night Shift -- autonomous overnight GitHub issue agent.\n\n"
        "Label issues with 'night-shift', go to sleep, wake up to pull requests."
    ),
    no_args_is_help=True,
)

# Sub-app for the `schedule` command group
schedule_app = typer.Typer(help="Install or manage the OS-level schedule.")
app.add_typer(schedule_app, name="schedule")


# ---------------------------------------------------------------------------
# nightshift run  (T-21)
# ---------------------------------------------------------------------------


@app.command()
def run(
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Simulate a run without pushing branches, opening PRs, or posting comments.",
        ),
    ] = False,
    config_path: Annotated[
        Optional[str],
        typer.Option("--config", help="Path to nightshift.toml (default: auto-discover)."),
    ] = None,
) -> None:
    """Run Night Shift right now (or simulate with --dry-run).

    Fetches labeled issues, processes each one with a Kiro ghost agent,
    runs tests, and opens PRs on success.
    """
    from pathlib import Path

    from nightshift import config as config_module
    from nightshift import runner as runner_module

    # Step 1: validate GitHub auth before doing any work (AC-01.4)
    try:
        validate_auth()
    except GitHubAuthError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    # Step 2: load config
    cfg_path = Path(config_path) if config_path else None
    try:
        cfg = config_module.load(cfg_path)
    except config_module.ConfigError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    # --dry-run flag overrides the config file value
    if dry_run:
        import dataclasses
        cfg = dataclasses.replace(cfg, dry_run=True)

    if cfg.dry_run:
        typer.echo("[dry-run] Simulating a Night Shift run. No PRs, pushes, or comments will be made.")

    # Step 3: run (lock file acquired inside run_all)
    try:
        run_log = runner_module.run_all(cfg)
    except runner_module.LockError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    # Step 4: print per-issue summary
    typer.echo("")
    typer.echo(f"Night Shift run complete — {run_log.date}")
    typer.echo(f"  Repo   : {run_log.repo}")
    typer.echo(f"  Issues : {run_log.total_issues}")
    typer.echo(f"  PRs    : {run_log.total_prs}")

    if run_log.events:
        typer.echo("")
        typer.echo("Per-issue results:")
        for event in run_log.events:
            pr_info = f"  -> {event.pr_url}" if event.pr_url else ""
            typer.echo(f"  #{event.issue_number:>4}  [{event.outcome:<12}]  {event.issue_title}{pr_info}")

    # Step 5: print diary path (if diary was rendered)
    diary_path = Path(".nightshift") / "diary" / f"{run_log.date.isoformat()}.html"
    if diary_path.exists():
        typer.echo("")
        typer.echo(f"Ghost Diary: {diary_path}")

    raise typer.Exit(code=0)


# ---------------------------------------------------------------------------
# nightshift diary  (T-20)
# ---------------------------------------------------------------------------


@app.command()
def diary(
    date: Annotated[
        Optional[str],
        typer.Option(
            "--date",
            help="Date in YYYY-MM-DD format (default: today).",
        ),
    ] = None,
) -> None:
    """(Re-)render the Ghost Diary HTML from the run log for a given date."""
    from nightshift import diary as diary_module

    if date is not None:
        try:
            target_date = dt.date.fromisoformat(date)
        except ValueError:
            typer.echo(f"Error: '{date}' is not a valid date (expected YYYY-MM-DD).", err=True)
            raise typer.Exit(code=1)
    else:
        target_date = dt.date.today()

    try:
        run_log = diary_module.load_log(target_date)
    except FileNotFoundError:
        typer.echo(
            f"No run log found for {target_date}. Generating a quiet-night diary.",
            err=True,
        )
        html_path = diary_module.quiet_night(target_date)
        typer.echo(f"Quiet night diary written to: {html_path}")
        return

    html_path = diary_module.render(run_log)
    typer.echo(f"Ghost Diary written to: {html_path}")


# ---------------------------------------------------------------------------
# nightshift status  (T-22)
# ---------------------------------------------------------------------------


@app.command()
def status(
    config_path: Annotated[
        Optional[str],
        typer.Option("--config", help="Path to nightshift.toml (default: auto-discover)."),
    ] = None,
) -> None:
    """Show labeled issues and a summary of the last run."""
    from pathlib import Path

    from nightshift import config as config_module
    from nightshift import diary as diary_module
    from nightshift.github import GitHubAuthError, list_labeled_issues

    # Load config to know the label and limits
    cfg_path = Path(config_path) if config_path else None
    try:
        cfg = config_module.load(cfg_path)
    except config_module.ConfigError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    # 1. List labeled issues
    try:
        issues = list_labeled_issues(cfg.label, limit=cfg.max_issues * 4)
    except Exception as exc:
        typer.echo(f"Error fetching issues: {exc}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Labeled issues (label: '{cfg.label}'):")
    if issues:
        for issue in issues:
            age = (dt.datetime.now(dt.timezone.utc) - issue.created_at).days
            typer.echo(f"  #{issue.number:>4}  {issue.title}  (opened {age}d ago)")
    else:
        typer.echo("  No open issues found with this label.")

    # 2. Last run summary from the most recent JSON log
    typer.echo("")
    runs_dir = Path(".nightshift") / "runs"
    last_log: "diary_module.RunLog | None" = None  # type: ignore[name-defined]
    if runs_dir.exists():
        log_files = sorted(runs_dir.glob("*.json"), reverse=True)
        for log_file in log_files:
            try:
                log_date = dt.date.fromisoformat(log_file.stem)
                last_log = diary_module.load_log(log_date, runs_dir=runs_dir)
                break
            except Exception:
                continue

    if last_log is None:
        typer.echo("Last run: no run logs found.")
    else:
        duration = (last_log.end_time - last_log.start_time).total_seconds()
        dry_tag = " [dry-run]" if last_log.dry_run else ""
        typer.echo(f"Last run: {last_log.date}{dry_tag}")
        typer.echo(f"  Repo     : {last_log.repo}")
        typer.echo(f"  Issues   : {last_log.total_issues}")
        typer.echo(f"  PRs      : {last_log.total_prs}")
        typer.echo(f"  Duration : {duration:.0f}s")

        if last_log.events:
            typer.echo("")
            typer.echo("  Outcomes:")
            for event in last_log.events:
                pr_info = f"  -> {event.pr_url}" if event.pr_url else ""
                typer.echo(
                    f"    #{event.issue_number:>4}  [{event.outcome:<12}]  {event.issue_title}{pr_info}"
                )

    raise typer.Exit(code=0)


# ---------------------------------------------------------------------------
# nightshift schedule install / remove / status
# ---------------------------------------------------------------------------


@schedule_app.command("install")
def schedule_install(
    time: Annotated[
        str,
        typer.Option("--time", help="Time to run in HH:MM format (default: 01:00)."),
    ] = "01:00",
) -> None:
    """Install the OS-level cron / Task Scheduler entry."""
    # Phase 7 will wire this to scheduler.install().
    typer.echo("nightshift schedule install -- not yet implemented")
    raise typer.Exit(code=0)


@schedule_app.command("remove")
def schedule_remove() -> None:
    """Remove the OS-level cron / Task Scheduler entry."""
    # Phase 7 will wire this to scheduler.uninstall().
    typer.echo("nightshift schedule remove -- not yet implemented")
    raise typer.Exit(code=0)


@schedule_app.command("status")
def schedule_status() -> None:
    """Report whether a schedule is installed and the next run time."""
    # Phase 7 will wire this to scheduler.status().
    typer.echo("nightshift schedule status -- not yet implemented")
    raise typer.Exit(code=0)
