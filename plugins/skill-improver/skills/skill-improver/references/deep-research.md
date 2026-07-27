# Deep Research Pipeline

The deep pass exists to answer one question before you rewrite a skill: **what
would this skill look like if it were built by someone who knew the current
state of the art?** You get there by grounding the rewrite in real, current
sources instead of the skill's own (possibly stale) assumptions.

Run the four research tracks below — in parallel via subagents if available,
otherwise inline — then synthesize. The output is not a reading list; it's a set
of concrete edits, each traceable to something you found.

## Track A — Web search (domain state of the art)

Use `WebSearch` to find how this skill's problem is best solved *today*.

- Search the skill's domain + "best practices" / "2026" / "state of the art".
- Look for techniques, patterns, or tools the skill predates or ignores.
- Note anything the skill does that is now considered an anti-pattern.

## Track B — Context7 (current library/API docs)

Stale API instructions are one of the top reasons a skill silently fails. If the
skill references any library, framework, SDK, CLI, or cloud service:

- `resolve-library-id` then `query-docs` (the context7 MCP) for each one.
- Verify every API call, flag, config key, and command the skill instructs the
  model to use still exists and behaves as described.
- Prefer this over web search for anything doc-shaped — it's current and precise.
- **If the target skill teaches anything about the skill/plugin format itself**
  (frontmatter fields, packaging, commands, marketplaces), the canonical
  authorities are `agentskills.io/specification`, Anthropic's skills
  best-practices page, and the official validator's rules in
  `anthropics/skills` (`skill-creator/scripts/quick_validate.py`) — check all
  three; docs sometimes lead the validator (e.g. `when_to_use`).
- **If the skill names a Claude model, a `model:` pin, or a price**, the
  authority is the live pricing page (and the `claude-api` skill, if installed)
  — see `references/claude5-context.md` §3. Re-fetch; never write a recalled
  price into someone's skill.

## Track C — Skills marketplace / prior art in skills

Someone may have already solved part of this well.

- Use the `find-skills` skill (or search available skill marketplaces) for skills
  in the same domain.
- Read how the best comparable skills structure their description, their
  progressive disclosure, and their bundled resources. Borrow patterns, not prose.
- If a mature skill already covers part of the target's job better, that's worth
  telling the user — sometimes the improvement is "compose with X" not "rewrite".

## Track D — GitHub (reference implementations)

- Use the GitHub search tools (or `gh`) to find reference implementations,
  popular repos, or issues in the skill's domain.
- Look for canonical code the bundled scripts should resemble, and for known
  pitfalls surfaced in issues.

## Synthesis

Merge the four tracks into the rubric findings from
`references/improvement-rubric.md`. For each proposed edit, keep a one-line
justification tied to a source ("Context7: flag `--foo` was renamed `--bar` in
v3", "web: retrieval-augmented approach now standard for this task"). Those
justifications are what let the user trust a deep rewrite — show them in the
proposal.

## Provenance — mark how each claim was obtained

A deep proposal makes two very different kinds of research claims: ones you
**fetched live** (a URL you opened today, docs you queried, an issue you read)
and ones you **recalled** (plausible, specific-sounding knowledge that was
never verified this run). Users can't tell these apart unless you mark them —
and recalled claims about fast-moving libraries are exactly the ones that rot.

So, in the proposal:

- Every load-bearing finding carries a source **and how it was obtained**:
  "verified live 2026-07-25: <url>" vs "recalled, unverified this run".
- If a research track's tools were unavailable — web search blocked, Context7
  not connected, **subagents whose tool calls were all denied by a hook** (this
  has happened: a misfiring PreToolUse hook silently turned two research
  subagents into training-knowledge oracles) — say so explicitly in the
  proposal, name the affected tracks, and mark every finding that came from
  them as recalled-unverified.
- Never dress recalled knowledge up as a citation. "GitHub issue #715 notes
  `fit_text()` needs the real font file" is only acceptable if you or a tool
  actually opened it; otherwise write "python-pptx autofit is known to be
  unreliable (recalled — verify before relying on)".
- If you discover mid-run that a track fell back to recall, prefer re-running
  that track with working tools over shipping unmarked claims.

Guard against research bloat: the point is a sharper, more correct, still-lean
skill — not a longer one stuffed with everything you read. If research doesn't
change an instruction, it doesn't go in.
