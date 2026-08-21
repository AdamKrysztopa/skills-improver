# Seeding the lessons-learned loop

How to install a self-improving lessons loop into a host project, and — more importantly — what
each piece is for, so you can adapt names to the project's conventions without hollowing it out.

**An implementation that keeps the file names and drops the reasoning will produce something that
looks like this and decays within a month.** Every choice below exists because the obvious
alternative fails in a specific, named way.

## The premise

Most projects capture lessons in a style guide, a retro doc, or a CONTRIBUTING file. All three
fail the same way: they only work if someone reads them at the moment the mistake is about to be
made. **A process improvement you have to remember to apply is one that decays.**

The fix is two-part: route each lesson to the artefact that is *already executing* at the moment
of the mistake, and make the capture itself something the workflow refuses to skip.

## The three failure modes any implementation must defeat

| Failure | What it looks like | What defeats it |
|---|---|---|
| **Capture-too-late** | lessons written at the end of a session; by then the bug is fixed, the diff looks clean, and the only trace is a correction nobody can reconstruct into a rule | the `lessons` skill fires *at the moment the mistake is caught*, and writes only |
| **Wrong-artefact** | a lesson whose honest moment was "while someone was typing an edit" lands as a sentence in a style guide — closed and not fixed; it recurs and looks handled | the routing ladder, and the `recurs` edge that makes the mis-route visible |
| **Oscillation** | a rule added, later removed as noisy, later re-learned and re-added; every step defensible alone, and invisible in a flat list because the queue is emptied between each step | the archive graph, the `reverses` edge, and a checker that exits non-zero on a reversal-of-a-reversal |

## What gets installed

`scripts/seed_lessons.py` writes all of it. Six artefacts, plus a test suite that proves the
machinery fires.

| Artefact | Default path | Role |
|---|---|---|
| the queue | `docs/lessons.md` | short-lived working list; **empty is the healthy state** |
| the graph | `docs/LESSONS-ARCHIVE.md` | one dated section per drain, newest first; the loop's entire memory |
| the hook | `.claude/hooks/session_start_lessons.py` | injects applied rules + queue depth into every session |
| the checker | `scripts/lessons_graph.py` | oscillation, recurrence, dangling edges; exits 1 |
| capture skill | `.claude/skills/lessons/` | writes one entry and stops |
| drain skill | `.claude/skills/implement-ll/` | groups, routes, applies, verifies, archives |

The installer detects the host's conventions (`doc/` vs `docs/`, `bin/` vs `scripts/`, an existing
`tests/`) and retargets every path inside the scripts, the skills and the prose. Names adapt; the
roles must stay distinct.

## Running it

```bash
SEED=<skill-dir>/scripts/seed_lessons.py

python3 "$SEED" --dry-run              # print the plan and the wiring candidates, write nothing
python3 "$SEED" --seed                 # install, with a short worked example in each file
python3 "$SEED" --seed-from-session    # install with an empty queue, then YOU populate it
python3 "$SEED" --upgrade              # refresh the machinery, preserve the ledger
```

Useful overrides: `--root PATH`, `--docs-dir`, `--scripts-dir`, `--tests-dir`.

**Exit 2 means an installation is already there and nothing was written.** Report that to the user
and offer `--upgrade`, which backs up each code file to `.bak` and never touches the queue or the
archive. Do not work around it by deleting files first: a half-migrated loop that silently drops
the archive is the worst possible outcome of this feature.

The installer ends by *running* the checker against a deliberately broken fixture, triggering the
hook and printing what it injects, and running the loop's test suite. Read that output — a hook is
code, and a green test suite is not a working binary. Pass it along to the user.

## `--seed-from-session` — the high-value form

The loop arrives already carrying evidence, which is what makes the first drain worth running
rather than theoretical. After the installer finishes, re-read the current session's transcript
and write one queue entry per mistake **that was actually caught in it**.

What counts:

- a documented check that turned out to be prose rather than code;
- a claim made from intuition that a measurement falsified;
- a recommendation that contradicted text already settled in the repo;
- a defect found by running the software rather than by its tests;
- a bug that survived more than one fix attempt;
- something that only worked after a non-obvious discovery.

