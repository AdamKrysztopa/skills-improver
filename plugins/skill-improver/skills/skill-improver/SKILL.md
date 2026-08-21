---
name: skill-improver
description: >-
  Check installed Claude Code skills and plugins for updates, improve existing
  skills, and install a self-improving lessons loop into a project. Use whenever
  the user wants to "upgrade my skills", check skills or plugins for updates,
  find what's out of date or was removed upstream, audit their installed skills,
  modernize or clean up a dated skill, fix a skill that under-triggers, or make a
  skill SOTA / best-in-class with a deep research pass (web, Context7 docs,
  skills marketplace, GitHub). Also use when a project keeps re-learning the same
  mistake, when someone wants its CLAUDE.md, hooks and skills to get better from
  the mistakes made while working in it, or asks to seed / set up / bootstrap a
  lessons-learned loop, a retro mechanism, or a lessons queue and archive — even
  when they don't say "skill-improver" or name the exact skill.
---

# Skill Improver

This skill does three related things. Figure out which one the user wants from
what they said, then jump to that section. If it's ambiguous, ask. (If the
*user* wants the human-facing guide — how to read reports, apply updates, and
make improvements stick — point them at `references/manual.md`.)

- **"Check for updates" / "upgrade my skills" / "what's out of date?"** →
  go to **Workflow 1: Scan for updates**.
- **"Improve skill X" / "make X better" / "modernize X" / "make X SOTA"** →
  go to **Workflow 2: Improve a skill**.
- **"Seed the lessons loop" / "we keep making the same mistake" / "make this
  project learn from its own errors"** → go to **Workflow 3: Seed the
  lessons-learned loop**.

They compose naturally: a scan often ends with "…and `research` looks dated,
want me to improve it?" — which flows straight into Workflow 2. Workflow 3 aims
one level up: instead of improving one skill by hand, it installs the machinery
by which a project's own tooling improves itself from the mistakes made in it.

These are the user's own installed tools, so nothing is edited blind: locate the
real source of truth first, propose changes, then tell the user how to make the
improvement stick. Steps 1, 4 and 5 of Workflow 2 carry the specifics.

---

## Workflow 1: Scan for updates

Goal: tell the user, at a glance, which installed plugins/skills have a newer
version available at their source, and what to do about it.

### Step 1 — Run the scan script

The update state is scattered across four files on disk (the plugin system's
three, plus `~/.agents/.skill-lock.json` for standalone skills), and diffing
git SHAs by hand is error-prone, so a bundled script does it deterministically:

```bash
python3 <skill-dir>/scripts/scan_updates.py          # human table
python3 <skill-dir>/scripts/scan_updates.py --json    # structured, to reason over
```

By default it `git fetch`es each marketplace clone (or ls-remotes snapshot
marketplaces) and shallow-clones standalone-skill source repos, so it compares
against the **true latest** the source knows about — a local clone is often
stale, which produces both false "update available" and false "up to date"
readings. Only pass `--no-fetch` if the user is offline or explicitly wants a
quick local-only check (say so in the report if you do; standalone skills come
back `unknown` offline because their comparison needs the clone).

The script already knows the subtle cases — a recorded install sha that's stale
relative to a matching version (NOT an update), a version that resolves to the
manifest's pinned sha via upstream tags, plugins whose only identity is their
marketplace repo's HEAD. Read `references/update-detection.md` if the script
errors, a result looks wrong, or you're tempted to second-guess one of those
notes by hand.

### Step 2 — Present the results

Lead with what's actionable. Report, in this order:

1. **Updates available** — plugin/skill, installed → latest, and the source repo.
   Pass along the script's caveat notes (e.g. HEAD-proxy plugins may have
   unchanged content).
2. **Removed upstream** — standalone skills whose folder vanished from their
   source repo. The installer can't update these; the user chooses to keep the
   local copy or delete it. Don't bury this — it's a decision only they can make.
3. **Can't determine** (`?`) — note them briefly with the script's reason,
   don't dwell.
4. **Up to date** — a short reassuring line, not a wall of green. Items marked
   `ok*` are fine; the footnote just explains a stale recorded sha.

