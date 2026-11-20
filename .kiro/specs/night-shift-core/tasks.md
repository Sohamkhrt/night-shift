# Night Shift Core — Implementation Tasks

Tasks are ordered for incremental delivery. Each task is independently testable. Complete them in order; later tasks depend on earlier ones.

---

## Phase 0 — Scaffolding (Day 1)

- [ ] **T-01** Set up repo: `uv init`, `pyproject.toml` with deps (`typer`, `jinja2`, `gitpython`, `hypothesis`, `pytest`, `pytest-subprocess`), entry point `nightshift = "nightshift.cli:app"`. *(REQ-09)*
- [ ] **T-02** Create `src/nightshift/` package skeleton: empty `__init__.py` in every planned module file. Add `tests/conftest.py` with a `tmp_path`-based bare git repo fixture. Confirm `uv run pytest` passes with zero tests collected. *(infra)*
- [ ] **T-03** Create `nightshift.toml.example` with all config fields documented. *(REQ-09, AC-09.4)*

---

## Phase 1 — Core infrastructure (Days 1–2)

- [ ] **T-04** Implement `shell.py`: `ShellResult`, `ShellError`, `run()`. Unit test: assert command list is passed correctly, stdout captured, non-zero exit raises `ShellError`. *(design: shell.py)*
- [ ] **T-05** Implement `config.py`: `NightShiftConfig` dataclass, `load()`. Unit tests: valid config loads, missing required field raises, secrets not read from file. *(REQ-09)* Property test: round-trip serialization.
- [ ] **T-06** Implement `cli.py` skeleton: `app = typer.Typer()`, stub commands `run`, `diary`, `schedule`, `status` that print "not yet implemented". Confirm `uv run nightshift --help` works. *(design: cli.py)*

---

## Phase 2 — GitHub integration (Day 2)

- [ ] **T-07** Implement `github.py`: `Issue` dataclass, `list_labeled_issues()`, `comment_on_issue()`. Mock `shell.run` in tests; assert correct `gh issue list --json` command and JSON parsing. *(REQ-01, REQ-04)*
- [ ] **T-08** Add `github.py`: `open_pr()` and `add_label()`. Unit tests with mocked `shell.run`. *(REQ-05)*
- [ ] **T-09** Add `github.py`: `validate_auth()` that runs `gh auth status` and raises a clear error on failure. Wire into `cli.py`'s `run` command as the first step. *(REQ-01, AC-01.4)*

---

## Phase 3 — Safety module (Day 3)

- [ ] **T-10** Implement `safety.py`: `make_branch_name(prefix, issue)`. Unit test: basic slug generation. Property tests: never equals `main`/`master`, always valid git ref, idempotent. *(REQ-02, design: safety)*
- [ ] **T-11** Implement `safety.py`: `prepare_branch()` — check for existing branch, `git checkout -b`. Unit test with mocked `shell.run`. *(REQ-02, AC-02.1–AC-02.3)*
- [ ] **T-12** Implement `safety.py`: `check_diff_limits()` — parse `git diff --stat`, raise `OverLimitError`. Unit tests for the parser. Property test: no error when within limits. *(REQ-06)*

---

## Phase 4 — Agent runner (Day 3–4)

- [ ] **T-13** Implement `agent.py`: `build_prompt(issue) -> str` and `AgentResult` dataclass. Unit test prompt contains issue number, title, body. *(REQ-03)*
- [ ] **T-14** Implement `agent.py`: `run(issue, config) -> AgentResult` — subprocess with timeout. Unit tests: normal exit, non-zero exit, `TimeoutExpired`. *(REQ-03, AC-03.2–AC-03.4)*
- [ ] **T-15** Implement `runner.py`: `RunEvent`, `RunLog` dataclasses and `run_issue()` function (single issue, all steps). Unit tests: mock all external calls, verify correct `RunEvent.outcome` for pass/fail/timeout/over-limit/skip. *(REQ-03, REQ-04, REQ-05, REQ-06)*
- [ ] **T-16** Implement `runner.py`: `run_all(config) -> RunLog` — load issues, loop, call `run_issue()`, handle per-issue exceptions. Unit test: multi-issue run with mixed outcomes. *(REQ-01, REQ-03)*

---

