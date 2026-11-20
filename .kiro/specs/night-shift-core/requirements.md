# Night Shift Core — Requirements

## User stories and acceptance criteria

Acceptance criteria use EARS notation:
- **WHEN** [trigger] **THE SYSTEM SHALL** [behavior]
- **WHERE** [feature] **THE SYSTEM SHALL** [constraint]
- **IF** [condition] **THEN THE SYSTEM SHALL** [behavior]

---

### REQ-01 — Issue labeling and discovery

**Story:** As a developer, I want to label GitHub issues with `night-shift` so that the agent knows which issues to work on tonight.

**Acceptance criteria:**

- AC-01.1: WHEN `nightshift run` is invoked, THE SYSTEM SHALL fetch all open issues in the configured repo that carry the configured label (default: `night-shift`).
- AC-01.2: WHERE the issue list exceeds `max_issues`, THE SYSTEM SHALL select only the oldest N issues (by creation date ascending).
- AC-01.3: WHEN no labeled issues are found, THE SYSTEM SHALL exit cleanly with a message and generate a diary entry noting an uneventful night.
- AC-01.4: THE SYSTEM SHALL require `gh auth status` to succeed before fetching issues and fail fast with a human-readable error if it does not.

---

### REQ-02 — Branch isolation

**Story:** As a developer, I want each issue worked on a dedicated branch so that work is isolated and I can review before merging.

**Acceptance criteria:**

- AC-02.1: WHEN processing an issue, THE SYSTEM SHALL create a new git branch named `{branch_prefix}{issue-number}-{slug}` where `slug` is a lowercase, hyphen-separated truncation of the issue title.
- AC-02.2: THE SYSTEM SHALL never push to `main`, `master`, or the repo's default branch.
- AC-02.3: IF a branch with the computed name already exists, THE SYSTEM SHALL skip that issue, leave a comment, and move to the next.
- AC-02.4: WHERE `dry_run = true`, THE SYSTEM SHALL create the branch locally but not push it.

---

### REQ-03 — Autonomous coding agent

**Story:** As a developer, I want a Kiro CLI agent to attempt the fix on each issue so that I wake up to actual code changes, not just plans.

**Acceptance criteria:**

- AC-03.1: WHEN a branch is ready, THE SYSTEM SHALL invoke `kiro-cli chat --no-interactive` with a prompt derived from the issue title, body, and labels.
- AC-03.2: THE SYSTEM SHALL enforce a hard per-issue time limit (`max_minutes`); IF the agent process exceeds this limit, THE SYSTEM SHALL terminate it, record a timeout event, and proceed to the next issue.
- AC-03.3: THE SYSTEM SHALL capture the agent's stdout and stderr and include them in the run log.
- AC-03.4: IF the agent process exits with a non-zero code, THE SYSTEM SHALL record a failure event (not a crash) and proceed to the next issue.

---

### REQ-04 — Test gating

**Story:** As a developer, I want the agent's work tested before a PR is opened so that I never wake up to a broken main.

**Acceptance criteria:**

- AC-04.1: AFTER the agent finishes, THE SYSTEM SHALL run `test_command` in the branch working directory.
- AC-04.2: IF tests pass (exit code 0), THE SYSTEM SHALL proceed to open a PR.
- AC-04.3: IF tests fail, THE SYSTEM SHALL NOT push the branch or open a PR; instead it SHALL post an issue comment with the test output (truncated to 2000 characters).
- AC-04.4: WHERE `dry_run = true`, THE SYSTEM SHALL run tests but skip the push and PR steps regardless of result.

---

### REQ-05 — Pull request creation

**Story:** As a developer, I want a PR opened automatically on success so that review is one click away in the morning.

**Acceptance criteria:**

- AC-05.1: WHEN tests pass and not in dry-run mode, THE SYSTEM SHALL push the branch and open a PR via `gh pr create` with a title referencing the issue number and a body containing the agent summary.
- AC-05.2: THE SYSTEM SHALL add the label `night-shift-pr` to opened PRs.
- AC-05.3: THE SYSTEM SHALL include `Closes #{issue_number}` in the PR body so GitHub auto-links the issue.
- AC-05.4: IF `gh pr create` fails, THE SYSTEM SHALL log the error and record a failure event without crashing the run.

---

### REQ-06 — Safety limits

**Story:** As a developer, I want hard limits on how much code the agent can change so that a runaway ghost can't corrupt my repo.

**Acceptance criteria:**

- AC-06.1: AFTER the agent runs but BEFORE tests, THE SYSTEM SHALL count files changed and lines changed (insertions + deletions from `git diff --stat`).
- AC-06.2: IF either `max_files` or `max_lines` is exceeded, THE SYSTEM SHALL abort the issue (no push, no PR), post an issue comment, and record an over-limit event.
- AC-06.3: WHERE `dry_run = true`, limit checks SHALL still run and be reported.
- AC-06.4: THE SYSTEM SHALL record the actual file/line counts in the run log regardless of whether limits were breached.

---

### REQ-07 — Ghost Diary generation

**Story:** As a developer, I want a spooky HTML summary of the night's work waiting for me in the morning so that I can review everything at a glance.

**Acceptance criteria:**

- AC-07.1: WHEN a nightly run completes (or when `nightshift diary` is invoked), THE SYSTEM SHALL render the Ghost Diary HTML from the run's JSON log using the Jinja2 template.
- AC-07.2: THE SYSTEM SHALL assign a ghost name (from the configured roster) to each issue, consistently within a run.
- AC-07.3: THE DIARY SHALL include, for each issue: ghost name, issue number and title, outcome (PR opened / test failed / timeout / over-limit / skipped), PR link (if applicable), test result summary, and a one-line in-character note.
- AC-07.4: THE DIARY SHALL include a run summary header: start time, end time, total issues attempted, total PRs opened.
- AC-07.5: IF no run log exists for the requested date, THE SYSTEM SHALL output a "quiet night" diary with the correct date.

---

### REQ-08 — Scheduling

**Story:** As a developer, I want to run `nightshift schedule` once and have the nightly run happen automatically so that I don't need to remember to trigger it.

**Acceptance criteria:**

- AC-08.1: WHEN `nightshift schedule install` is invoked on Linux/macOS, THE SYSTEM SHALL add a crontab entry for `nightshift run` at the configured time.
- AC-08.2: WHEN `nightshift schedule install` is invoked on Windows, THE SYSTEM SHALL create a Task Scheduler entry for `nightshift run`.
- AC-08.3: `nightshift schedule remove` SHALL remove the entry created by `install`.
- AC-08.4: `nightshift schedule status` SHALL report whether a schedule is installed and the next scheduled run time.

---

### REQ-09 — Configuration

**Story:** As a developer, I want to configure Night Shift via a committed `nightshift.toml` file so that settings are version-controlled.

**Acceptance criteria:**

- AC-09.1: THE SYSTEM SHALL load `nightshift.toml` from the current working directory; if absent, it SHALL fall back to `~/.config/nightshift/config.toml`.
- AC-09.2: IF a required field is missing and has no default, THE SYSTEM SHALL report all missing fields at startup and exit before doing any work.
- AC-09.3: THE SYSTEM SHALL never read secrets (tokens) from the config file; tokens SHALL come from environment variables only.
- AC-09.4: All config fields SHALL have documented defaults in `nightshift.toml.example` committed to the repo.