> ❌ **Bad:** "3 plugins have updates; everything else looks fine." — the 5
> skills deleted from their source repo vanished from the report.
> ✅ **Good:** "3 plugin updates, and a decision for you: `diagnose`, `to-prd`
> and 3 more were deleted upstream — keep the local copies or remove them?"

### Step 3 — Offer to act

Updating is a native operation, not something this skill does by editing files.
Point the user at the right tool for each kind rather than hand-rolling a
`git pull` into their cache (which the plugin system would clobber anyway):

> Run `/plugin` to update the marketplace plugins, and re-run the skills
> installer for the standalone skills (e.g. `npx skills add <owner/repo>`) —
> then I can re-scan to confirm.

If, after updating, the user wants a skill *improved* rather than just version-
bumped, that's Workflow 2.

---

## Workflow 2: Improve a skill

Goal: make one existing skill meaningfully better, and hand the user changes
they can review and keep. There are two depths — **standard** and **deep** —
and you should confirm which one the user wants (default to standard unless they
say "deep", "SOTA", "best-in-class", "research it", or similar).

### Step 1 — Locate the skill and secure a writable copy

Where the skill lives decides how you may edit it, and the probe is the same
every time — so a bundled script does it:

```bash
python3 <skill-dir>/scripts/resolve_skill.py <name>
```

It prints the skill's real path (following symlinks) and classifies its home:

- **`plugin-cache`** — *never edit in place.* That directory is replaced whole
  on the next plugin update, so any edit there is silently temporary — a trap.
  Copy the skill to a writable workspace first:
  ```bash
  cp -r "<resolved-skill-path>" ~/.claude/skill-improver-workspace/<name>-improved/
  ```
- **`agents-standalone`** — installed via the skills CLI (`npx skills add`),
  which also overwrites on update. Improve a copy; durable homes are an
  upstream PR or a fork.
- **`own-standalone`** — the user's own directory (their git repo, or the
  project behind a symlink). Editing in place is fine; Step 4's confirmation
  still applies.

### Step 2 — Read the whole skill, then diagnose

Read `SKILL.md` **and** every bundled resource (`scripts/`, `references/`,
`assets/`, commands). You can't improve what you haven't read; the weaknesses
are often in the resources, not the front page.

Assess it against `references/improvement-rubric.md` — the concrete checklist
covering description/triggering quality, progressive disclosure, prompt clarity,
overfit/dead-weight instructions, bundled-script opportunities, and freshness
(it pulls in `references/claude5-context.md` for the Claude 5 trim rules and
current model/pricing facts). Come out of this step with a short written list of
*specific* problems, not vibes.

### Step 3 — Improve

**Standard pass** — apply the rubric fixes:

