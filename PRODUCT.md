# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primary:** a solo developer or small team who tracks work in GitHub Issues and has a runnable test suite. They label small, well-specified issues `night-shift` before bed and open the Ghost Diary in the morning to see what got done.
- **Priority audience for the diary page right now:** Kiroween 2026 hackathon judges, who see it in a demo video under 3 minutes and in screenshots. The page must also work as a real morning report.

## Product Purpose

Night Shift is an autonomous overnight coding assistant. On a schedule (e.g. 1 AM), headless Kiro "ghost" agents pick up labeled issues, work on isolated branches, run the tests, and either open a pull request or leave an honest comment explaining what they tried. Success: you wake up to real progress on chores you never had to context-switch into.

## Positioning

The elves and the shoemaker for code. You leave the work out, ghosts do it overnight, and the morning report reads like a diary of the night shift rather than a CI log.

## Operating Context

- The Ghost Diary is a local, self-contained HTML file rendered by Jinja2 (`src/nightshift/templates/diary.html.j2`) to `.nightshift/diary/YYYY-MM-DD.html` and opened in a browser. It is not sent as email.
- The CLI is the other surface; it stays clean and professional, with no spooky language.

## Capabilities and Constraints

- Per-issue outcomes: `pr_opened`, `test_failed`, `timeout`, `over_limit`, `skipped`, `agent_error`.
- Each event has: issue number/title, ghost name, branch, duration, optional note, PR URL, diff stats, test output, agent output.
- Run-level data: date, dry-run flag, repo, start/end time, totals.
- No external CDN or network assets: a single self-contained file.
- Safety guarantees (never pushes to main, diff limits, time limits) are real product facts.

## Brand Commitments

- Ghost agents are called "ghosts" or "night workers", never "bots" or "AI".
- Ghosts have names from a roster (Casper, Spook, Wraith, Phantom, Specter).
- Tone: spooky but readable. Honest and helpful first, atmospheric second.

## Evidence on Hand

No real run data, users, or testimonials exist yet. Demo data must be clearly sample data.

## Product Principles

1. Honesty over flavor: failures are reported plainly.
2. The morning glance: in five seconds you know what shipped and what needs you.
3. Safe by default: nothing touches main.
