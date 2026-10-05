"""Score the detectors on the labelled corpus.

    python3 run.py --corpus corpus/corpus.jsonl --detectors heuristic,jev,claude_haiku,openrouter_llm \
        --openrouter-model <id> --out results/2026-11-01

Raw rows go to <out>/<detector>.jsonl, the aggregate to <out>/summary.json.
"""

from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


S = _load("bench_stats", HERE.parent / "stats.py")
DET = _load("bench_detectors", HERE / "detectors.py")

SPLITS = ("dev", "test")
DETECTORS = ("heuristic", "jev", "claude_haiku", "openrouter_llm")
KEY_ENV = {"jev": DET.D.PROVIDERS["openrouter"][2], "claude_haiku": "ANTHROPIC_API_KEY",
           "openrouter_llm": "OPENROUTER_API_KEY"}
SHIPPED_THRESHOLD = DET.D.WORTHY_MIN
KAPPA_MIN = 0.6


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def build_detector(name: str, openrouter_model: str | None):
    if name == "openrouter_llm":
        return functools.partial(DET.openrouter_llm, model=openrouter_model)
    return getattr(DET, name)


def error_kind(exc: Exception) -> str:
    return getattr(exc, "kind", None) or type(exc).__name__


def score_records(detector, records: list[dict]) -> list[dict]:
    """One call per record; a failed call is a miss (decision False) with its error kind recorded."""
    rows = []
    for rec in records:
        row = {"id": rec["id"], "split": rec["split"], "label": rec["label"], "decision": False,
               "score": None, "latency_ms": None, "bytes_out": None, "error": None}
        try:
            row.update(detector(rec))
        except Exception as exc:
            row["error"] = error_kind(exc)
        rows.append(row)
    return rows


def decide(row: dict, threshold: float | None) -> bool:
    if threshold is None:
        return bool(row["decision"])
    return row["score"] is not None and row["score"] >= threshold


def confusion(rows: list[dict], threshold: float | None = None) -> dict:
    tp = fp = fn = tn = 0
    for row in rows:
        decision = decide(row, threshold)
        if row["label"]:
            tp, fn = tp + decision, fn + (not decision)
        else:
            fp, tn = fp + decision, tn + (not decision)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def summarise(rows: list[dict], threshold: float | None = None) -> dict:
    c = confusion(rows, threshold)
    p, r, f1 = S.prf(c["tp"], c["fp"], c["fn"])
    answered = [row for row in rows if row["error"] is None]
    latencies = [row["latency_ms"] for row in answered]
    negatives = c["fp"] + c["tn"]
    return {
        "n": len(rows), **c,
        "precision": p, "recall": r, "f1": f1,
        "precision_ci": S.wilson(c["tp"], c["tp"] + c["fp"]),
        "recall_ci": S.wilson(c["tp"], c["tp"] + c["fn"]),
        "false_nudges_per_100": 100 * c["fp"] / negatives if negatives else None,
        "latency_p50_ms": S.percentile(latencies, 0.5) if latencies else None,
        "latency_p95_ms": S.percentile(latencies, 0.95) if latencies else None,
        "mean_bytes_out": sum(row["bytes_out"] for row in answered) / len(answered) if answered else None,
        "errors": sum(row["error"] is not None for row in rows),
    }


def best_threshold(dev_rows: list[dict]) -> float | None:
    """The score cut-off with the best dev F1; among ties the highest, which nudges least."""
    scores = sorted({row["score"] for row in dev_rows if row["score"] is not None})
    best, best_f1 = None, -1.0
    for threshold in scores:
        f1 = summarise(dev_rows, threshold)["f1"]
        if f1 >= best_f1:
            best, best_f1 = threshold, f1
    return best


def kappa_report(records: list[dict], second_path: Path) -> dict:
    first = {r["id"]: r["label"] for r in records}
    second = {r["id"]: r["label"] for r in read_jsonl(second_path)}
    shared = sorted(set(first) & set(second))
    value = S.cohen_kappa([bool(first[i]) for i in shared], [bool(second[i]) for i in shared])
    return {"n": len(shared), "kappa": value, "meets_threshold": value >= KAPPA_MIN}


