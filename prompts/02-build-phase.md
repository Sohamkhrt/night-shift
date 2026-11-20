Implement the Night Shift project by following the spec in `.kiro/specs/night-shift-core/` (requirements.md, design.md, tasks.md) and the steering docs in `.kiro/steering/`.

Do PHASES: __PHASES__ from tasks.md, in order.
Rules:
- You can read and write files but you cannot run shell commands in this session. A teammate will run `uv sync` and `uv run pytest -q` after you finish and send you any failures. So write code and tests carefully.
- Write `pyproject.toml` by hand (src layout, hatchling build backend, dependencies listed, script entry point `nightshift = "nightshift.cli:app"`, dev dependency group with pytest, hypothesis).
- Tick each task's checkbox in tasks.md (`- [x]`) when its code and tests are written.
- If something in the design is wrong or unclear, make the simplest sensible choice and note it in a "Decisions" section at the bottom of design.md.
At the end, print a short summary of the files you created or changed.
