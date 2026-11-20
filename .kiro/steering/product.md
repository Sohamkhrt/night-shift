# Night Shift — Product Steering

## What it is

Night Shift is an autonomous overnight coding assistant. You label GitHub issues with `night-shift` before you go to sleep. At 1 AM, a fleet of headless Kiro ghost agents picks up those issues, writes code on isolated branches, runs your tests, and either opens a pull request or leaves a comment explaining what it tried. In the morning your inbox contains a "Ghost Diary" — a spooky HTML summary of everything that happened while you slept.

The name comes from the fairy tale of the elves and the shoemaker. You leave the work out; the ghosts do it overnight; you wake up to finished shoes (or at least honest attempt notes).

## Why it matters

Developers context-switch constantly to handle small, well-specified issues — dependency upgrades, typo fixes, small feature requests, test coverage gaps. These tasks are ideal for autonomous agents but jarring to context-switch into during a focused work session. Night Shift removes that friction: batch them up, label them, sleep.

## Target user

A solo developer or small team who:
- Uses GitHub Issues for task tracking.
- Has a repo with a runnable test suite.
- Wants to wake up to meaningful progress, not just CI results.

## Ghost theme and tone

Night Shift leans into a playful Halloween aesthetic without being annoying.

- Ghost agents are referred to as "ghosts" or "night workers," never "bots" or "AI."
- Each ghost is assigned a name from a small roster (e.g. Casper, Spook, Wraith, Phantom, Specter) for personality in the diary.
- The Ghost Diary uses spooky-but-readable language: "Spook drifted into issue #42 at 01:03 AM and left a pull request by 01:17 AM."
- Error messages are honest and helpful first, atmospheric second. Correctness over flavor.
- The CLI output is clean and professional. Spooky language lives in the diary HTML, not in `--help` text or stack traces.

## Success criteria for the hackathon

1. A live demo: label an issue, run `nightshift run --dry-run`, show the diary output.
2. The `.kiro` folder is committed and showcases specs, steering, hooks, and MCP configuration.
3. The repo tells a clear story: someone reading the README can understand and run it in under 5 minutes.
4. Property-based tests (Hypothesis) are present and meaningful, not decorative.
