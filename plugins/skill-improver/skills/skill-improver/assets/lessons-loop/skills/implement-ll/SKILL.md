---
name: implement-ll
description: >-
  Use at a checkpoint where work is being settled — a phase or work item is
  closing, a release is being cut, the lessons queue has entries waiting, or
  someone asks to clear, drain, fold in or act on the accumulated lessons. Also
  use when a rule that already exists in the archive turned out not to prevent a
  defect, and when a queue entry has been sitting through a previous checkpoint.
---

# Drain the lessons queue

Route every open entry to something that binds, archive it with its edges, leave the queue empty.

**Announce:** "Using `implement-ll` to drain `<n>` open lessons."

```
docs/lessons.md (queue) → graph check → group → route → apply → verify → docs/LESSONS-ARCHIVE.md
        ↑                                                                            │
        └──────── appended during work ────── SessionStart injects ───────────────────┘
```

**The question for every entry is not "where should this be written down" but "at what moment
could this have been caught, and what was running at that moment?"**

## Step 1 — Graph check first, before reading the queue

```sh
python3 scripts/lessons_graph.py     # exits 1 on a finding
```

Run this *before* routing anything, not after — its two findings change what you should **do**,
not merely what you should write.

**OSCILLATION** (a `reverses` of a `reverses`) is a stop, not an entry. You do not have a lesson;
you have an unsettled decision wearing a lesson's clothes. Take the whole chain to whatever this
project uses for deliberate decisions and settle it — usually by naming the condition under which
both sides are correct. A third rule continues the loop. Reversed entries are never deleted: the
chain is the argument.

**RECURRENCE at 2+** means MOVE IT. The rule was right; it was applied and did not bite, so it is
in the wrong artefact. Record a `moves` edge and say in the report which home failed. Restating it
in the same artefact guarantees a third occurrence.

Then read **the archive's existing entries for this drain's subject matter**. Half of what a queue
proposes has been proposed before, and the archive is the only place that says so.

## Step 2 — Read the whole queue, then group

Read every open entry before routing any of them.

Entries are written one at a time by someone who could not see the next four. Several usually
collapse into one rule — and **the grouped version routes differently from any of its members**,
most often upward: four prose sentences become one hook.

## Step 3 — Route each group

The ladder, ordered by the cost of being forgotten. **Reach for the top and only fall through when
the moment genuinely cannot be detected.**

| Home | Binds because | Use when |
|---|---|---|
| **A hook** | fires whether anyone remembers or not | the moment is mechanically detectable — this is the default, not the exception |
| **A test / CI check** | cannot be skipped, fails loudly | it is a property of the whole tree rather than of one edit |
| **An existing skill** | loaded at the moment that workflow runs | it is judgement at a known moment — **amend, do not create** |
| **CLAUDE.md** | loaded once, at the start | nothing above can hold it — the most expensive destination |
| **A reference document** | looked up deliberately | it is a design fact or a work item wearing a lesson's clothes |
| **Decline** | records that the question was asked and answered | it is not a rule — record the reason |

Notes that decide the hard cases:

- **A test/CI check must be added to the canonical CI task in the same commit.** A check that is
  not in the gate never runs. Prefer a ratchet with its waiver constant pinned empty, so adding a
  waiver is a visible act in a diff.
- **A new skill nobody invokes is worse than another sentence in one that is already invoked.**
  Amend an existing skill unless there is genuinely no owner for the moment.
- **CLAUDE.md is not the default.** Every line there competes for attention with every other line;
  a CLAUDE.md that grows every cycle is one that stops being read.
- **Decline is a real outcome and must stay available.** The recorded reason is the whole value —
  it is what stops the same proposal arriving next cycle.

If you finish a drain and the only things that changed are markdown files, you built the weak
version.

## Two traps

**A rule in the wrong place looks applied and is not.** It will recur, and it will look like it
was handled. When torn between a hook and a sentence, take the hook.

**Do not implement a finding as a rule.** Some entries carry a concrete defect *and* a
generalisation. The defect becomes a work item; only the generalisation becomes a rule. Fixing the
instance and closing the lesson leaves the class open.

Also: **check for contradictions you are creating.** An edit that contradicts a sentence already in
the target file leaves the file arguing with itself, and the older sentence usually wins because it
reads as settled. Search the target for the belief you are overturning and fix it in the same pass.

## Step 4 — Apply, then verify each change binds

Real edits, not descriptions of edits. Then:

- **A new assertion or check: make it fail on purpose, once.** An assertion that has never fired is
  indistinguishable from one that checks nothing. Fire it, read the message, then restore.
- **A hook: trigger it and read what it prints.** A hook is code, and a green test suite is not a
  working binary.
- **A changed default:** run something that previously showed the old behaviour.
- **Prose:** re-read it at the point of use and confirm it says the thing where it is needed.

Run **the project's full gate, in the foreground**, before archiving.

## Step 5 — Archive and clear

Move **every** entry from the queue to `docs/LESSONS-ARCHIVE.md`, newest drain section first:

```markdown
## <today> — drain <N>

| id | rule | home | commit | edges |
|------|------|------|--------|-------|
| L<N>.1 | <one sentence, imperative, readable cold by someone who was not there> | `<path>` | <sha> | moves L2.2 |
```

The rule sentence is what gets injected into every future session — it is the entire memory of the
loop. If it needs the original queue entry to make sense, it is not finished.

Edges are a closed vocabulary: `refines`, `supersedes`, `moves`, `recurs`, `reverses`, `caused-by`.
Two rules that appear to contradict each other are almost always one conditional rule whose
condition nobody wrote down — find the condition and record one `refines`/`supersedes` row naming
it, not a flip.

Then: `docs/lessons.md` ends **empty**. Declined entries are archived with their reason, not left
behind. **Nothing is carried across two drains** — an entry that survives one is an entry nobody
intends to implement.

One commit, naming the lesson ids and what each became. Re-run `python3 scripts/lessons_graph.py`
to confirm the archive still parses and no new oscillation was introduced.

## Step 6 — Report, and answer the loop's fitness check

One table of what landed where. Then say plainly what was escalated and which home failed it, what
was declined and why, and any oscillation surfaced as a decision to settle rather than a rule that
was written.

Then answer this, and record the answer in the drain section:

> **Which of this cycle's defects would a rule already in the archive have caught?**

- *"One, and it was in the queue"* → drain more often.
- *"One, and it was applied"* → the rule is in the wrong artefact. **Re-route it in this same
  drain** with a `moves` edge, rather than logging a new entry about it.
- *"None"* → say so. That is the healthy answer and it is worth being able to see over time.

## When not to use this

- **The queue is empty** — say so and stop. Do not invent lessons to justify a run.
- **Mid-task.** This edits shared config and hooks, and can change behaviour under work in flight.
  Capture during, drain at a checkpoint.
