# Night Shift — Structure Steering

## Planned folder layout

```
night-shift/
├── .kiro/
│   ├── steering/
│   │   ├── product.md
│   │   ├── tech.md
│   │   └── structure.md
│   ├── specs/
│   │   └── night-shift-core/
│   │       ├── requirements.md
│   │       ├── design.md
│   │       └── tasks.md
│   └── hooks/                     # Kiro automation hooks (post-run diary, etc.)
│
├── src/
│   └── nightshift/
│       ├── __init__.py
│       ├── cli.py                 # Typer app, entry points for all commands
│       ├── config.py              # Load/validate nightshift.toml
│       ├── github.py              # gh CLI wrapper (list issues, comment, open PR)
│       ├── agent.py               # Spawn and supervise a kiro-cli chat session
│       ├── runner.py              # Orchestrate one nightly run across N issues
│       ├── safety.py              # Branch naming, change limits, time limits, dry-run
│       ├── diary.py               # Collect run events, render Ghost Diary HTML
│       ├── scheduler.py           # Scheduler protocol + CronScheduler + TaskScheduler
│       ├── shell.py               # Subprocess wrapper (log + capture)
│       └── templates/
│           └── diary.html.j2      # Jinja2 template for the Ghost Diary
│
├── tests/
│   ├── conftest.py                # Shared fixtures (tmp git repo, mock gh, etc.)
│   ├── test_config.py
│   ├── test_github.py
│   ├── test_safety.py             # Property-based tests (hypothesis)
│   ├── test_diary.py              # Property-based tests (hypothesis)
│   ├── test_runner.py
│   └── test_scheduler.py
│
├── .nightshift/                   # Runtime data (gitignored except skeleton)
│   └── runs/                      # JSON logs: YYYY-MM-DD.json
│
├── nightshift.toml                # Project-level config (committed as example)
├── pyproject.toml
├── uv.lock
├── README.md
└── LICENSE
```

## Module responsibilities (one-line each)

| Module | Responsibility |
|---|---|
| `cli.py` | Parse commands and flags, delegate to other modules, print results. |
| `config.py` | Read `nightshift.toml`, apply defaults, validate types. |
| `github.py` | Wrap `gh` CLI: fetch labeled issues, post comments, open PRs. |
| `agent.py` | Build the prompt, spawn `kiro-cli chat --no-interactive`, stream output. |
| `runner.py` | Pick issues up to N, loop over them, call agent, run tests, decide PR vs comment. |
| `safety.py` | Enforce branch naming rules, max file/line change limits, per-issue time limits. |
| `diary.py` | Accumulate `RunEvent` objects during a run, then render the Jinja2 template. |
| `scheduler.py` | Install/remove OS-level schedule entries. |
| `shell.py` | Single subprocess execution point: log command, capture output, raise on error. |

## What lives in `.nightshift/` (runtime, gitignored)

- `runs/YYYY-MM-DD.json` — structured log of each night's run events.
- `diary/YYYY-MM-DD.html` — rendered Ghost Diary output.
- `locks/` — per-issue lock files to prevent double-runs.

## Configuration file shape (`nightshift.toml`)

```toml
[nightshift]
label         = "night-shift"       # GitHub issue label to watch
max_issues    = 5                   # Max issues per nightly run
max_minutes   = 15                  # Hard time limit per issue
max_files     = 20                  # Max files changed per issue
max_lines     = 500                 # Max lines changed per issue
test_command  = "pytest"            # Command to run after agent finishes
branch_prefix = "night-shift/"     # Branch name prefix
dry_run       = false               # Set true to skip push/PR

[diary]
ghost_names   = ["Casper", "Spook", "Wraith", "Phantom", "Specter"]
output_dir    = ".nightshift/diary"
```