- Rewrite the `description` for reliable triggering (the single highest-leverage
  change — it's what decides whether the skill ever runs).
- Restructure for progressive disclosure: lean `SKILL.md`, details pushed to
  `references/`, repeated procedural work extracted into `scripts/`.
- Replace rigid `ALWAYS`/`NEVER` scaffolding with the *reason* behind the rule,
  so the model applies judgment instead of following brittle rote.
- Cut instructions that don't earn their tokens.

**Deep pass** — everything in standard, *plus* a research phase that grounds the
skill in current reality before you rewrite. This is what turns "cleaned up" into
"state of the art." Follow `references/deep-research.md`, which drives four
sources in parallel: **web search** (current best practices in the skill's
domain), **Context7** (up-to-date docs for any library/API/CLI the skill relies
on — stale API instructions are a top cause of skill failure), the **skills
marketplace / find-skills** (comparable skills to learn from), and **GitHub**
(reference implementations and prior art). Synthesize findings into concrete
edits — don't just append a "further reading" list. Every research claim in the
proposal is marked for provenance (fetched live this run vs recalled from prior
knowledge), and any research track whose tools were unavailable is declared as
such — an unverified claim dressed as a citation is worse than no claim.

### Step 4 — Propose, then confirm

Show the user a clear before/after: a diff, or a tight summary of what changed
and *why* (tie each change back to a rubric finding or a research insight — the
reasoning is what lets them trust it). Then wait for approval before writing
anything.

### Step 5 — Make it stick

After the user approves, explain how the improvement actually persists — this is
easy to get wrong:

- **User's own skill** (own git repo / standalone folder): edit in place; offer
  to commit.
- **Plugin-provided skill**: the improved copy lives in the workspace, not the
  live cache. The durable homes are **upstream** (open a PR to the source repo —
  you know it from the scan) or a **local skill** under `~/.claude/skills/<name>/`
  that shadows the plugin version. Make the user pick one.

---

## Workflow 3: Seed the lessons-learned loop

Goal: install into a project the machinery by which its own tooling — its
CLAUDE.md, its hooks, its skills — gets better from the mistakes made while
working in it, **without anyone having to remember that the machinery exists.**

Read `references/lessons-loop.md` before running this. It carries the reasoning
behind each artefact, and an install that keeps the file names and drops the
reasoning produces something that looks right and decays within a month.

### Step 1 — Confirm the form

Ask which one, unless the user already said:

- **`--seed`** — install with the files empty and a short worked example in each.
- **`--seed-from-session`** — install, then populate the queue from mistakes
  visible in *this* session's transcript. **Recommend this one.** The loop
  arrives already carrying evidence, which is what makes the first drain worth
  running rather than theoretical.
- **`--dry-run`** — print what would be created and where it would wire in,
  changing nothing.

### Step 2 — Run the installer

```bash
python3 <skill-dir>/scripts/seed_lessons.py --dry-run --root <project>
python3 <skill-dir>/scripts/seed_lessons.py --seed-from-session --root <project>
```

It detects the host's conventions (`doc/` vs `docs/`, `bin/` vs `scripts/`, an
existing `tests/`) and retargets every path inside the scripts, skills and prose.

**Exit 2 means a loop is already installed and nothing was written.** Offer
`--upgrade`, which backs up each code file and never touches the queue or the
archive. Don't route around it by deleting files first — a half-migrated loop
that silently drops the archive is the worst outcome this feature can produce.

The installer finishes by running the checker against a deliberately broken
fixture, triggering the hook and printing what it injects, and running the loop's
test suite. **Read that output and pass it on** — a hook is code, and a green
test suite is not a working binary.

### Step 3 — Populate the queue (`--seed-from-session` only)

Re-read this session's transcript and write one queue entry per mistake actually
caught in it — a documented check that was prose rather than code, a claim from
intuition falsified by a measurement, a recommendation contradicting settled
text, a defect found by running the software rather than by its tests.

`Generalises to` is the filter: if it can't be written as a rule someone could
follow, it's an anecdote and doesn't belong. Do **not** implement any of them —
routing happens at the drain, where entries can be grouped.

### Step 4 — Wire it into checkpoints that already fire

The step that's easiest to skip and most expensive to skip. The installer prints
the candidates it found. Add the capture skill to the project's **definition of
done** and the drain skill to its **"decision is settled"** moment, amending an
existing checkpoint rather than inventing a ceremony beside one that exists. In a
project with neither, create exactly one line in CLAUDE.md's contribution
section. Register both documents wherever the project indexes its docs.

Then report against the acceptance list at the end of `references/lessons-loop.md`
— showing the checker's and hook's real output, not asserting it.

---

## Installing & packaging

This skill ships as the `skill-improver` plugin in the
`AdamKrysztopa/skills-improver` marketplace — installable via:

```text
/plugin marketplace add AdamKrysztopa/skills-improver
/plugin install skill-improver@skills-improver
```

That wires up the skill plus the `/skill-improver:upgrade` and
`/skill-improver:improve` command wrappers (thin files at the plugin's
`commands/` root — each just says to load this skill and run one workflow, so
behavior stays in one place).

A standalone install works too (no plugin machinery): symlink this skill into
`~/.claude/skills/skill-improver` and the wrappers into
`~/.claude/commands/skill-improver/` — a subdirectory of `commands/` is what
creates the `/skill-improver:` namespace. Symlinks are officially supported,
so edits in the source repo go live immediately. Uninstall is the reverse:
remove those symlinks, or `/plugin uninstall skill-improver@skills-improver`.

Exact commands for both paths are in the repo `README.md`; the human-facing
guide is `references/manual.md`.
