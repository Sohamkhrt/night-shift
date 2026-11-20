# Night Shift Core — Design

## Architecture overview

Night Shift is a single-process Python application. There is no server, no daemon, and no persistent background process. The scheduler (cron or Task Scheduler) wakes `nightshift run` at the configured time; the process runs to completion and exits. All state is captured in a JSON log file.

```
nightshift run
      │
      ▼
  Config ──────────────── load nightshift.toml
      │
      ▼
  GitHub ──────────────── gh issue list --label night-shift
      │
      ▼
  Runner (loop over issues)
      │
      ├─► Safety.make_branch()     create + checkout branch
      ├─► Agent.run(issue)         kiro-cli chat --no-interactive
      ├─► Safety.check_limits()    git diff --stat
      ├─► Shell.run(test_command)  pytest (or configured command)
      ├─► GitHub.open_pr()         gh pr create   (on pass)
      │   └─► GitHub.comment()     gh issue comment (on fail)
      └─► Diary.record(event)      append RunEvent to log
      │
      ▼
  Diary.render()          Jinja2 → .nightshift/diary/YYYY-MM-DD.html
```

## Components

### `config.py`

Reads `nightshift.toml` using `tomllib`. Produces a `NightShiftConfig` dataclass. Validates required fields and types at import time (before any side effects). Exposes a `load(path: Path | None) -> NightShiftConfig` factory.

### `github.py`

Thin wrapper around `gh` CLI. Functions:
- `list_labeled_issues(label, limit) -> list[Issue]`
- `open_pr(branch, title, body) -> str` (returns PR URL)
- `comment_on_issue(issue_number, body) -> None`
- `add_label(pr_number, label) -> None`

All functions call `shell.run()` and parse JSON output from `gh ... --json`.

### `agent.py`

Builds the prompt string from an `Issue` object and calls `kiro-cli chat --no-interactive`. Runs in a subprocess with a `timeout` enforced via `subprocess.run(..., timeout=max_seconds)`. Returns an `AgentResult(success, output, duration_seconds)`.

Prompt template (plain text, not Jinja2):
```
You are working on a GitHub issue in the repository at the current directory.

Issue #{number}: {title}

{body}

Labels: {labels}

Please implement a fix or feature that satisfies this issue. Keep changes minimal and focused. Do not modify unrelated files.
```

### `runner.py`

Orchestrates a full nightly run. Accepts a `NightShiftConfig` and returns a `RunLog`. For each issue (up to `max_issues`):

1. Call `Safety.prepare_branch(issue)` → branch name or skip.
2. Call `Agent.run(issue, timeout)` → `AgentResult`.
3. Call `Safety.check_diff_limits(config)` → `DiffStats` or `OverLimitError`.
4. Call `shell.run(config.test_command)` → pass/fail.
5. If pass and not dry-run: `GitHub.open_pr(...)`.
6. If fail: `GitHub.comment_on_issue(...)`.
7. Append a `RunEvent` to the log.

After the loop: call `Diary.render(run_log)`.

### `safety.py`

- `make_branch_name(prefix, issue) -> str`: sanitizes the issue title to a slug, assembles the full branch name. Pure function — testable with Hypothesis.
- `prepare_branch(issue, config) -> str | None`: checks if branch exists, creates and checks out, returns name or None to skip.
- `check_diff_limits(max_files, max_lines) -> DiffStats`: runs `git diff --stat HEAD`, parses output, raises `OverLimitError` if exceeded.

### `diary.py`

Accumulates `RunEvent` objects. At the end of a run, serializes the full `RunLog` to `.nightshift/runs/YYYY-MM-DD.json`, then renders the Jinja2 template to `.nightshift/diary/YYYY-MM-DD.html`.

Ghost assignment: `ghost = ghost_names[issue_number % len(ghost_names)]` — deterministic so rerenders produce the same ghost names.

### `scheduler.py`

Implements the `Scheduler` protocol with `CronScheduler` and `TaskSchedulerScheduler`. Detection via `sys.platform`. The `KiroCrewScheduler` stub logs a "not yet implemented" message.

### `shell.py`

```python
def run(cmd: list[str], cwd: Path | None = None, timeout: int | None = None) -> ShellResult:
    ...
```

Logs the command at DEBUG level, captures stdout and stderr, raises `ShellError` on non-zero exit (unless `check=False`). Never uses `shell=True`.

---

## Data model

```python
@dataclass
class Issue:
    number: int
    title: str
    body: str
    labels: list[str]
    created_at: datetime

@dataclass
class AgentResult:
    success: bool
    output: str            # combined stdout + stderr, truncated to 10k chars
    duration_seconds: float

@dataclass
class DiffStats:
    files_changed: int
    lines_added: int
    lines_removed: int

@dataclass
class RunEvent:
    issue_number: int
    issue_title: str
    ghost_name: str
    branch: str
    outcome: Literal["pr_opened", "test_failed", "timeout", "over_limit", "skipped", "agent_error"]
    pr_url: str | None
    diff_stats: DiffStats | None
    test_output: str | None        # truncated to 2000 chars
    agent_output: str | None       # truncated to 2000 chars
    duration_seconds: float
    note: str                      # one-line in-character diary note

@dataclass
class RunLog:
    date: date
    start_time: datetime
    end_time: datetime
    repo: str
    dry_run: bool
    events: list[RunEvent]
```

