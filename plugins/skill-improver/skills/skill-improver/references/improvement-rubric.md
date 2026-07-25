# Skill Improvement Rubric

Use this to diagnose an existing skill before rewriting it. Work through each
axis and write down *specific* findings (file + line + what's wrong), not a
grade. The goal is a concrete edit list, because "make it better" without
specifics produces mush.

The order matters: triggering and structure are the highest-leverage fixes.
A brilliant skill that never triggers is worth nothing; a skill that dumps 800
lines into context on every trigger taxes every future use.

## 1. Description & triggering (highest leverage)

The `description` frontmatter is the *only* thing that decides whether the skill
runs. Most skills fail by **under-triggering** — they're perfect but never fire.

- Does the description say both *what it does* AND *when to use it*, in concrete
  user language? List the actual phrases/contexts a user would type.
- Does it cover casual/indirect phrasings, not just the formal name? (Users
  rarely say the skill's name.)
- Is it a little "pushy" toward triggering on genuinely-relevant tasks, without
  grabbing near-miss tasks that belong to another tool?
- Red flag: a description that only restates the title. Rewrite it to enumerate
  triggering situations.

## 2. Progressive disclosure & structure

Skills load in layers: metadata always, `SKILL.md` on trigger, resources on
demand. Respect that budget.

- Is `SKILL.md` lean (aim <500 lines)? If it's bloated, what should move to
  `references/`?
- Are large reference files (>~300 lines) given a table of contents and a clear
  "read this when…" pointer from `SKILL.md`?
- For multi-domain skills, is each variant its own reference file so only the
  relevant one loads?
- Is anything in `SKILL.md` that's only needed sometimes? Push it down a layer.

## 3. Prompt quality & the "why"

Modern models reason well when they understand intent, and follow brittle rote
badly.

- Are rules explained with their *reason*, or are they bare `ALWAYS`/`NEVER`
  commands? Reframe imperatives as reasoning the model can generalize from.
- Is the language imperative and direct, or hedged and vague?
- Are output formats defined concretely (template, worked example) where the
  skill promises a specific shape of output?

## 4. Overfitting & dead weight

- Are there instructions that only make sense for one example the author had in
  mind, that would misfire on the general case?
- Is there redundancy — the same instruction stated three times?
- Does every section earn its tokens? Cut what doesn't pull its weight; a
  shorter skill that trusts the model often outperforms a longer one that
  micromanages it.

## 5. Bundled-script opportunities

If the skill describes a deterministic, repetitive procedure in prose (parsing,
formatting, a fixed multi-command sequence), that's a candidate for a bundled
script: written once, run reliably, no re-derivation on every invocation.

- Would any prose procedure be more reliable as a `scripts/` helper the skill
  calls?
- Do existing scripts have clear usage docs and graceful failure, or will they
  break the first time an input is slightly off?

## 6. Correctness & freshness

- Does the skill reference APIs, flags, file paths, or library behavior that may
  have changed? (This is where the **deep pass**'s Context7 + web research earns
  its keep — verify rather than trust the skill's own claims.)
- Do bundled scripts still run? Actually execute them against a realistic input
  if feasible — a skill whose script is silently broken is worse than no skill.

## Output of this step

A short list like:

- `SKILL.md:12` description only restates title → rewrite with 6+ trigger phrases
- `SKILL.md:40-90` 50 lines of API detail → move to `references/api.md` w/ TOC
- `scripts/build.py` no error handling; crashes on empty input → guard + message
- Three `ALWAYS` blocks around formatting → replace with one explained principle

Hand that list into the improvement step.
