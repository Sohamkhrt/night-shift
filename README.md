# 👻 Night Shift

> Like the elves and the shoemaker: you go to sleep, little ghost agents fix your GitHub issues overnight, and in the morning you wake up to pull requests plus a spooky **Ghost Diary** telling you what they did.

Built for the [Kiroween 2026 Hackathon](https://kiroween2026.devpost.com/) · Category: **Frankenstein** · Bonus target: **Best Kiro Crew App**

---

## How it works

1. **Label** your GitHub issues with `night-shift`.
2. **Go to sleep.** At 1 AM, Night Shift picks up to N labeled issues.
3. For each issue it: creates an isolated branch → runs a headless Kiro CLI agent → runs your tests → opens a PR if they pass, or leaves a comment explaining what the ghost tried if they fail.
4. **Wake up** to pull requests and the Ghost Diary — a polished HTML summary of every ghost's night's work.

```
nightshift run            # run right now (or via cron/Task Scheduler at 1 AM)
nightshift run --dry-run  # simulate without pushing anything
nightshift diary          # regenerate today's Ghost Diary HTML
nightshift schedule       # install the OS-level schedule
nightshift status         # see labeled issues and last run summary
```

---

## Quick start

**Prerequisites:** Python 3.11+, [`uv`](https://docs.astral.sh/uv/), [`gh` CLI](https://cli.github.com/) authenticated to GitHub, [`kiro-cli`](https://kiro.dev) installed.

```bash
# 1. Clone
git clone https://github.com/your-username/night-shift.git
cd night-shift

# 2. Install
uv sync

# 3. Configure
cp nightshift.toml.example nightshift.toml
# Edit nightshift.toml: set your repo, test command, and limits

# 4. Dry run against a labeled issue
uv run nightshift run --dry-run

# 5. Open the diary
open .nightshift/diary/$(date +%Y-%m-%d).html
```

---

## Configuration (`nightshift.toml`)

```toml
[nightshift]
label        = "night-shift"   # issue label to watch
max_issues   = 5               # max issues per run
max_minutes  = 15              # hard time limit per issue
max_files    = 20              # max files changed
max_lines    = 500             # max lines changed
test_command = "pytest"        # command to validate the agent's work
dry_run      = false           # true = no push, no PR, no comments

[diary]
ghost_names  = ["Casper", "Spook", "Wraith", "Phantom", "Specter"]
```

Secrets (GitHub tokens) come from the environment, not this file. `gh` CLI handles auth.

---

## Safety

- **Never pushes to `main` or `master`.** Every issue gets its own branch.
- **Hard time limit** per issue (`max_minutes`) — the agent is killed if it overruns.
- **Change limits** — if the agent touches more than `max_files` files or `max_lines` lines, the branch is abandoned.
- **Tests must pass** before a PR is opened. Failed tests → issue comment only.
- **Dry-run mode** — does everything except push, open PRs, or post comments.
- **Lock file** — prevents concurrent runs.

---

## Project structure

```
src/nightshift/   Python package (cli, config, github, agent, runner, safety, diary, scheduler, shell)
tests/            pytest + hypothesis property-based tests
.kiro/            Kiro steering, specs, and hooks (committed)
.nightshift/      Runtime logs and diary output (gitignored)
```

---

## Kiro integration

This project was designed with Kiro from the ground up:

- `.kiro/steering/` — product, tech, and structure steering documents.
- `.kiro/specs/night-shift-core/` — EARS-style requirements, architecture design, and incremental task checklist.
- `.kiro/hooks/` — post-run diary opener, pre-run auth check.
- MCP configuration sketch for the GitHub MCP server.
- Property-based tests via Hypothesis on the safety model and diary renderer.

---

## License

MIT — see [LICENSE](LICENSE).
