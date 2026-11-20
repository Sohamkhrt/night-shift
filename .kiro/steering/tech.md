# Night Shift — Tech Steering

## Runtime and package management

- Python 3.11. Managed with `uv` (no pip, no poetry).
- `uv sync` to install; `uv run nightshift` to invoke.
- `pyproject.toml` is the single source of truth for deps and metadata.

## Key dependencies

| Purpose | Library |
|---|---|
| CLI framework | `typer` |
| GitHub operations | `gh` CLI (subprocess) |
| Git operations | `subprocess` + `gitpython` |
| Diary templating | `jinja2` |
| Property-based tests | `hypothesis` |
| Unit/integration tests | `pytest` |
| Config file | `tomllib` (stdlib 3.11) |
| Scheduling shim | `schedule` (pluggable, see below) |

## CLI commands

```
nightshift run            # Execute a nightly run right now
nightshift run --dry-run  # Simulate without pushing or opening PRs
nightshift diary          # Regenerate the HTML diary from last run's log
nightshift schedule       # Install the OS-level schedule (cron / Task Scheduler)
nightshift status         # Show labeled issues and last run summary
```

## Coding conventions

- Type hints everywhere. No bare `Any` except at subprocess boundaries.
- Dataclasses (or `@dataclass`) for all data models. No raw dicts passed between modules.
- All subprocess calls go through a single `shell.run()` wrapper that logs the command and captures stdout/stderr.
- Never `subprocess.shell=True` with untrusted input.
- Configuration lives in `nightshift.toml` at the repo root (or `~/.config/nightshift/config.toml` for global defaults).
- Secrets (GitHub tokens) come from environment variables, never from config files committed to git.
- Log with the stdlib `logging` module. One JSON log file per nightly run, written to `.nightshift/runs/YYYY-MM-DD.json`.

## GitHub integration

- All GitHub reads/writes use the `gh` CLI. No direct REST calls; `gh` handles auth.
- Required `gh` commands: `gh issue list`, `gh issue comment`, `gh pr create`, `gh repo view`.
- Validate `gh auth status` at startup; fail fast with a clear message if not authenticated.

## Scheduler pluggability

The scheduler module exposes a single interface:

```python
class Scheduler(Protocol):
    def install(self, command: str, cron_expr: str) -> None: ...
    def uninstall(self) -> None: ...
    def status(self) -> str: ...
```

Concrete implementations: `CronScheduler` (Linux/macOS), `TaskSchedulerScheduler` (Windows). A `KiroCrewScheduler` stub is included but not wired — it documents the hook for the bonus category.

## Testing strategy

- `pytest` for unit and integration tests under `tests/`.
- `hypothesis` for property-based tests on the safety model (branch name generation, line-change limits, config parsing, diary rendering with arbitrary issue data).
- Use `pytest-subprocess` or `unittest.mock` to mock `gh` and `git` subprocess calls in unit tests.
- Integration tests run against a local bare git repo created in a `tmp_path` fixture.
- Target: all core logic (issue selection, branch naming, safety checks, diary rendering) covered by property-based tests.

## Cross-platform notes

- Use `pathlib.Path` everywhere, never string concatenation for paths.
- Scheduler detection: `sys.platform` — `"win32"` → Task Scheduler, else → cron.
- End-of-line: let `gitpython` handle it; don't hardcode `\n` vs `\r\n`.
- Shell activation for `uv run` is the same on all platforms.