## Phase 5 — Ghost Diary (Day 4–5)

- [ ] **T-17** Implement `diary.py`: JSON serialization of `RunLog` to `.nightshift/runs/YYYY-MM-DD.json`. Unit test: file created, round-trip readable. *(REQ-07)*
- [ ] **T-18** Create `templates/diary.html.j2`: HTML template with run header, per-issue cards (ghost name, outcome badge, PR link, test snippet, in-character note), and spooky CSS. No external CDN — all styles inline or in a `<style>` block. *(REQ-07, AC-07.3–AC-07.4)*
- [ ] **T-19** Implement `diary.py`: `render(run_log) -> Path` — Jinja2 render to `.nightshift/diary/YYYY-MM-DD.html`. Unit test: known `RunLog` → check HTML contains issue number and ghost name. Property test: arbitrary `RunLog` never raises. *(REQ-07, AC-07.1–AC-07.5)*
- [ ] **T-20** Wire `nightshift diary` CLI command to load the latest (or `--date`) JSON log and call `Diary.render()`. *(REQ-07)*

---

## Phase 6 — CLI wiring (Day 5)

- [ ] **T-21** Wire `nightshift run` to call `runner.run_all(config)`. Add `--dry-run` flag (overrides config). Print per-issue summary to stdout and diary path at end. *(REQ-01–REQ-07)*
- [ ] **T-22** Wire `nightshift status` to list labeled issues (from `github.list_labeled_issues`) and last run summary (from latest JSON log). *(REQ-01)*
- [ ] **T-23** Add lock file logic to `runner.py`: check `.nightshift/locks/run.lock` at startup, create on entry, delete on exit (with `try/finally`). *(design: safety model)*

---

## Phase 7 — Scheduler (Day 6)

- [ ] **T-24** Implement `scheduler.py`: `Scheduler` protocol, `CronScheduler` (read/write crontab via `crontab -l` / `crontab -`). Unit tests: mock subprocess, assert correct crontab manipulation. *(REQ-08, AC-08.1)*
- [ ] **T-25** Implement `scheduler.py`: `TaskSchedulerScheduler` for Windows (uses `schtasks`). Unit tests: mock subprocess. *(REQ-08, AC-08.2)*
- [ ] **T-26** Add `KiroCrewScheduler` stub with a `NotImplementedError` and a comment pointing to the Kiro Crew docs. *(tech.md: pluggability)*
- [ ] **T-27** Wire `nightshift schedule install/remove/status` CLI subcommand. *(REQ-08)*

---

## Phase 8 — Polish and hackathon deliverables (Days 7–9)

- [ ] **T-28** Write `nightshift.toml.example` and ensure `nightshift run --dry-run` works end-to-end against a real test repo. *(demo readiness)*
- [ ] **T-29** Add `.kiro/hooks/` entries: a post-run hook that opens the diary HTML if on a desktop OS, and a pre-run hook that checks `gh auth status`. *(hackathon: Kiro hooks criterion)*
- [ ] **T-30** Add MCP configuration sketch in `.kiro/` (even if not fully wired) demonstrating the GitHub MCP server as an alternative to `gh` CLI. *(hackathon: MCP criterion)*
- [ ] **T-31** Final README pass: add screenshots/GIF of a dry run, diary screenshot, and "Quick Start" section. *(hackathon: presentation criterion)*
- [ ] **T-32** Run full test suite with `uv run pytest --tb=short -q`. Fix any failures. Check coverage on `safety.py` and `diary.py` (should be >80%). *(quality gate)*

---

## Task summary by requirement

| Requirement | Tasks |
|---|---|
| REQ-01 Issue discovery | T-07, T-09, T-16, T-21, T-22 |
| REQ-02 Branch isolation | T-10, T-11 |
| REQ-03 Coding agent | T-13, T-14, T-15 |
| REQ-04 Test gating | T-15, T-16 |
| REQ-05 PR creation | T-08, T-15 |
| REQ-06 Safety limits | T-12, T-15, T-23 |
| REQ-07 Ghost Diary | T-17, T-18, T-19, T-20 |
| REQ-08 Scheduling | T-24, T-25, T-26, T-27 |
| REQ-09 Configuration | T-01, T-05, T-06 |
