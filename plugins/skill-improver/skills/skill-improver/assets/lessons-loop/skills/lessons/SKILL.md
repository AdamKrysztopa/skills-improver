---
name: lessons
description: >-
  Use the moment a mistake is caught, while the mechanism is still known — a
  documented check turns out to be prose rather than code, a claim made from
  intuition is falsified by a measurement, a recommendation contradicts text
  already settled in the repo, a defect is found by running the software rather
  than by its tests, a bug survives more than one fix attempt, a check passed
  something it should have caught, or something only worked after a non-obvious
  discovery. Capture only — it does not implement the fix.
---

# Capture a lesson

Write one entry into the queue, now, and stop.

**Announce:** "Using `lessons` to capture this before it's lost."

## Why now and not later

Writing lessons at the end of a session loses them. By then the bug is fixed, the diff looks
clean, and the only trace is a correction nobody can reconstruct into a rule. The lesson has to
be written **when it is paid for** — at the moment of the mistake, while the mechanism is still
known.

## Write the entry

Append to the `## Open` section of `docs/lessons.md`:

```markdown
### <short title>

- **What happened:** <the specific fact, with `path:line` or a quotation — and *how it was
  caught*, which is frequently the real finding>
- **Generalises to:** <one sentence, stated as a rule someone could follow>
- **Candidate home:** <a suggestion, explicitly not a decision>
```

Do not assign an id. Ids are assigned at drain time.

### `Generalises to` is the filter

It must read as a rule someone could follow, in one sentence. If you cannot write it that way,
what you have is an anecdote, and it does not belong in the queue.

> ❌ "The renderer broke on the long title."
> ✅ "Any text that is laid out rather than measured needs a width assertion, because the failure
> is silent until a real string is long enough."

### `Candidate home` is a suggestion, not a decision

You are writing this entry alone, without seeing the next four. The routing decision belongs to
the drain, where several entries are read together and usually collapse into one rule that routes
differently from any of its members. Suggest, then let go.

### `How it was caught` is often the real finding

"Found by running it" and "found by a test" are different lessons about the same defect. The
second is a bug; the first is a gap in the gate.

## What is not a lesson

- A typo.
- A one-off misreading with no general shape.
- A decision that was correctly argued and went the other way.

A queue padded with those is a queue nobody drains. If it does not generalise past the file it
happened in, fix the file and move on.

## Stop here

**This skill writes and stops. It does not apply the lesson.**

Implementing a lesson in isolation, before the rest of the drain's entries exist to be grouped
with it, is the single most reliable way to land it in the wrong artefact — where it will look
applied and will not be. Draining is `implement-ll`'s job, at a checkpoint.

If the fix to the *instance* is urgent, fix the instance. That is a work item, not the lesson;
the lesson is the generalisation, and it still goes in the queue.
