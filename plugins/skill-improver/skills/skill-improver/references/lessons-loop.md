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
| the checker | `scripts/lessons_graph.py` | oscillation and recurrence over the edges Claude declared, plus dangling edges; exits 1 |
| capture skill | `.claude/skills/lessons/` | writes one entry and stops |
| drain skill | `.claude/skills/implement-ll/` | groups, routes, applies, verifies, archives |

The hook restates only the rules that still need the model's judgment. A rule whose home is a safeguard that exists and is known to run — a Claude Code hook registered in `.claude/settings*.json`, an executable git hook, an installed pre-commit config — is enforced without anyone remembering it, so it is listed by id with a pointer to its archive row instead of being repeated. Rules homed in prose, in several files, in a path that only resembles a gate (`src/webhooks/retry.py`, `docs/hooks.rst`), in a test that may never run, a CI workflow that may filter out the change, a Makefile or task runner someone must invoke, or in a safeguard that is missing or unregistered, are still injected in full.

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
python3 "$SEED" --upgrade --jev-provider openrouter   # optional: Jev-assisted detection
```

Useful overrides: `--root PATH`, `--docs-dir`, `--scripts-dir`, `--tests-dir`.

**Exit 2 means an installation is already there and nothing was written.** Report that to the user
and offer `--upgrade`, which backs up each code file to `.bak` and never touches the queue or the
archive. Do not work around it by deleting files first: a half-migrated loop that silently drops
the archive is the worst possible outcome of this feature.

### Upgrading a project seeded by an older version

A project seeded by v1.2 and then upgraded at the plugin level still has the v1.2 machinery and no
Jev. `--dry-run` reports `EXISTING LOOP DETECTED`, how many generated files are stale (it compares
each against what this plugin would write — the artefacts are the version record, nothing extra is
stored) and what Jev is doing. Then `--upgrade [--jev-provider ...]`.

- **Preserved:** `lessons.md` and `LESSONS-ARCHIVE.md` (never opened for writing), the existing
  SessionStart registration (even a hand-edited command), every other hook, permission and setting.
- **Layout is read back from the installed hook**, not re-guessed from the directories the project
  has grown since; an install whose hook points somewhere the installer cannot reproduce stops with
  `--docs-dir` guidance and writes nothing.
- **A loop without the generated hook keeps its own ledger.** The installer locates it by its
  archive: the one `lessons-archive.md` (any case) at the root or under `docs/`, `doc/` or
  `documentation/`. A queue alone does not count, so a stale `docs/lessons.md` cannot pull a new
  archive beside it. No archive (and no queue in the default docs directory), or more than one,
  stops with exit 1 and `--docs-dir` guidance: a second, empty ledger is never created. The
  ledger's file names are kept as the filesystem spells them.
- **A project SessionStart hook that injects the ledger is kept, not doubled.** The installer runs
  each registered SessionStart script that mentions the ledger, and it counts only if what it
  injects names the archive's path or cites a rule the archive holds — a comment, a queue counter
  or an archive validator does not. The generated hook is then neither installed nor registered.
- **Refreshed:** only files that differ. A second run writes nothing. A `.bak` is never overwritten —
  a later upgrade adds `.bak.1`, so a hand-edited hook stays recoverable. A Python file that differs
  from a shipped version only in formatting (same syntax tree and comments) counts as that version,
  so a project formatter does not freeze it.
- **The suite tests only what the plugin installed.** The checker, the hook or a skill kept as the
  project's own is listed in the suite's `PROJECT_OWNED`, and its checks are skipped and say so, so an
  edited hook no longer holds the suite at an older version. With both the checker and the hook the
  project's own, the suite is not installed. Importing the suite runs nothing; a project's pytest
  collects it as `test_lessons_loop`.
- **All or nothing:** files are written through a journal; a write error, or a failure of the
  upgraded machinery's own checks, restores every file and prints `rolled back` with the cause.
  Findings the checker reports in the project's real archive are shown (capped) and never fail it.
- **Jev is a separate, explicit answer.** No flag leaves it exactly as found (`enabled (provider)`,
  `installed but not registered`, or `not enabled`); only `--jev-provider` changes it, and it never
  switches provider on its own. "Never chosen" and "chosen Off" leave identical artefacts and are
  treated identically — nothing acts on the difference.

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

## Jev-assisted lesson detection (optional)

The loop only works if someone notices a mistake is worth capturing. This optional hook watches a
compact window of recent events and asks Jev (TypeSafe's decision model, which returns
probabilities, not text) one question: does this look like a lesson? **Jev detects; Claude writes.**
A high score injects a short nudge to run the `lessons` skill; the entry, queue, drain, routing,
archive and checker are unchanged. It changes *when* capture is suggested, nothing else.

- **Enable / disable:** `--jev-provider openrouter | typesafe | off` (with `--seed`,
  `--seed-from-session` or `--upgrade`). Off removes the hooks; nothing is sent anywhere.
- **Consent lives in `.claude/settings.local.json`** (personal): three hook registrations for
  `.claude/hooks/lesson_detect.py`. The installer adds the file to this clone's `.git/info/exclude`,
  writes no backup of it (it may hold a key), and refuses to register into a copy git tracks. The
  script is committed and inert, so no commit can turn external calls on for a teammate, and
  `--upgrade` never enables it by itself.
- **Credential, never in config:** `OPENROUTER_API_KEY` or `TYPESAFE_API_KEY`, from the process
  environment (shell profile, or an `env` block in a Claude Code settings file) or a project `.env`
  (git-ignore it; the installer warns if it isn't). The installer reports whether the key was found
  and makes one connectivity call; a missing or bad key never fails the install.
- **What it sends:** bounded, redacted event snippets, never the transcript or file contents: at
  most the last 8 events, truncated, secret-shaped values redacted, paths relative. Redaction is
  best-effort regex, not DLP. This is an external inference call. Per-session state
  lives in the OS temp dir, not the repo.
- **Failure:** the hook always exits 0. No key, timeouts, 429s, malformed replies: silent no-op
  (three transient failures in a row pause calls for 30 minutes). A key that is present but out of
  credit or rejected pauses detection for the session and warns once per session with the
  fix and how to turn it off. Off never warns.
- **Volume control:** one nudge per distinct problem, 10 minutes apart, 3 per session, 30 Jev calls
  per session. `WORTHY_MIN` and the other constants sit at the top of the hook; they were set on a
  synthetic replay, so recalibrate against your own sessions.

### Measuring whether Claude acts on a nudge

Off by default. Set `SKILL_IMPROVER_JEV_EVAL` to a file (absolute, outside the repo, or relative to
the project and git-ignored) before starting Claude Code and the hook appends one JSON line per Jev
call, nudge and queue write: counts, scores and the `###` title of a written entry — never a
prompt, command, error text or key. It changes nothing the session or the state files can observe.

