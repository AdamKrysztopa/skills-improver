#!/usr/bin/env python3
"""Walk docs/LESSONS-ARCHIVE.md and report what a flat reading cannot see.

Three findings, each with a different diagnosis — and none of the diagnoses is
"write another rule":

  OSCILLATION  a reversal of a reversal. Not a lesson; an unsettled decision.
  RECURRENCE   a rule re-learned after it was applied. At 2+: MOVE IT.
  DANGLING     an edge naming an id the archive does not hold.

Plus an informational WEAK-HOME list: rules currently living in prose, which are
the standing recurrence candidates.

No dependencies, reads one file — so there is no excuse not to run it.

Usage:
    python3 scripts/lessons_graph.py            # check, exit 1 on a finding
    python3 scripts/lessons_graph.py --list     # dump parsed entries, always exit 0
    LESSONS_ARCHIVE=fixture.md python3 scripts/lessons_graph.py   # test a fixture
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# --- installer-templated paths (relative to the project root) ---------------
ARCHIVE_REL = "docs/LESSONS-ARCHIVE.md"
QUEUE_REL = "docs/lessons.md"
# ---------------------------------------------------------------------------

EDGES = ("refines", "supersedes", "moves", "recurs", "reverses", "caused-by")

ID_RE = re.compile(r"^L\d+\.\d+$")
DRAIN_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
EDGE_RE = re.compile(r"\b(" + "|".join(EDGES) + r")\s+(L\d+\.\d+)\b")
QUEUE_TITLE_RE = re.compile(r"^###\s+(.+?)\s*$")
EMPTY = {"", "-", "—", "–", "n/a", "none"}


def project_root() -> Path:
    """Locate the project root by looking for the ledger, not by counting `..`.

    The installer adapts to the host project's directory names, so a hardcoded
    depth would silently break on any project that keeps scripts in `bin/`.
    """
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ARCHIVE_REL).exists() or (parent / QUEUE_REL).exists():
            return parent
    return here.parent.parent


def archive_path() -> Path:
    env = os.environ.get("LESSONS_ARCHIVE")
    return Path(env) if env else project_root() / ARCHIVE_REL


def queue_path() -> Path:
    env = os.environ.get("LESSONS_QUEUE")
    return Path(env) if env else project_root() / QUEUE_REL


class Entry:
    __slots__ = ("id", "rule", "home", "commit", "edges", "drain", "declined")

    def __init__(self, id_, rule, home, commit, edges, drain):
        self.id = id_
        self.rule = rule
        self.home = home
        self.commit = commit
        self.edges = edges          # list[(kind, target_id)]
        self.drain = drain
        self.declined = rule.lower().startswith("declined:")

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<Entry {self.id} {self.rule[:40]!r}>"


def _cells(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def _clean(cell: str) -> str:
    cell = cell.strip().strip("`").strip()
    return "" if cell.lower() in EMPTY else cell


def parse_archive(path: Path | None = None) -> list[Entry]:
    """Parse archive rows. Returns [] for a missing or unreadable file.

    Two defences against reading the archive's own documentation as data:
    fenced code blocks are skipped entirely, and a row only counts when it sits
    under a dated `## YYYY-MM-DD` drain heading and its first cell is an id.
    """
    path = path or archive_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    entries: list[Entry] = []
    in_fence = False
    fence_marker = ""
    drain = ""

    for line in text.splitlines():
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence, fence_marker = True, marker
            elif marker == fence_marker:
                in_fence, fence_marker = False, ""
            continue
        if in_fence:
            continue

        heading = DRAIN_RE.match(line)
        if heading:
            drain = heading.group(1)
            continue
        if line.startswith("## "):        # a prose section ends the drain
            drain = ""
            continue
        if not drain or not line.lstrip().startswith("|"):
            continue

        cells = _cells(line)
        if len(cells) < 5 or not ID_RE.match(_clean(cells[0])):
            continue                       # header, separator, or vocabulary table

        edges = EDGE_RE.findall(cells[4])
        entries.append(
            Entry(_clean(cells[0]), cells[1].strip(), _clean(cells[2]),
                  _clean(cells[3]), edges, drain)
        )
    return entries


def parse_queue(path: Path | None = None) -> list[str]:
    """Return open queue entry titles. [] for a missing or unreadable file."""
    path = path or queue_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    titles: list[str] = []
    in_fence = False
    fence_marker = ""
    in_open = False
    for line in text.splitlines():
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence, fence_marker = True, marker
            elif marker == fence_marker:
                in_fence, fence_marker = False, ""
            continue
        if in_fence:
            continue
        if line.startswith("## "):
            in_open = line.strip().lower().startswith("## open")
            continue
        if not in_open:
            continue
        title = QUEUE_TITLE_RE.match(line)
        if title:
            titles.append(title.group(1).strip())
    return titles


# --- home classification ----------------------------------------------------

def home_rank(home: str) -> str:
    """Where on the ladder a rule landed. Used for the standing weakness list."""
    h = home.lower()
    if not h:
        return "none"
    if "hook" in h:
        return "hook"
    if any(k in h for k in ("test", "/ci", "ci/", ".github/workflows", "makefile",
                            "justfile", "noxfile", "tox.ini", "conftest")):
        return "gate"
    if "skill" in h or "/agents/" in h or "/commands/" in h:
        return "skill"
    if h.endswith(".md"):
        return "prose"
    return "code"


# --- findings ---------------------------------------------------------------

def _edges_of(entry: Entry, kind: str) -> list[str]:
    return [t for k, t in entry.edges if k == kind]


def find_oscillations(entries: list[Entry]) -> list[list[str]]:
    """A `reverses` edge pointing at an entry that itself carries `reverses`."""
    by_id = {e.id: e for e in entries}
    chains = []
    for entry in entries:
        for target in _edges_of(entry, "reverses"):
            mid = by_id.get(target)
            if not mid:
                continue
            for tail in _edges_of(mid, "reverses"):
                chain = [entry.id, mid.id, tail]
                # keep walking so the printed chain is the whole argument
                seen = set(chain)
                cursor = by_id.get(tail)
                while cursor:
                    nxt = _edges_of(cursor, "reverses")
                    if not nxt or nxt[0] in seen:
                        break
                    chain.append(nxt[0])
                    seen.add(nxt[0])
                    cursor = by_id.get(nxt[0])
                chains.append(chain)
    return chains


def find_recurrences(entries: list[Entry]) -> list[dict]:
    """Group `recurs` edges by the original rule they keep re-learning."""
    by_id = {e.id: e for e in entries}

    def root_of(entry_id: str) -> str:
        seen = {entry_id}
        cursor = by_id.get(entry_id)
        while cursor:
            up = _edges_of(cursor, "recurs")
            if not up or up[0] in seen:
                break
            entry_id = up[0]
            seen.add(entry_id)
            cursor = by_id.get(entry_id)
        return entry_id

    groups: dict[str, list[str]] = {}
    for entry in entries:
        for target in _edges_of(entry, "recurs"):
            groups.setdefault(root_of(target), []).append(entry.id)

    out = []
    for root, learners in sorted(groups.items()):
        original = by_id.get(root)
        moved = any("moves" in [k for k, t in e.edges if t == root] for e in entries)
        out.append({
            "root": root,
            "learners": sorted(set(learners)),
            "count": len(set(learners)),
            "rule": original.rule if original else "(unknown — id not in archive)",
            "home": original.home if original else "",
            "moved": moved,
        })
    return out


def find_dangling(entries: list[Entry]) -> list[tuple[str, str, str]]:
    ids = {e.id for e in entries}
    return [(e.id, kind, target)
            for e in entries for kind, target in e.edges if target not in ids]


def find_weak_homes(entries: list[Entry]) -> list[Entry]:
    """Applied rules living in prose — the next recurrence candidates."""
    superseded = {t for e in entries for k, t in e.edges
                  if k in ("supersedes", "moves", "reverses")}
    return [e for e in entries
            if not e.declined and e.id not in superseded and home_rank(e.home) == "prose"]


# --- reporting --------------------------------------------------------------

def main(argv: list[str]) -> int:
    path = archive_path()
    entries = parse_archive(path)

    if "--list" in argv:
        for e in entries:
            flag = "declined" if e.declined else home_rank(e.home)
            print(f"{e.id}\t{e.drain}\t{flag}\t{e.home or '—'}\t{e.rule}")
        print(f"({len(entries)} entries from {path})")
        return 0

    if not path.exists():
        print(f"lessons_graph: no archive at {path} — nothing to check.")
        return 0
    if not entries:
        print(f"lessons_graph: {path} holds no entries — clean.")
        return 0

    failed = False

    for chain in find_oscillations(entries):
        failed = True
        print("OSCILLATION  " + " reverses ".join(chain))
        print("  This is a stop, not an entry. You do not have a lesson; you have an")
        print("  unsettled decision wearing a lesson's clothes. Take the whole chain to")
        print("  whatever this project uses for deliberate decisions (a design doc, an ADR,")
        print("  a grilling session) and settle it — usually by naming the condition under")
        print("  which both sides are correct. A third rule continues the loop.")
        print()

    for rec in find_recurrences(entries):
        learners = ", ".join(rec["learners"])
        verdict = "MOVE IT" if rec["count"] >= 2 else "watch"
        if rec["count"] >= 2:
            failed = True
        print(f"RECURRENCE   {rec['root']} re-learned {rec['count']}x (by {learners}): {verdict}")
        print(f"  rule: {rec['rule']}")
        print(f"  home: {rec['home'] or '—'} ({home_rank(rec['home'])})")
        if rec["count"] >= 2:
            print("  A rule that was applied and did not bite is in the wrong artefact.")
            print("  The repair is `moves`, not a second rule saying the same thing louder.")
            if rec["moved"]:
                print("  (a `moves` edge already exists — it did not go far enough up the ladder)")
        print()

    dangling = find_dangling(entries)
    for src, kind, target in dangling:
        failed = True
        print(f"DANGLING     {src} — edge `{kind} {target}` names an id the archive does not hold")
    if dangling:
        print("  Fix the id or add the missing entry; an edge to nowhere breaks every chain")
        print("  that would have run through it, so oscillation goes undetected.")
        print()

    weak = find_weak_homes(entries)
    if weak:
        print(f"WEAK-HOME    {len(weak)} live rule(s) currently held in prose (informational):")
        for e in weak:
            print(f"  {e.id}  {e.home}  — {e.rule}")
        print("  Prose only binds if someone reads it at the moment of the mistake.")
        print("  These are the standing recurrence candidates.")
        print()

    if not failed:
        print(f"lessons_graph: {len(entries)} entries, no oscillation, no recurrence, "
              f"no dangling edges.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
