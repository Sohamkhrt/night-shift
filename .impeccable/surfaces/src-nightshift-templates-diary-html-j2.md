---
version: 1
slug: "src-nightshift-templates-diary-html-j2"
primary_target: "src/nightshift/templates/diary.html.j2"
related_targets: []
---

# Ghost Diary (diary.html.j2)

Scope: the morning report HTML, rendered by Jinja2, opened locally in a browser. Mode: Read.
Audience: hackathon judges first (demo video, screenshots), then the developer at 7 AM. Job: in five seconds know what shipped and what needs you, then read the ghosts' notes and evidence.
Constraints: single self-contained file, no CDN or web fonts (system font stacks only), all Jinja variables preserved, honest failure reporting.

## Direction contract

THESIS: The ghosts are a hotel's night staff and this is their handover sheet, read under the key board at shift change. Refuses the default dark dashboard of stat tiles and status pills.

OWN-WORLD: Deep desk-leather green frame (#16302a family) with brass key tags (#b08d57) on hooks; ivory card-stock handover sheet (#f4efe3) with ink-black text; oxblood (#7a1f2b) reserved for "needs you". Tags are numbered in a condensed DIN-like face (Bahnschrift stack); the sheet's letterhead is a centred, tracked engraved-stationery line; body in a calm system serif reading face.

STORY: Glance at the board: brass tags hang for fixed issues, a red card hangs where you're needed. Read the handover: each ghost's timestamped entry, its words beside its proof. Act: open the PRs, look at the red ones.

FIRST VIEWPORT: Full-width green key-board band at top holding one brass tag per issue (number + outcome mark ● ○ ✕ ◐), a small legend, the hotel-style masthead "Night Shift · Night Desk Handover" with date, repo and shift hours. Below, centred ivory sheet (max ~68ch column): totals line, then entries. Primary action: each entry's PR link.

FORM: Night-porter handover sheet + key-and-pigeonhole board; grounded list position 5. seed:fa4d56d0c40ac5a2. Raises: claim-beside-proof (from monochrome canon); outcome as a mark in a fixed cell (from timetable rack); structure showing via one tag per issue (from coptic binding).

SIGNATURE: tags sway once on load like keys settling on hooks (reduced-motion: none); clicking a tag scrolls to and highlights its entry.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
