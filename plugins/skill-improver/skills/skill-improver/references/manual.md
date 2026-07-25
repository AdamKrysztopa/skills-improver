# skill-improver manual

A practical guide for a person. `SKILL.md` is written for Claude; this is for
you — what the skill does, how to run it, and how to read what it tells you.

## What it does

Two jobs:

1. **Scan** — checks every globally installed plugin *and* standalone skill
   against its source and tells you what has updates waiting.
2. **Improve** — takes one skill you own and makes it better: a quick standard
   cleanup, or a deep pass that researches the current state of the art first.

Nothing is ever changed without asking you. Scans are read-only; improvements
are always proposed first and written only after you approve.

## Running it

Just ask in plain language — the skill triggers on phrasing, not commands:

- "check my skills for updates" / "what's out of date?" → **scan**
- "improve my research skill" / "give X a cleanup" → **standard pass**
- "make deck-builder best-in-class" / "really research X" → **deep pass**

If you installed the command wrappers, `/skill-improver:upgrade` and
`/skill-improver:improve` do the same things explicitly.

You can also run the scanner yourself, straight from the terminal:

```bash
python3 ~/.claude/skills/skill-improver/scripts/scan_updates.py          # table
python3 ~/.claude/skills/skill-improver/scripts/scan_updates.py --json   # machine-readable
python3 ~/.claude/skills/skill-improver/scripts/scan_updates.py --no-fetch   # offline
```

Options: `--claude-dir` / `--agents-dir` if your config lives somewhere
unusual. `--no-fetch` compares plugins against local clones only and marks
standalone skills `unknown` (their check needs to clone the source repo).

## Reading the scan report

Two sections — **Plugins (marketplaces)** and **Standalone skills (~/.agents)** —
each row one of:

| Mark | Meaning | What to do |
|---|---|---|
| `UPDATE` | The source has something newer than what you have | Update (see below) |
| `REMOVED` | The skill's folder was deleted from its source repo | Your call: keep the local copy or delete it. The installer can't update what no longer exists |
| `?` | Not enough information to compare (no version/sha on one side, offline, or unreachable source) | Usually safe to ignore; the row says why |
| `ok` | Current | Nothing |
| `ok*` | Current, **but** the recorded install sha disagrees with the source | Nothing — this is a bookkeeping artifact of the installer, the footnote explains it |

Two kinds of rows deserve a second of thought:

- **HEAD-proxy updates** (marked with a note): plugins like `code-review` that
  pin no version of their own are compared against their marketplace repo's
  latest commit. *Any* commit in that repo — even to a different plugin —
  advances it. The flag is real but coarse; the plugin's own files may be
  untouched. Updating is harmless either way.
- **Stale-sha footnotes** (`ok*`): e.g. superpowers showed `6.2.0` installed
  with an older recorded sha. The scanner verifies the version against the
  upstream repo's release tags before believing the sha — if the version
  resolves to the pinned commit, you're current, full stop.

## Applying updates

The skill never updates anything itself — updating is the installer tools' job:

- **Plugins**: run `/plugin` in Claude Code and update from the marketplace.
- **Standalone skills**: re-run the skills installer for that repo, e.g.
  `npx skills add mattpocock/skills`.

Then re-scan to confirm. That's the whole loop.

## The improve workflows

### Standard pass — "give X a cleanup"

A focused revision of one skill: rewrite the description so it actually
triggers (the highest-leverage fix — a skill that never runs can't help you),
tighten structure, push detail into reference files, replace brittle
ALWAYS/NEVER rules with the reasoning behind them, cut dead weight. Minutes,
no external research.

### Deep pass — "make X SOTA" / "really research it"

Everything in the standard pass, plus a research phase across four sources:
web search (current best practices), Context7 (are the libraries the skill
teaches still current?), the skills marketplace (what do the best comparable
skills do?), and GitHub (reference implementations, known pitfalls). Findings
become concrete edits, each with a one-line justification tied to its source.

Every research claim in a deep proposal is marked **how it was obtained** —
fetched live during the run vs recalled from prior knowledge. If a research
tool was unavailable or blocked mid-run, the proposal says so and marks the
affected findings unverified. Treat recalled-unverified claims as leads, not
facts.

### What you get

Both passes deliver the same two things, in a workspace folder
(`skill-improver-workspace/<name>-improved/` or the eval outputs dir):

1. **The improved copy** — a full, self-contained copy of the skill with the
   changes applied. Your live installed skill is never edited in place
   (plugin-cache skills get *overwritten* on plugin updates — editing them
   directly would silently evaporate).
2. **A proposal** — what changed, why, and what was deliberately left alone,
   often with recommended-but-not-applied ideas for you to accept or decline.

Review the diff, and if you approve:

- **Your own skill** (a git repo or folder you authored): copy the changed
  files over, commit. If it's symlinked from `~/.claude/skills/`, it goes live
  immediately.
- **A plugin's skill**: the durable homes are a PR to the source repo, or a
  local shadow copy at `~/.claude/skills/<name>/` that takes precedence over
  the plugin version. The proposal tells you which applies.

## Troubleshooting

- **"No installed_plugins.json under …"** — you're pointing at the wrong
  config dir; pass `--claude-dir`.
- **Everything is `?`** — you're probably offline without `--no-fetch`, or the
  sources are unreachable; the scan degrades to "couldn't check" rather than
  guessing.
- **A plugin you *just* updated still shows UPDATE** — check whether it's a
  HEAD-proxy row (note explains). If not, that's a bug — the scan is
  deterministic, so the same inputs will reproduce it; report it.
- **An improvement didn't persist** — it was probably written into a plugin
  cache. See "What you get" above: improvements need a durable home.
