"""Label captured event windows by hand, blind to every detector's output.

    python3 label.py capture1.jsonl capture2.jsonl --labeler A
    python3 label.py --relabel-sample 50 --labeler B

Answers: y = a lesson is worth capturing here, n = not, s = skip for now, q = quit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CORPUS = HERE / "corpus" / "corpus.jsonl"
ANSWERS = {"y": True, "n": False}


def window_key(window: list) -> str:
    return json.dumps(window, sort_keys=True)


def record_id(window: list) -> str:
    return hashlib.sha1(window_key(window).encode("utf-8")).hexdigest()[:12]


def split_for(group: str) -> str:
    """By capture group, never by window: a session's overlapping windows must not straddle dev and test."""
    return "test" if int(group, 16) % 2 else "dev"


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def merge_captures(raw_rows: list[dict], existing: list[dict]) -> list[dict]:
    """Existing records first, untouched; then each previously unseen window once, unlabelled.

    Raises:
        ValueError: A capture line has no session group `g` (captured before v1.4.0).
    """
    out = list(existing)
    seen = {window_key(r["window"]) for r in out}
    for row in raw_rows:
        if not row.get("g"):
            raise ValueError("a capture line has no session group \"g\"; recapture with the current hook")
        key = window_key(row["window"])
        if key in seen:
            continue
        seen.add(key)
        rid = record_id(row["window"])
        out.append({"id": rid, "group": row["g"], "trigger": row["trigger"], "window": row["window"],
                    "label": None, "labeler": None, "split": split_for(row["g"])})
    return out


def relabel_pool(records: list[dict], second: list[dict], size: int, seed: int = 0) -> list[dict]:
    """A seeded sample of already-labelled records, so a second labeler sees the same ones every run."""
    labelled = sorted((r for r in records if r["label"] is not None), key=lambda r: r["id"])
    sample = random.Random(seed).sample(labelled, min(size, len(labelled)))
    answered = {r["id"] for r in second}
    return [r for r in sample if r["id"] not in answered]


def show(record: dict) -> None:
    print("\n" + "-" * 72)
    print("trigger: %s   id: %s" % (record["trigger"], record["id"]))
    for event in record["window"]:
        print("  " + json.dumps(event, ensure_ascii=False))


def ask_label(record: dict, ask=input) -> str:
    show(record)
    while True:
        answer = ask("lesson-worthy? [y/n/s/q] ").strip().lower()
        if answer in ("y", "n", "s", "q"):
            return answer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("captures", nargs="*", type=Path, help="raw capture JSONL file(s)")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--labeler", required=True)
    parser.add_argument("--relabel-sample", type=int, metavar="N",
                        help="write a second label set for N already-labelled records")
    args = parser.parse_args(argv)

    if args.relabel_sample:
        records = read_jsonl(args.corpus)
        target = args.corpus.with_name("labels_%s.jsonl" % args.labeler)
        second = read_jsonl(target) if target.exists() else []
        queue = relabel_pool(records, second, args.relabel_sample)

        def commit(record: dict, value: bool) -> None:
            second.append({"id": record["id"], "label": value, "labeler": args.labeler})
            write_jsonl(target, second)
    else:
        raw = [row for path in args.captures for row in read_jsonl(path)]
        records = merge_captures(raw, read_jsonl(args.corpus) if args.corpus.exists() else [])
        write_jsonl(args.corpus, records)
        queue = [r for r in records if r["label"] is None]
        target = args.corpus

        def commit(record: dict, value: bool) -> None:
            record["label"], record["labeler"] = value, args.labeler
            write_jsonl(args.corpus, records)

    print("%d to label -> %s" % (len(queue), target))
    for record in queue:
        answer = ask_label(record)
        if answer == "q":
            break
        if answer in ANSWERS:
            commit(record, ANSWERS[answer])
    return 0


if __name__ == "__main__":
    sys.exit(main())
