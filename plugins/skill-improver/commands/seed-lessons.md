---
description: Install a self-improving lessons loop into this project — queue, archive, SessionStart hook, graph checker, and two skills
---

Load the `skill-improver` skill and run **Workflow 3: Seed the lessons-learned
loop** against the project the user names in the arguments (default: the current
project).

Read `references/lessons-loop.md` first — the reasoning behind each artefact is
the part that keeps the loop from decaying.

Pass along whatever the user said about form: "from this session" / "use what
went wrong today" means `--seed-from-session` (recommend it — the loop arrives
carrying evidence); "just set it up" means `--seed`; "show me what it would do"
means `--dry-run`. Also offer the optional Jev-assisted lesson detection (Workflow 3, Step 1). Run `--dry-run` first: if it reports
`EXISTING LOOP DETECTED` (a project seeded by an earlier version), this is an upgrade — offer
`--upgrade` plus the separate Jev choice (OpenRouter / TypeSafe / Off, never enabled unasked), and
never delete or reseed. The queue and archive are never touched.

Exit 3 means the files are installed but the SessionStart hook is not registered — show the user the
printed line to add to `.claude/settings.json`; do not report success.
