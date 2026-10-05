# skill-improver

Skills Improver is a Claude Code plugin that turns development mistakes into a
project-local lessons loop, where lessons can be escalated from memory into
enforceable safeguards (tests, hooks, CI), with an optional semantic gate
deciding when Claude should consider capturing one. It also improves skills and
scans for updates.

Three jobs:

1. **Seed a lessons loop** — installs into any project the machinery by which
   its own tooling gets better from the mistakes made while working in it,
   without anyone having to remember the machinery exists: a short-lived
   **queue**, a linked **archive** whose rules a SessionStart hook injects into
   every session, and a **graph checker** over the edges (`recurs`, `reverses`,
   `moves`) Claude records when it drains the queue. Alongside them, two
   **skills** — one that captures at the moment a mistake is caught and stops,
   one that drains at a checkpoint and routes each lesson to the artefact that
   was actually running when the mistake happened. Paths adapt to the host
   project's conventions. `--seed-from-session` populates the queue from what
   went wrong in the current session.
   - SessionStart names rules enforced by a hook, test or CI gate by id instead
     of restating them.
   - Optionally, **Jev-assisted lesson detection** (`--jev-provider`) nudges
     Claude to capture a lesson when a compact window of recent events looks
     lesson-worthy; Jev only detects, Claude still writes the entry. Off by
     default. `python3 .claude/hooks/lesson_detect.py --status --probe` checks
     that it is configured, running and succeeding.
   - The installer refuses paths outside the project.

   See [`references/lessons-loop.md`](plugins/skill-improver/skills/skill-improver/references/lessons-loop.md).
2. **Improve** — takes one existing skill and improves it: a **standard** pass
   (triggering, structure, prompt quality, dead weight) or a **deep** pass that
   first researches the current state of the art (web search, Context7 docs,
   the skills marketplace, GitHub) and grounds every edit in a cited finding.
   Research claims are marked live-fetched vs recalled. Both passes apply the Claude 5 generation's context rules — trim
   restated rules and stacked emphasis, never a decision — and flag stale model
   names, `model:` pins and hardcoded prices for re-verification.
3. **Scan** — crawls every globally installed plugin *and* standalone skill
   (`~/.agents/.skill-lock.json`) and reports which have newer versions at
   their source, including skills that were **removed upstream**. No false
   positives from stale installer bookkeeping: recorded shas are verified
   against versions, upstream release tags, and marketplace snapshots before
   anything is flagged.

Changes are always proposed for your confirmation before anything is written.

## How the loop works

```text
capture → queue → drain → route → archive → SessionStart
```

- **Deterministic:** the queue and archive formats, the graph checker, and the
  SessionStart injection. The checker warns on a single `recurs` edge and fails
  when a rule has been re-learned 2 or more times, when a reversal is itself
  reversed (oscillation), or when an edge names an id the archive does not hold.
- **The detector decides** only *when* to suggest capturing a lesson.
- **Claude decides** what the lesson is, where it belongs, and which edges to
  declare; a re-learned rule moves from prose toward a test, hook or CI gate.

## What it does not do

- It does not discover recurrence semantically: the checker only sees the
  relationships Claude declared. It cannot tell on its own that two lessons are
  the same mistake.
- It does not measure whether a safeguard reduced the failure rate.
- The optional detector sends bounded, redacted event snippets, never the
  transcript or file contents. Redaction is best-effort regex, not DLP.
- It is not a replacement for Claude Code's auto-memory.

## Related work

- Claude Code [auto-memory](https://code.claude.com/docs/en/memory) and
  [prompt hooks](https://code.claude.com/docs/en/hooks) — the built-in
  mechanisms this plugin sits beside; it adds a queue, recurrence edges and a
  path from remembered rule to enforced one.
- [`sh5623/self-improvement`](https://github.com/sh5623/self-improvement) — the
  closest project: it also moves a convention toward the strongest enforcement
  layer.
- [`RasputinKaiser/Self-Improvement-Plugin`](https://github.com/RasputinKaiser/Self-Improvement-Plugin)
  — a broader, more instrumented harness (SIPS).
- [`liza-studio/skillmem`](https://github.com/liza-studio/skillmem) —
  procedural memory with retrieval and provenance.
- [`UniM0cha/self-improving-skills`](https://github.com/UniM0cha/self-improving-skills)
  — distills transcripts into skills.

## Evidence

The detector baseline (Jev against a Claude Haiku prompt-hook judge, a cheap
LLM and a deterministic heuristic) is pending; the protocol is in
[`bench/detector/README.md`](bench/detector/README.md). Raw dogfood runs will
land in [`bench/dogfood/`](bench/dogfood/). No numbers are published yet.

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
