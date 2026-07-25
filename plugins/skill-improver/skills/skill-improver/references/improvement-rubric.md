# Skill Improvement Rubric

Use this to diagnose an existing skill before rewriting it. Work through each
axis and write down *specific* findings (file + line + what's wrong), not a
grade. The goal is a concrete edit list, because "make it better" without
specifics produces mush.

The order matters: triggering and structure are the highest-leverage fixes.
A brilliant skill that never triggers is worth nothing; a skill that dumps 800
lines into context on every trigger taxes every future use.

**Axis 0 — should this skill exist at all?** Models improve fast; a skill that
patched a gap in last year's model may now be dead weight the base model
outperforms. If current Claude does the job well with no skill, say so plainly —
retiring (or shrinking to a thin pointer) is a valid improvement, and the
honest one.

A shared vocabulary for naming what you find (borrowed from
`writing-great-skills` — name the failure mode in your findings):
- **sediment** — stale instructions left behind by earlier revisions (axis 6)
- **sprawl** — detail dumped into `SKILL.md` that belongs a layer down (axis 2)
- **no-op** — a sentence that changes no behavior vs the default (axis 4)
- **premature completion** — the skill lets the model declare done before
  verifying its work (axis 3)

## 1. Description & triggering (highest leverage)

The `description` frontmatter is the *only* thing that decides whether the skill
runs. Most skills fail by **under-triggering** — they're perfect but never fire.

- **The SDO rule: the description states ONLY when-to-use — never the workflow,
  guardrails, or a summary of the steps.** Agents follow the description instead
  of reading the skill, so every sentence there that isn't a trigger both wastes
  the listing budget and risks being obeyed out of context. (Observed failure in
  `superpowers/writing-skills`; enforced here.)
- Third person ("Use whenever the user wants…"), with **exact quoted trigger
  phrases** users would actually say, and the key use case **first** — the
  skill listing truncates combined description at ~1,536 chars.
- Does it cover casual/indirect phrasings, not just the formal name? (Users
  rarely say the skill's name.) Is it pushy toward genuinely-relevant tasks
  without grabbing near-misses? For side-effect-heavy skills, consider a "do
  NOT use when…" clause or `disable-model-invocation: true`.
- Red flag: a description that only restates the title, or one longer than
  ~500 chars (the official reviewer heuristic; the hard limit is 1,024).
- **Frontmatter hygiene:** `name` must match `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`,
  ≤64 chars, no "anthropic"/"claude"; description ≤1,024 chars, no angle
  brackets. Allowed keys per the official validator: `name`, `description`,
  `license`, `allowed-tools`, `metadata`, `compatibility` (≤500 chars, env
  requirements). Newer loaders also accept `disable-model-invocation`,
  `user-invocable`, `argument-hint`, `model`, `context: fork` + `agent`, and
  `when_to_use` — but the official validator doesn't accept `when_to_use` yet,
  so keep triggers in `description` for portability.

## 2. Progressive disclosure & structure

Skills load in layers: metadata always, `SKILL.md` on trigger, resources on
demand. Respect that budget — loaded content persists across turns and taxes
every future one.

- Is `SKILL.md` lean (aim <500 lines / ~1,500–2,000 words; push detail out
  beyond ~5,000 words)? If it's bloated, what moves to `references/`?
- **References stay one level deep** — nested reference files get only
  partially read. If a reference needs its own reference, restructure instead.
- **Say "run X" vs "read X" explicitly.** Scripts are executed (only their
  output enters context); references are read for logic. Ambiguity here makes
  the model read 400-line scripts into context.
- **Match rigidity to fragility (degrees of freedom):** fragile, exact
  operations get low-freedom instructions (specific commands/scripts);
  judgment work gets high-freedom text. Rigid prose for creative work — or
  vague prose for fragile work — are both sprawl of a kind.
- Are large reference files (>~300 lines) given a table of contents and a
  clear "read this when…" pointer from `SKILL.md`?
- For multi-domain skills, is each variant its own reference file so only the
  relevant one loads?

## 3. Prompt quality & the "why"

Modern models reason well when they understand intent, and follow brittle rote
badly.

- Are rules explained with their *reason*, or are they bare `ALWAYS`/`NEVER`
  commands? Reframe imperatives as reasoning the model can generalize from.
- Is the language imperative and direct, or hedged and vague?
- Are output formats defined concretely (template, worked example) where the
  skill promises a specific shape of output? **❌BAD/✅GOOD example pairs teach
  better than paragraphs of adjectives.**
- **Premature completion:** does the skill require verification before
  declaring success (compile the scripts, diff the claim, re-read the output) —
  or can the model finish on vibes?

## 4. Overfitting & dead weight

- **The no-op test:** for every instruction, ask "does this sentence change
  behavior versus the base model's default?" If not, delete it — it only
  spends tokens and dilutes the instructions that do matter.
- Are there instructions that only make sense for one example the author had
  in mind (an absolute path on the author's machine is the classic tell),
  that would misfire on the general case?
- Is there redundancy — the same instruction stated three times?

## 5. Bundled-script opportunities

If the skill describes a deterministic, repetitive procedure in prose (parsing,
formatting, a fixed multi-command sequence), that's a candidate for a bundled
script: written once, run reliably, no re-derivation on every invocation.

- Would any prose procedure be more reliable as a `scripts/` helper the skill
  calls?
- Do existing scripts have clear usage docs and graceful failure, or will they
  break the first time an input is slightly off? Scripts must handle their own
  errors and document their constants (no unexplained magic numbers).

## 6. Correctness & freshness

- Does the skill reference APIs, flags, file paths, or library behavior that
  may have changed? (This is where the **deep pass**'s Context7 + web research
  earns its keep — verify rather than trust the skill's own claims.) For
  skill-format claims specifically, the canonical authorities are
  **agentskills.io/specification** and Anthropic's skills best-practices page
  (platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) —
  check both before asserting anything about the format itself.
- Do bundled scripts still run? Actually execute them against a realistic
  input if feasible — a skill whose script is silently broken is worse than no
  skill.
- **Sediment:** anything taught that newer Claude Code versions made native
  (features, flags, workarounds)? Delete or downgrade to a footnote.

## Output of this step

A short list like:

- `SKILL.md:12` description only restates title → rewrite with 6+ trigger phrases
- `SKILL.md:40-90` 50 lines of API detail → move to `references/api.md` w/ TOC
- `scripts/build.py` no error handling; crashes on empty input → guard + message
- Three `ALWAYS` blocks around formatting → replace with one explained principle

Hand that list into the improvement step.