---

## Sequence: one nightly run

```
1.  Load config
2.  Validate gh auth
3.  Fetch labeled issues (up to max_issues oldest)
4.  For each issue:
    a. Compute branch name
    b. Check if branch exists → skip if yes
    c. git checkout -b {branch}
    d. Build agent prompt
    e. Spawn kiro-cli chat --no-interactive (with timeout)
    f. git diff --stat HEAD → check limits
    g. Run test_command
    h. If tests pass and not dry-run:
         git push origin {branch}
         gh pr create ...
       Else:
         gh issue comment #{number} ...
    i. Record RunEvent
    j. git checkout {default_branch}  (restore working tree)
5.  Render Ghost Diary HTML
6.  Print summary to stdout
7.  Exit 0
```

---

## Safety model

| Concern | Mechanism |
|---|---|
| Pushing to default branch | Explicit check in `prepare_branch`; refuse if branch name == default |
| Runaway agent | `subprocess.run(timeout=max_seconds)` → `TimeoutExpired` caught |
| Excessive changes | `git diff --stat` parsed after agent exits, before tests |
| Broken tests reaching main | Tests must pass before `gh pr create` is called |
| Credential leakage | Tokens from env vars only; `shell.py` redacts env from logs |
| Concurrent runs | Lock file `.nightshift/locks/run.lock` checked at startup |
| Dry-run safety | `dry_run=True` skips all push/PR/comment operations |

---

## Error handling

- **Config errors**: logged to stderr, exit code 1, no work started.
- **`gh` auth failure**: logged to stderr, exit code 1, no work started.
- **Per-issue errors** (agent crash, timeout, over-limit, test failure): recorded as a `RunEvent` with the appropriate outcome. The run continues to the next issue. The process exits 0 (a failed issue is not a program crash).
- **Unexpected exceptions**: caught at the runner loop level, logged with traceback, recorded as `outcome="agent_error"`, run continues.
- **Diary render failure**: logged as a warning; the JSON log is always written first so the diary can be rerendered with `nightshift diary`.

---

## Testing strategy

### Unit tests (pytest)

- `test_config.py`: valid config, missing fields, type errors, env-var secret exclusion.
- `test_github.py`: mock `shell.run`, assert correct `gh` commands and JSON parsing.
- `test_safety.py`: branch name generation (see property tests), diff stat parsing, limit checks.
- `test_diary.py`: diary render with known `RunLog`, HTML structure checks.
- `test_runner.py`: mock agent + gh + shell, verify correct RunEvent outcomes for each scenario.
- `test_scheduler.py`: mock `subprocess`, assert crontab / schtasks commands.

### Property-based tests (Hypothesis)

**`test_safety.py`**
- `make_branch_name` never produces a branch equal to `main` or `master`.
- `make_branch_name` output is always a valid git ref (no spaces, no `..`, no leading `-`).
- `make_branch_name` is idempotent: calling it twice with the same input gives the same result.
- `check_diff_limits` never raises `OverLimitError` when both counts are within limits.

**`test_diary.py`**
- Rendering a `RunLog` with arbitrary `RunEvent` data never raises an exception.
- Ghost assignment (`issue_number % len(names)`) always returns a name in the roster.
- Diary HTML always contains the run date string for any valid date.

**`test_config.py`**
- Round-trip: any valid `NightShiftConfig` serialized to TOML and re-parsed produces the same config.



---

## Decisions

Choices made during Phase 0–3 implementation where the design was silent or ambiguous.

| # | Location | Decision |
|---|---|---|
| D-01 | `config.py` — required fields | Only `test_command` is required; every other field has a sensible default. The design doc did not specify which fields are required; this is the most user-friendly interpretation. |
| D-02 | `config.py` — round-trip TOML serialization | A local `config_to_toml()` helper in `test_config.py` serializes a `NightShiftConfig` back to TOML for the Hypothesis round-trip test. This avoids a `tomli-w` dev dependency. |
| D-03 | `safety.py` — `prepare_branch` signature | The design shows `prepare_branch(issue, config)` but that couples the function to two separate concerns. The implementation takes only `branch_name: str` (the output of `make_branch_name`), keeping it focused and easier to unit-test. The caller (Phase 4 runner) is responsible for composing the two. |
| D-04 | `safety.py` — existing branch detection | The design said "check if branch exists" without specifying how. `git branch --list <name>` is used because it is portable across all git versions and platforms without extra parsing. |
| D-05 | `safety.py` — `check_diff_limits` diff target | `git diff --stat HEAD` is used (working tree vs HEAD). This captures all changes since the last commit, including untracked staged or unstaged changes from the agent. An alternative (`--cached`) would miss unstaged files; the design explicitly said "after agent runs, before tests". |
| D-06 | `github.py` — `open_pr` push responsibility | `open_pr()` performs both `git push origin <branch>` and `gh pr create`. The design described `runner.py` calling push + PR separately, but consolidating them in `open_pr` reduces error-prone sequencing at call sites. |
| D-07 | `shell.py` — `input` parameter name shadows builtin | The parameter is named `input` to match `subprocess.run`'s API for familiarity, accepting the shadow of the builtin. A `# noqa` comment would suppress any linter warning. |
