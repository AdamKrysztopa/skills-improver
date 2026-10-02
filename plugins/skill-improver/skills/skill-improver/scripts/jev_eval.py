#!/usr/bin/env python3
"""Read the log Jev-assisted detection writes when SKILL_IMPROVER_JEV_EVAL is set, and report.

    export SKILL_IMPROVER_JEV_EVAL=$HOME/jev-eval.jsonl     # before starting Claude Code
    python3 jev_eval.py $HOME/jev-eval.jsonl --queue docs/lessons.md

Answers: how many Jev calls, how many positive, how many nudges, how many nudges were followed by
a queue entry (the `lessons` skill's output) and how many were ignored, and whether the followed
entries are still waiting or have been drained. Reads one local file; sends nothing anywhere.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def load(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and isinstance(record.get("e"), str):
            records.append(record)
    return records


def queued_titles(queue: Path) -> set[str]:
    """Titles of the entries still in the queue's `## Open` section (fenced examples excluded)."""
    text = queue.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    open_part = re.split(r"^## Open\s*$", text, maxsplit=1, flags=re.M)[-1]
    return {m.strip() for m in re.findall(r"^### (.+)$", open_part, flags=re.M)}


def summarise(records: list[dict], queue: Path | None = None) -> dict:
    """Pair each queue write with the earliest unanswered nudge in its session.

    Args:
        records: Log records in file order.
        queue: The project's queue file, to tell waiting entries from drained ones.

    Returns:
        Counts: calls, positive, negative, errors, nudges, followed, ignored, organic (queue
        writes with no nudge before them), and for followed entries waiting vs drained.
    """
    out = {"calls": 0, "positive": 0, "negative": 0, "errors": 0, "nudges": 0, "followed": 0,
           "ignored": 0, "organic": 0, "followed_titles": []}
    waiting: dict[str, int] = {}
    for r in records:
        session = str(r.get("s"))
        if r["e"] == "call":
            out["calls"] += 1
            outcome = r.get("outcome")
            out[outcome if outcome in ("positive", "negative") else "errors"] += 1
        elif r["e"] == "nudge":
            out["nudges"] += 1
            waiting[session] = waiting.get(session, 0) + 1
        elif r["e"] == "queue_write":
            if waiting.get(session):
                waiting[session] -= 1
                out["followed"] += 1
                out["followed_titles"] += [t for t in r.get("titles", []) if isinstance(t, str)]
            else:
                out["organic"] += 1
    out["ignored"] = out["nudges"] - out["followed"]
    if queue is not None:
        still = queued_titles(queue)
        titles = out["followed_titles"]
        out["followed_entries_waiting"] = sum(t in still for t in titles)
        out["followed_entries_drained"] = sum(t not in still for t in titles)
    return out


def render(summary: dict) -> str:
    rate = f" ({summary['followed'] / summary['nudges']:.0%})" if summary["nudges"] else ""
    lines = [
        f"Jev calls              : {summary['calls']}  (positive {summary['positive']}, negative "
        f"{summary['negative']}, errors {summary['errors']})",
        f"Nudges emitted         : {summary['nudges']}",
        f"  followed by an entry : {summary['followed']}{rate}",
        f"  ignored              : {summary['ignored']}",
        f"Queue writes with no nudge before them (Claude's own captures): {summary['organic']}",
    ]
    if "followed_entries_waiting" in summary:
        lines.append(f"Entries written after a nudge: {summary['followed_entries_waiting']} still in the queue, "
                     f"{summary['followed_entries_drained']} no longer there (drained — accepted or declined; "
                     "the archive does not link a row to its entry, so the split needs the drain report)")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("log", type=Path, help="the file SKILL_IMPROVER_JEV_EVAL pointed at")
    p.add_argument("--queue", type=Path, help="the project's docs/lessons.md")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    if not args.log.is_file():
        print(f"no log at {args.log}: SKILL_IMPROVER_JEV_EVAL was not set, or nothing has run yet", file=sys.stderr)
        return 1
    summary = summarise(load(args.log), args.queue if args.queue and args.queue.is_file() else None)
    print(json.dumps(summary, indent=2) if args.json else render(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
