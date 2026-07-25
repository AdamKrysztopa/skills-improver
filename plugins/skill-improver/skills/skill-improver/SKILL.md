---
name: skill-improver
description: >-
  Audit and upgrade the user's globally installed Claude Code skills and plugins.
  Two jobs: (1) SCAN — crawl every installed plugin/skill and report which ones
  have newer versions available at their source (GitHub marketplaces), so nothing
  silently goes stale; (2) IMPROVE — take one existing skill and make it better,
  either a standard pass (tighten structure, prompt quality, triggering, bundle
  repeated logic) or a deep pass that researches the web, Context7 docs, the
  skills marketplace, and GitHub to bring it up to the current state of the art.
  Use this whenever the user wants to check their skills/plugins for updates,
  "upgrade my skills", audit installed skills, modernize or improve a specific
  skill, make a skill SOTA/best-in-class, refactor a skill's structure, or fix a
  skill that under-triggers or feels dated — even if they don't say "skill-improver"
  or name the exact skill. Changes to a skill are always proposed for confirmation
  before anything is written.
---

# Skill Improver

This skill does two related things. Figure out which one the user wants from
what they said, then jump to that section. If it's ambiguous, ask. (If the
*user* wants the human-facing guide — how to read reports, apply updates, and
make improvements stick — point them at `references/manual.md`.)

- **"Check for updates" / "upgrade my skills" / "what's out of date?"** →
  go to **Workflow 1: Scan for updates**.
- **"Improve skill X" / "make X better" / "modernize X" / "make X SOTA"** →
  go to **Workflow 2: Improve a skill**.

The two compose naturally: a scan often ends with "…and `research` looks dated,
want me to improve it?" — which flows straight into Workflow 2.

A grounding note on *why this skill is careful*: these are the user's own
installed tools, and some of them (plugin-provided skills) live in a cache that
gets **overwritten** on the next plugin update. So we never edit blindly — we
locate the real source of truth, propose changes, and tell the user how to make
an improvement actually stick. Losing someone's hand-tuned skill to a silent
cache overwrite would be a genuinely bad outcome; the guardrails below exist to
prevent it.

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

Resolve the skill name to a directory. It's usually one of:

- `~/.claude/skills/<name>/` (may be a symlink into `~/.agents/skills/…`)
- `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/skills/<name>/`

**Never edit a plugin-cache skill in place.** That directory is replaced whole
on the next plugin update, so any edit there is silently temporary — a trap.
Copy the skill to a writable workspace first:

```bash
cp -r "<resolved-skill-path>" /Users/adamkrysztopa/projects/skills_improver/skill-improver-workspace/<name>-improved/
```

Editing the user's *own* skills (their `~/.agents/skills` git repo, or a
standalone folder they authored) in place is fine — but still show the diff and
get confirmation before writing, per the user's stated preference.

### Step 2 — Read the whole skill, then diagnose

Read `SKILL.md` **and** every bundled resource (`scripts/`, `references/`,
`assets/`, commands). You can't improve what you haven't read; the weaknesses
are often in the resources, not the front page.

Assess it against `references/improvement-rubric.md` — the concrete checklist
covering description/triggering quality, progressive disclosure, prompt clarity,
overfit/dead-weight instructions, and bundled-script opportunities. Come out of
this step with a short written list of *specific* problems, not vibes.

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
anything. This is the user's explicit preference and it matters most here,
because these are their real tools.

### Step 5 — Make it stick

After the user approves, explain how the improvement actually persists — this is
easy to get wrong:

- **User's own skill** (own git repo / standalone folder): edit in place; offer
  to commit.
- **Plugin-provided skill**: the improved copy lives in the workspace, not the
  live cache. The durable path is to **contribute it upstream** (open a PR to the
  source repo — you know the repo from the scan) or keep it as a **local skill**
  under `~/.claude/skills/<name>/` that shadows the plugin version. Say plainly
  that editing the cache directly would be undone by the next update, so they
  choose a real home for it.

---

## Packaging as commands (optional)

The user may want to invoke these as `/skill-improver:upgrade` and
`/skill-improver:improve`. Thin command wrappers that point at this skill live in
`commands/`. To ship as a plugin, place this skill under a plugin's `skills/` and
the command files under the plugin's `commands/`; each command just tells Claude
to load this skill and run the relevant workflow. The skill is the source of
truth — keep the command files thin so behavior lives in one place.