def date_utc() -> str:
    return time.strftime("%a %b %d %H:%M:%S UTC %Y", time.gmtime())


def fmt(value, spec: str = ".2f") -> str:
    return "-" if value is None else format(value, spec)


def print_table(detector: str, split: str, s: dict, label: str = "") -> None:
    print("%-15s %-4s %-14s n=%-4d P=%s [%s-%s]  R=%s [%s-%s]  F1=%s  FalseNudge/100=%s  p50=%s p95=%s ms  bytes=%s  err=%d" % (
        detector, split, label, s["n"], fmt(s["precision"]), fmt(s["precision_ci"][0]), fmt(s["precision_ci"][1]),
        fmt(s["recall"]), fmt(s["recall_ci"][0]), fmt(s["recall_ci"][1]), fmt(s["f1"]),
        fmt(s["false_nudges_per_100"], ".1f"), fmt(s["latency_p50_ms"], ".0f"), fmt(s["latency_p95_ms"], ".0f"),
        fmt(s["mean_bytes_out"], ".0f"), s["errors"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, default=HERE / "corpus" / "corpus.jsonl")
    parser.add_argument("--detectors", default="heuristic",
                        help="comma-separated subset of: " + ",".join(DETECTORS))
    parser.add_argument("--openrouter-model", help="required with openrouter_llm; no default is chosen")
    parser.add_argument("--second-labels", type=Path, help="labels_<labeler>.jsonl from label.py --relabel-sample")
    parser.add_argument("--out", type=Path, default=HERE / "results" / time.strftime("%Y-%m-%d", time.gmtime()))
    args = parser.parse_args(argv)

    names = [n.strip() for n in args.detectors.split(",") if n.strip()]
    unknown = [n for n in names if n not in DETECTORS]
    if unknown or not names:
        parser.error("unknown detector(s): %s" % (", ".join(unknown) or "none given"))
    if "openrouter_llm" in names and not args.openrouter_model:
        parser.error("--openrouter-model is required when openrouter_llm is selected")
    missing = sorted({KEY_ENV[n] for n in names if n in KEY_ENV and not os.environ.get(KEY_ENV[n])})
    if missing:
        parser.error("missing environment variable(s): " + ", ".join(missing))

    records = [r for r in read_jsonl(args.corpus) if r["label"] is not None]
    if not records:
        parser.error("no labelled records in %s" % args.corpus)
    args.out.mkdir(parents=True, exist_ok=True)

    summary = {
        "date_utc": date_utc(), "corpus": str(args.corpus), "n_labelled": len(records),
        "models": {"jev": DET.D.PROVIDERS["openrouter"][1], "claude_haiku": DET.HAIKU_MODEL,
                   "openrouter_llm": args.openrouter_model},
        "detectors": {},
    }
    if args.second_labels:
        summary["kappa"] = kappa_report(records, args.second_labels)
        k = summary["kappa"]
        print("Cohen's kappa on %d shared windows: %.3f%s" % (
            k["n"], k["kappa"], "" if k["meets_threshold"] else "  (< %.1f: revisit the labels before publishing)" % KAPPA_MIN))

    for name in names:
        rows = score_records(build_detector(name, args.openrouter_model), records)
        with open(args.out / (name + ".jsonl"), "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        by_split = {split: [r for r in rows if r["split"] == split] for split in SPLITS}
        entry = {split: summarise(by_split[split]) for split in SPLITS}
        for split in SPLITS:
            print_table(name, split, entry[split])
        if name == "jev":
            chosen = best_threshold(by_split["dev"])
            entry["threshold"] = {"shipped": SHIPPED_THRESHOLD, "dev_best": chosen}
            entry["test_at_shipped"] = summarise(by_split["test"], SHIPPED_THRESHOLD)
            print_table(name, "test", entry["test_at_shipped"], "@%.2f shipped" % SHIPPED_THRESHOLD)
            if chosen is not None:
                entry["test_at_dev_best"] = summarise(by_split["test"], chosen)
                print_table(name, "test", entry["test_at_dev_best"], "@%.2f dev-best" % chosen)
        summary["detectors"][name] = entry

    with open(args.out / "summary.json", "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
