# Claude 5 generation: the context-engineering lens

Read this when improving any skill, `CLAUDE.md`, agent config, or command file.
It carries two things the rubric can't: **current model facts** (which rot, so
verify them) and **the Claude 5 trim rules** (which changed direction — more
context used to help, now it hurts).

## 1. The flip: less is more

Anthropic removed over 80% of Claude Code's system prompt for the Claude 5
generation. Stronger models do *worse* with over-specified context, not better —
extra words compete with the actual task. The instruction from Anthropic is to
simplify system prompts, Skills, and `CLAUDE.md` files.

Source: <https://claude.com/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models>

What that means when you're holding the red pen:

- **Cut redundancy.** Say each rule once, in one place. Delete restatements.
- **Drop hedging and pep talk.** Not "IMPORTANT", "ALWAYS", "you MUST" stacked
  three deep. State the rule plainly once; strong models follow it.
- **Prefer references over inlining.** Link to the ADR, spec, or doc rather than
  pasting its content into context that loads on every request.
- **Push detail down.** Skills load progressively. `SKILL.md` stays short; long
  examples and edge cases move into `references/` that load only when needed.
- **Keep genuine constraints.** "Less is more" trims verbosity, not decisions.
  Non-negotiables, security boundaries, and hard rules stay. **Remove words, not
  meaning.**

`claude doctor` produces automated simplification suggestions for a project —
worth running, worth reviewing by hand rather than applying blind.

## 2. When the file is mostly decisions

The "removed 80%" figure came from a generic system prompt full of hand-holding.
A governance `CLAUDE.md` where nearly every line is a distinct load-bearing rule
(non-negotiables, standing decisions, CI gates) is a different animal — cutting
it for length deletes governance. The honest ceiling there is removing
redundancy and repeated reinforcement while every rule survives once.

**Expect modest trims on these files, and say so rather than manufacturing
cuts.** A proposal that reports "trimmed 12% by removing three restatements, no
rule lost" is worth more than one that hit a percentage target by deleting
decisions.

Two rule-preserving patterns to look for:

- **A rule stated in two sections.** Keep the fuller, more actionable copy;
  reduce the other to its unique part and point at the canonical one.
- **A repeated analogy or emphasis.** An aside restated in three sections is
  reinforcement, not a new rule. Establish it once; drop the repeats.

Also: don't *add* new always-on content while you're in there (a model-routing
note, a style preamble). That belongs in the relevant skill, not in
every-request context.

## 3. Model facts — verify before quoting

**Claude Opus 5** (`claude-opus-5`, released 2026-07-24) is the current flagship;
Opus 4.8 is the prior generation. Opus 5 is priced identically to Opus 4.8. Fast
mode runs ~2.5x default speed at 2x base price.

Standard API pricing, USD per million tokens, **as verified 2026-07-27**:

| Model | Input | Output |
|---|---|---|
| Opus 5 / Opus 4.8 | $5 | $25 |
| Sonnet 5 (intro, through 2026-08-31) | $2 | $10 |
| Sonnet 5 (from 2026-09-01) | $3 | $15 |
| Sonnet 4.6 | $3 | $15 |
| Haiku 4.5 | $1 | $5 |
| Fable 5 | $10 | $50 |

Multipliers: prompt-cache write 1.25x base input (5-min) or 2x (1-hour), cache
read 0.1x; Batch API 50% off both directions (not combinable with fast mode);
fast mode 2x; web search $10 per 1,000 searches.

**These numbers go stale.** Before putting a price or a "latest model" claim
into a skill, re-verify against
<https://platform.claude.com/docs/en/about-claude/pricing> — or the `claude-api`
skill if the user has it installed, which is the maintained local authority.
Never quote a price from memory into someone's skill.

## 4. Model routing

Price gaps drive routing, not model names. Point cheap tiers at an **alias**
(`model: sonnet`, `model: haiku`, `model: opus`) rather than a pinned old
version, so the config tracks the current best model per tier.

- **Cheap coding / review:** `model: sonnet`. Sonnet 5 is cheaper than Sonnet 4.6
  through 2026-08-31 and equal after, and is the stronger model — there is no
  longer a cost reason to pin Sonnet 4.6.
- **Mechanical, fully-specified work:** `model: haiku` — scaffolding, fixtures,
  enum/model files, fully-specified helpers.
- **Hard reasoning / orchestration:** `model: opus`. Same price as 4.8, so the
  upgrade is free.
- **Escalation** goes up a tier, not sideways: a Haiku task that fails review
  twice moves to Sonnet.

Cost levers that beat model choice: prompt caching for repeated context, the
Batch API for anything not time-sensitive, and simply sending less context.

## 5. What to check during an improve pass

Facts:

- Stale "latest model" claims (Opus 5 is current; Opus 4.8 is prior).
- Hardcoded prices — re-verify, don't trust the table above blindly.
- Any claim that Sonnet 5 costs more than Sonnet 4.6. It does not.

Routing:

- Pinned cheap tiers (`Sonnet 4.6`, `Sonnet 4.5`) → repoint to `model: sonnet`
  unless there's a specific behavioral reason to pin. Document a kept pin.
- Mechanical work on `haiku`, hard work on `opus`.

Context:

- Restated rules deleted, stacked emphasis collapsed, inlined doc content
  replaced with links.
- Long examples moved out of `SKILL.md` into `references/`.
- Decisions-dense file → redundancy removal only; no manufactured cuts, no new
  always-on content.

Verify:

- Re-read and confirm every decision still appears (once). Trim words, keep
  meaning.
- The skill still triggers and runs after the edits.
- Nothing security- or correctness-critical was trimmed.