```bash
python3 <skill-dir>/scripts/jev_eval.py "$SKILL_IMPROVER_JEV_EVAL" --queue docs/lessons.md
```

reports calls, positives, nudges, nudges **followed** (an entry written to the queue after the
nudge, same session) vs **ignored**, entries Claude wrote on its own, and whether the followed
entries are still queued or drained. A skill invocation that ends in "routine, no entry" counts as
ignored, which is the right reading. The accepted/declined split at drain is not recoverable from
the archive, which does not link a row to its entry; the drain report carries it.

`tests/dogfood_nudge.py` measures the same thing with real `claude -p` sessions and a fixed nudge,
without Jev. Measured at v1.3.1 (sonnet, 3-9 runs per cell; indicative, not statistical): with the
user saying the mistake is a repeat, no nudge → `lessons` used 2/6; v1.3.0's imperative wording →
9/10; the factual wording → 9/9; a routine typo → 0/3 under both; a plain fix request with no
mistake in sight → 0/6 under all three. The nudge lifts capture on a real lesson without making
Claude capture non-lessons. The wording was changed because Claude Code's hook documentation says
text framed as a system command can trip prompt-injection defences; the data did not show the old
wording failing. Not measured: the PostToolUseFailure path end to end.

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
- **Monorepos** — one queue per team boundary, one shared archive. Recurrence across teams, once
  declared as a `recurs` edge, is the most valuable signal the graph produces.
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
