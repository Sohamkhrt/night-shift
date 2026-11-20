"""cli.py — Typer application and command definitions for Night Shift.

Entry point: ``nightshift = "nightshift.cli:app"`` in pyproject.toml.

Commands implemented here as stubs (Phase 2–6 will fill them in):
  nightshift run       -- kick off (or simulate) a nightly run
  nightshift diary     -- (re-)render the Ghost Diary HTML
  nightshift schedule  -- install/remove/status OS-level schedule
  nightshift status    -- show labeled issues and last run summary
"""

from __future__ import annotations

from typing import Annotated, Optional

import typer

from nightshift.github import GitHubAuthError, validate_auth

app = typer.Typer(
    name="nightshift",
    help=(
        "👻 Night Shift — autonomous overnight GitHub issue agent.\n\n"
        "Label issues with 'night-shift', go to sleep, wake up to pull requests."
    ),
    no_args_is_help=True,
)

# Sub-app for the `schedule` command group
schedule_app = typer.Typer(help="Install or manage the OS-level schedule.")
app.add_typer(schedule_app, name="schedule")


# ---------------------------------------------------------------------------
# nightshift run
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
    config: Annotated[
        Optional[str],
        typer.Option("--config", help="Path to nightshift.toml (default: auto-discover)."),
    ] = None,
) -> None:
    """Run Night Shift right now (or simulate with --dry-run).

    Fetches labeled issues, processes each one with a Kiro ghost agent,
    runs tests, and opens PRs on success.
    """
    # Step 1: validate GitHub auth before doing any work (AC-01.4)
    try:
        validate_auth()
    except GitHubAuthError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    # Phase 6 will wire the rest to runner.run_all().
    typer.echo("nightshift run — not yet implemented")
    raise typer.Exit(code=0)


# ---------------------------------------------------------------------------
# nightshift diary
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
    # Phase 5 will wire this to diary.render().
    typer.echo("nightshift diary — not yet implemented")
    raise typer.Exit(code=0)


# ---------------------------------------------------------------------------
# nightshift status
# ---------------------------------------------------------------------------


@app.command()
def status(
    config: Annotated[
        Optional[str],
        typer.Option("--config", help="Path to nightshift.toml (default: auto-discover)."),
    ] = None,
) -> None:
    """Show labeled issues and a summary of the last run."""
    # Phase 6 will wire this to github.list_labeled_issues and the JSON log.
    typer.echo("nightshift status — not yet implemented")
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
    typer.echo("nightshift schedule install — not yet implemented")
    raise typer.Exit(code=0)


@schedule_app.command("remove")
def schedule_remove() -> None:
    """Remove the OS-level cron / Task Scheduler entry."""
    # Phase 7 will wire this to scheduler.uninstall().
    typer.echo("nightshift schedule remove — not yet implemented")
    raise typer.Exit(code=0)


@schedule_app.command("status")
def schedule_status() -> None:
    """Report whether a schedule is installed and the next run time."""
    # Phase 7 will wire this to scheduler.status().
    typer.echo("nightshift schedule status — not yet implemented")
    raise typer.Exit(code=0)