What does not: a typo, a one-off misreading with no general shape, a decision that was correctly
argued and went the other way. **A queue padded with those is a queue nobody drains.**

Each entry needs `What happened` (the specific fact, with `path:line` or a quotation, *and how it
was caught* — frequently the real finding), `Generalises to` (one sentence, as a rule someone
could follow — this field is the filter), and `Candidate home` (a suggestion, explicitly not a
decision).

**Do not implement any of them.** Routing happens at the drain, where entries can be grouped;
implementing one in isolation is the reliable way to land it in the wrong artefact.

## Wiring it into the host project

This is the step that is easiest to skip and most expensive to skip.

**The two skills must be called from checkpoints that already fire, never left as things to
remember — that is the failure the whole design exists to prevent.** The installer prints the
candidates it found: instructions files, docs indexes, and any existing definition-of-done or
checklist wording.

1. Find the project's **"definition of done"** and add the requirement that the queue is current
   before work closes. A task is not finished while a lesson from it is uncaptured.
2. Find its **"decision is settled"** moment (a phase close, a release, a PR merge) and add the
   drain there.
3. **Amend an existing checkpoint; do not invent a second ceremony beside one that already
   exists.** In a project with no checkpoints at all, create exactly one: a line in CLAUDE.md's
   contribution section.
4. **Register the two documents wherever the project indexes its docs**, so they are discoverable
   by someone who never read this.

## The edge vocabulary is closed

Six edges, spelled exactly: `refines`, `supersedes`, `moves`, `recurs`, `reverses`, `caused-by`.

Distinguishing `moves` / `recurs` / `reverses` is the crux — collapsing them into "we changed our
mind" is what makes oscillation undetectable. The archive template documents each one and why it
earns its own name; do not edit that table down.

Two rules that appear to contradict each other are almost always **one conditional rule whose
condition nobody wrote down.** Find the condition and record one `refines`/`supersedes` row naming
it. Never resolve a contradiction by picking a winner.

## The routing ladder

Ordered by the cost of being forgotten. **Reach for the top and only fall through when the moment
genuinely cannot be detected.**

hook → test/CI check → an existing skill → CLAUDE.md → a reference document → decline.

- A test/CI check must be **added to the canonical CI task in the same commit** — a check not in
  the gate never runs. Prefer a ratchet with its waiver constant pinned empty, so a waiver is a
  visible act in a diff.
- **Amend a skill rather than create one.** A new skill nobody invokes is worse than another
  sentence in one that is already invoked.
- **CLAUDE.md is the most expensive destination, not the default.** Every line competes for
  attention with every other line.
- **Decline is a real outcome** and the recorded reason is the whole value — it stops the same
  proposal arriving next cycle.

If a drain finishes and the only things that changed are markdown files, the weak version got
built.

## Adaptation

- **Non-Python projects** — the checker can be any language; only the three findings matter. The
  bundled one has no dependencies and reads one file, so there is rarely a reason to rewrite it.
- **No hook mechanism** — inject via whatever file is loaded unconditionally at session start, and
  say plainly in the report that this is a weaker substitute that will decay.
- **Monorepos** — one queue per team boundary, one shared archive. Recurrence across teams is the
  most valuable signal the graph produces.
- **An existing retro process** — wire into it rather than replacing it. The queue is the artefact
  that matters; the ceremony around it can be whatever already exists.

## Acceptance — do not report success without these

- [ ] A fresh session, with nothing said by the user, begins with the archive's rules in context.
- [ ] A seeded oscillation and a 2× recurrence both make the checker exit non-zero and print the
      full chain. **Shown, not asserted.**
- [ ] The SessionStart hook does not report the archive's own format example as data.
- [ ] The queue file is empty immediately after a drain.
- [ ] Both skills' descriptions trigger on symptoms, not on the phrase "lessons learned".
- [ ] Deleting the archive breaks nothing: the hook degrades silently, the checker reports cleanly.

The bundled `tests/test_lessons_loop.py` covers all six against the retargeted install; the
installer runs it. If you adapted anything by hand, run it again afterwards.
