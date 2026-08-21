# Lessons — archive (FIXTURE: clean)

A healthy archive: refinements and a move, no reversal-of-a-reversal, no repeated recurrence, no
dangling edge. The checker must exit 0 against this.

## Row format

```markdown
## 2020-01-01 — drain 0

| id | rule | home | commit | edges |
|------|------|------|--------|-------|
| L0.1 | Fenced example row — must never be parsed as data. | `CLAUDE.md` | dead000 | reverses L0.2 |
| L0.2 | Nor this one. | `CLAUDE.md` | dead000 | reverses L0.3 |
```

---

## Applied

## 2026-04-01 — drain 2

| id | rule | home | commit | edges |
|------|------|------|--------|-------|
| L2.1 | Every documented check has a mechanical counterpart or is deleted. | `.claude/hooks/check_docs.py` | bbb2222 | moves L1.1 |
| L2.2 | declined: a naming convention nobody could state a failure for. | — | bbb2222 | — |

## 2026-03-01 — drain 1

| id | rule | home | commit | edges |
|------|------|------|--------|-------|
| L1.1 | Checks described in prose must have a mechanical counterpart. | `CLAUDE.md` | aaa1111 | — |
| L1.2 | Rendered output is measured, never assumed, before it is called correct. | `tests/test_render.py` | aaa1111 | refines L1.1 |
