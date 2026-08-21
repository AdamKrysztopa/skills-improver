# skill-improver

A Claude Code plugin that keeps your skills and plugins current, makes them
better, and installs the machinery by which a project improves itself.

Three jobs:

1. **Scan** — crawls every globally installed plugin *and* standalone skill
   (`~/.agents/.skill-lock.json`) and reports which have newer versions at
   their source, including skills that were **removed upstream**. No false
   positives from stale installer bookkeeping: recorded shas are verified
   against versions, upstream release tags, and marketplace snapshots before
   anything is flagged.
2. **Improve** — takes one existing skill and improves it: a **standard** pass
   (triggering, structure, prompt quality, dead weight) or a **deep** pass that
   first researches the current state of the art (web search, Context7 docs,
   the skills marketplace, GitHub) and grounds every edit in a cited finding.
   Research claims are marked live-fetched vs recalled, so you can trust the
   proposal. Both passes apply the Claude 5 generation's context rules — trim
   restated rules and stacked emphasis, never a decision — and flag stale model
   names, `model:` pins and hardcoded prices for re-verification.

3. **Seed a lessons loop** — installs into any project the machinery by which
   its own tooling gets better from the mistakes made while working in it,
   without anyone having to remember the machinery exists: a short-lived
   **queue**, a linked **archive** whose rules a SessionStart hook injects into
   every session, a **graph checker** that fails on oscillation (a rule added,
   removed, re-added) and on a rule re-learned after it was applied, and two
   **skills** — one that captures at the moment a mistake is caught and stops,
   one that drains at a checkpoint and routes each lesson to the artefact that
   was actually running when the mistake happened. Paths adapt to the host
   project's conventions. `--seed-from-session` populates the queue from what
   went wrong in the current session, so the first drain is worth running.

Changes are always proposed for your confirmation before anything is written.

## Install

```text
/plugin marketplace add AdamKrysztopa/skills-improver
/plugin install skill-improver@skills-improver
```

Restart Claude Code, then:

- `/skill-improver:upgrade` — scan everything for updates
- `/skill-improver:improve <skill-name>` — improve a skill (say "deep" for the
  research pass)
- `/skill-improver:seed-lessons` — install the lessons loop into this project

Or just ask in plain language: "check my skills for updates", "make my
deck-builder skill best-in-class", "we keep making the same mistake — make this
project learn from it".

## Standalone (no plugin)

```bash
git clone https://github.com/AdamKrysztopa/skills-improver.git
ln -s "$PWD/skills-improver/plugins/skill-improver/skills/skill-improver" ~/.claude/skills/skill-improver
mkdir -p ~/.claude/commands/skill-improver
ln -s "$PWD/skills-improver/plugins/skill-improver/commands/"*.md ~/.claude/commands/skill-improver/
```

## Documentation

- **For humans:** [`plugins/skill-improver/skills/skill-improver/references/manual.md`](plugins/skill-improver/skills/skill-improver/references/manual.md) —
  how to read the scan report, apply updates, and make improvements stick.
- The skill itself: [`plugins/skill-improver/skills/skill-improver/SKILL.md`](plugins/skill-improver/skills/skill-improver/SKILL.md).

## How the scan decides

It reads four sources — `installed_plugins.json`, `known_marketplaces.json`,
each marketplace's `marketplace.json` (git clone or snapshot), and
`~/.agents/.skill-lock.json` — and compares versions first, shas second,
upstream release tags for disambiguation, and file-tree diffs for standalone
skills. Full details:
[`references/update-detection.md`](plugins/skill-improver/skills/skill-improver/references/update-detection.md).
