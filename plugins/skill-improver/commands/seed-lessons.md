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
means `--dry-run`. If a loop is already installed the installer stops with exit 2
— offer `--upgrade` rather than deleting anything.
