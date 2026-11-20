We're building "Night Shift" for the Kiroween 2026 hackathon (Devpost, deadline Dec 4 2026).

ONE-LINER: Like the elves and the shoemaker: you go to sleep, little ghost agents fix your GitHub issues overnight, and in the morning you wake up to pull requests plus a spooky "Ghost Diary" telling you what they did.

HOW IT WORKS (MVP):
1. User labels GitHub issues with `night-shift` in a repo they own.
2. On a schedule (e.g. 1:00 AM), Night Shift picks up to N labeled issues.
3. For each issue: create a branch, run a headless coding agent (Kiro CLI, `kiro-cli chat --no-interactive`) in that branch with the issue text as the task, run the repo's tests, and only if tests pass, push and open a PR (via `gh`). If tests fail, leave a comment on the issue explaining what the ghost tried.
4. In the morning, generate the "Ghost Diary": a polished, spooky-but-readable HTML page (and optional email/Discord message) summarizing each night's work: issue, what changed, tests, PR link, and a short in-character note from the ghost who worked on it.
5. Safety: never push to main, max files/lines changed per issue, dry-run mode, and a hard time limit per issue.

TECH CONSTRAINTS:
- Python 3.11, managed with uv. Typer CLI (`nightshift run`, `nightshift diary`, `nightshift schedule`). Use `gh` CLI for GitHub. Jinja2 for the diary HTML. pytest + hypothesis for tests.
- Must run on Windows (Task Scheduler) and Linux/macOS (cron). Keep the scheduler pluggable so Kiro Crew schedules can be added later.
- The developer is strong in Python. Keep the architecture simple and solo-buildable in ~10 days.

HACKATHON REQUIREMENTS TO RESPECT:
- Judging: Potential Impact, Technological Implementation (deep, varied use of Kiro: specs, hooks, steering, MCP, property-based testing), Design, Innovation, Presentation. Equal weights.
- The repo is public with an MIT license, and `/.kiro` must be committed (never gitignore it).
- Category target: Frankenstein (stitching scheduler + agent + GitHub + diary) or Skeleton Crew. Also aim for the "Best Kiro Crew App" bonus later.

YOUR TASK RIGHT NOW (planning only, do NOT write application code yet):
A. Create steering files in `.kiro/steering/`: `product.md` (what and why, the ghost theme, tone), `tech.md` (stack, commands, conventions), `structure.md` (planned folder layout).
B. Create a spec in `.kiro/specs/night-shift-core/`: `requirements.md` (user stories with EARS-style acceptance criteria), `design.md` (architecture, components, data model, sequence of a nightly run, safety model, error handling, testing strategy including property-based tests), and `tasks.md` (a numbered, incremental checklist of small implementation tasks, each referencing requirements).
C. Add a README.md with the one-liner, and add an MIT LICENSE file.
Keep everything concise and practical. When done, list the files you created.
