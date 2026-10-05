"""Offline tests for the detector benchmark runner: heuristic only, synthetic corpus, no network.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

_path = Path(__file__).resolve().parent.parent / "bench" / "detector" / "run.py"
_spec = importlib.util.spec_from_file_location("bench_run", _path)
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

REPEAT = [{"k": "fail", "key": "Bash:pytest", "err": "Exit code 1\nAssertionError: 3 != 4"},
          {"k": "fail", "key": "Bash:pytest", "err": "Exit code 1\nAssertionError: 5 != 6"}]
CORRECTED = [{"k": "prompt", "text": "no, that is wrong again, use alembic"}]
ONE_FAIL = [{"k": "fail", "key": "Bash:ls", "err": "Exit code 1\nno such file"}]
BENIGN = [{"k": "prompt", "text": "please add a docstring to parse()"}]
DISTINCT = [{"k": "fail", "key": "Bash:a", "err": "Exit code 1\nboom"},
            {"k": "fail", "key": "Bash:b", "err": "Exit code 1\nsomething else"}]

# dev: r1 TP, r3 FP, r5 TN    test: r2 TP, r4 FN, r6 TN
CORPUS = [
    ("r1", "dev", True, REPEAT), ("r3", "dev", False, CORRECTED), ("r5", "dev", False, BENIGN),
    ("r2", "test", True, CORRECTED), ("r4", "test", True, ONE_FAIL), ("r6", "test", False, DISTINCT),
]


def record(rid, split, label, window):
    return {"id": rid, "trigger": window[-1]["k"], "window": window, "label": label,
            "labeler": "A", "split": split}


class RunTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.corpus = self.tmp / "corpus.jsonl"
        self.write(self.corpus, [record(*c) for c in CORPUS])
        self.out = self.tmp / "out"

    @staticmethod
    def write(path, rows):
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def run_main(self, *extra):
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code = R.main(["--corpus", str(self.corpus), "--detectors", "heuristic",
                           "--out", str(self.out), *extra])
        self.assertEqual(code, 0)
        return json.loads((self.out / "summary.json").read_text()), buf.getvalue()

    def test_heuristic_counts_per_split(self):
        summary, printed = self.run_main()
        dev, test = summary["detectors"]["heuristic"]["dev"], summary["detectors"]["heuristic"]["test"]
        keys = ("n", "tp", "fp", "fn", "tn")
        self.assertEqual({k: dev[k] for k in keys}, dict(n=3, tp=1, fp=1, fn=0, tn=1))
        self.assertEqual({k: test[k] for k in keys}, dict(n=3, tp=1, fp=0, fn=1, tn=1))
        self.assertEqual((dev["precision"], dev["recall"]), (0.5, 1.0))
        self.assertAlmostEqual(dev["f1"], 2 / 3)
        self.assertEqual((test["precision"], test["recall"]), (1.0, 0.5))
        self.assertAlmostEqual(test["f1"], 2 / 3)
        self.assertEqual(dev["false_nudges_per_100"], 50.0)
        self.assertEqual(test["false_nudges_per_100"], 0.0)
        self.assertEqual((dev["errors"], dev["mean_bytes_out"]), (0, 0))
        self.assertIn("heuristic", printed)

    def test_raw_rows_and_provenance(self):
        summary, _ = self.run_main()
        rows = [json.loads(line) for line in (self.out / "heuristic.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 6)
        self.assertEqual(set(rows[0]), {"id", "split", "label", "decision", "score", "latency_ms", "bytes_out", "error"})
        self.assertEqual({r["id"]: r["decision"] for r in rows},
                         {"r1": True, "r2": True, "r3": True, "r4": False, "r5": False, "r6": False})
        self.assertIn("UTC", summary["date_utc"])
        self.assertEqual(summary["models"]["claude_haiku"], "claude-haiku-4-5")
        self.assertEqual(summary["n_labelled"], 6)

    def test_unlabelled_records_are_not_scored(self):
        self.write(self.corpus, [record(*c) for c in CORPUS] + [record("r7", "dev", None, REPEAT)])
        summary, _ = self.run_main()
        self.assertEqual(summary["n_labelled"], 6)

    def test_kappa_is_reported_when_a_second_label_set_is_given(self):
        second_labels = {"r1": True, "r2": True, "r3": False, "r4": False, "r5": False, "r6": True}
        second = self.tmp / "labels_B.jsonl"
        self.write(second, [{"id": i, "label": v, "labeler": "B"} for i, v in second_labels.items()])
        summary, printed = self.run_main("--second-labels", str(second))
        self.assertEqual(summary["kappa"]["n"], 6)
        self.assertAlmostEqual(summary["kappa"]["kappa"], 1 / 3)
        self.assertFalse(summary["kappa"]["meets_threshold"])
        self.assertIn("revisit the labels", printed)

    def test_openrouter_model_is_required_and_never_defaulted(self):
        with contextlib.redirect_stderr(io.StringIO()), mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "x"}):
            with self.assertRaises(SystemExit):
                R.main(["--corpus", str(self.corpus), "--detectors", "openrouter_llm", "--out", str(self.out)])
        self.assertFalse((self.out / "summary.json").exists())

    def test_missing_provider_key_and_unknown_detector_fail_before_any_call(self):
        with contextlib.redirect_stderr(io.StringIO()), mock.patch.dict(os.environ, {}, clear=True):
            for detectors in ("jev", "claude_haiku", "nonsense"):
                with self.assertRaises(SystemExit):
                    R.main(["--corpus", str(self.corpus), "--detectors", detectors, "--out", str(self.out)])

    def test_a_failing_detector_counts_as_a_miss_and_is_reported_separately(self):
        def boom(rec):
            raise KeyError("x")

        rows = R.score_records(boom, [record(*c) for c in CORPUS])
        self.assertTrue(all(r["decision"] is False and r["error"] == "KeyError" for r in rows))
        s = R.summarise(rows)
        self.assertEqual((s["tp"], s["fn"], s["errors"], s["latency_p50_ms"]), (0, 3, 6, None))

    def test_jev_threshold_selection_and_rescoring(self):
        def row(label, score):
            return {"label": label, "score": score, "decision": score is not None and score >= 0.6,
                    "error": None if score is not None else "transient", "latency_ms": 1.0, "bytes_out": 1}

        dev = [row(True, 0.9), row(True, 0.5), row(False, 0.4), row(False, 0.1), row(True, None)]
        self.assertEqual(R.best_threshold(dev), 0.5)
        self.assertEqual(R.summarise(dev, 0.5)["tp"], 2)
        self.assertEqual(R.summarise(dev, 0.6)["tp"], 1)
        self.assertEqual(R.summarise(dev, 0.6)["fn"], 2)
        self.assertIsNone(R.best_threshold([row(True, None)]))


if __name__ == "__main__":
    unittest.main()
