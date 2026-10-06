# Lessons — archive

Where drained queue entries land. **One dated section per drain, newest first.** One row per entry.

This file is the entire memory of the loop: a SessionStart hook injects every applied rule below
into every session, so nobody has to open it. That has a consequence for how you write:

> The one-sentence rule must be readable **cold, months later, by someone who was not there.**
> If it needs the original queue entry to make sense, it is not finished.

Nothing here is ever deleted. Reversed entries especially — the chain is the argument.

## Row format

Each drain is a `## YYYY-MM-DD` section containing one table. Rows are parsed by
`scripts/lessons_graph.py` and by the SessionStart hook, so keep the five columns exact:

```markdown
## 2026-01-31 — drain 4

| id | rule | home | commit | edges |
|------|------|------|--------|-------|
| L4.1 | Every check named in prose must have a mechanical counterpart or be deleted. | `.claude/hooks/check_docs.py` | a1b2c3d | moves L2.2 |
| L4.2 | declined: proposed a naming convention nobody could state a failure for. | — | a1b2c3d | — |
```

- **id** — `L<drain>.<n>`, assigned at drain time.
- **rule** — one sentence, imperative, readable cold. `declined: <reason>` for a declined entry.
- **home** — the exact artefact path it landed in, or `—`.
- **commit** — the commit that carried it.
- **edges** — comma-separated `<edge> <id>` pairs, or `—`.

## Edge vocabulary

Closed. Six edges, spelled exactly.

| edge | means | why it is its own edge |
|---|---|---|
| `refines` | narrows or widens a rule without contradicting it | healthy — the rule was right and imprecise |
| `supersedes` | replaces a rule with a better one, same intent | healthy — the old rule stops being live |
| `moves` | same rule, relocated (usually prose → hook) | the expected repair: a rule that was applied and did not bite was in the wrong artefact, not wrong |
| `recurs` | same defect re-learned, after a rule for it existed | a finding about the rule, not a new rule |
| `reverses` | undoes a rule that fired on correct work | legitimate once; twice in a chain is oscillation |
| `caused-by` | this defect exists because of an earlier rule | rarest and most valuable — a rule that bought a problem |

Distinguishing `moves` / `recurs` / `reverses` is the crux. Collapsing them into "we changed our
mind" is what makes oscillation undetectable.

**Two rules that appear to contradict each other are almost always one conditional rule whose
condition nobody wrote down.** Find the condition and record one `supersedes` or `refines` row
naming it. Do not record a flip.

## The oscillation rule

**A `reverses` edge pointing at an entry that itself carries a `reverses` edge is a stop, not an
entry.** What is being held is an unsettled decision wearing a lesson's clothes. It goes to
whatever this project uses for deliberate decisions — a design doc, an ADR, a grilling session —
with the whole chain as its evidence. Answering an oscillation with a third rule continues it.

`scripts/lessons_graph.py` detects this and exits non-zero.

---

## Applied

<!-- Newest drain first. Append a new `## YYYY-MM-DD — drain N` section above the previous one. -->

_No drains yet._
