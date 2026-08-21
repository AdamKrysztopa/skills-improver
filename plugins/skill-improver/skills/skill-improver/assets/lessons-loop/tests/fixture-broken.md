# Lessons — archive (FIXTURE: deliberately broken)

Not a real archive. This file seeds one oscillation, one 2× recurrence and one typo edge, so the
checker can be shown firing. A checker only ever run against a clean archive has been verified to
print nothing.

## Row format

```markdown
## 2020-01-01 — drain 0

| id | rule | home | commit | edges |
|------|------|------|--------|-------|
| L0.1 | This row is inside a fence and must never be parsed as data. | `CLAUDE.md` | dead000 | reverses L0.2 |
| L0.2 | Neither must this one. | `CLAUDE.md` | dead000 | reverses L0.3 |
```

## Edge vocabulary

| edge | means |
|---|---|
| `reverses` | this table is not under a dated heading and must never be parsed as data |

---

## Applied

## 2026-06-01 — drain 4

| id | rule | home | commit | edges |
|------|------|------|--------|-------|
| L4.1 | Reinstate the trailing-newline rule; removing it broke three diffs. | `CLAUDE.md` | ddd4444 | reverses L3.2 |
| L4.2 | Generated files carry a provenance header. | `scripts/gen.py` | ddd4444 | refines L9.9 |

## 2026-05-01 — drain 3

| id | rule | home | commit | edges |
|------|------|------|--------|-------|
| L3.1 | Every documented check needs a mechanical counterpart or must be deleted. | `CLAUDE.md` | ccc3333 | recurs L1.1 |
| L3.2 | Drop the trailing-newline rule; it fires on correct work. | `CLAUDE.md` | ccc3333 | reverses L1.2 |

## 2026-04-01 — drain 2

| id | rule | home | commit | edges |
|------|------|------|--------|-------|
| L2.1 | A check named in prose is not a check. | `CLAUDE.md` | bbb2222 | recurs L1.1 |
| L2.2 | Fixture data lives beside the test that reads it. | `.claude/hooks/paths.py` | bbb2222 | — |

## 2026-03-01 — drain 1

| id | rule | home | commit | edges |
|------|------|------|--------|-------|
| L1.1 | Checks described in prose must have a mechanical counterpart. | `CLAUDE.md` | aaa1111 | — |
| L1.2 | Every text file ends with a trailing newline. | `CLAUDE.md` | aaa1111 | — |
| L1.3 | declined: proposed a naming convention nobody could state a failure for. | — | aaa1111 | — |
