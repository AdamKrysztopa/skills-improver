"""Tests for the corpus labeller's pure helpers (the interactive loop is not exercised).

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

_path = Path(__file__).resolve().parent.parent / "bench" / "detector" / "label.py"
_spec = importlib.util.spec_from_file_location("bench_label", _path)
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)

W1 = [{"k": "fail", "key": "Bash:pytest", "err": "boom"}]
W2 = [{"k": "prompt", "text": "no, again"}]
G = "0123456789ab"


class LabelHelperTests(unittest.TestCase):
    def test_id_is_a_stable_key_order_independent_hash(self):
        a = [{"k": "fail", "key": "x"}]
        b = [{"key": "x", "k": "fail"}]
        self.assertEqual(L.record_id(a), L.record_id(b))
        expected = hashlib.sha1(json.dumps(a, sort_keys=True).encode()).hexdigest()[:12]
        self.assertEqual(L.record_id(a), expected)

    def test_split_follows_group_parity(self):
        self.assertEqual(L.split_for("000000000001"), "test")
        self.assertEqual(L.split_for("00000000000a"), "dev")
        self.assertEqual({L.split_for(L.record_id([{"n": i}])) for i in range(40)}, {"dev", "test"})

    def test_overlapping_windows_from_one_session_share_a_split(self):
        events = [{"k": "fail", "key": "Bash:pytest", "err": "boom %d" % i} for i in range(16)]
        raw = [{"t": i, "g": "00000000000a", "trigger": "fail", "window": events[i:i + 8]} for i in range(9)]
        raw += [{"t": i, "g": "000000000001", "trigger": "fail", "window": events[i + 1:i + 9]} for i in range(3)]
        out = L.merge_captures(raw, [])
        self.assertEqual(len(out), 9)
        self.assertEqual({r["split"] for r in out}, {"dev"})
        self.assertEqual({r["group"] for r in out}, {"00000000000a"})

    def test_a_capture_without_a_session_group_is_refused(self):
        with self.assertRaises(ValueError):
            L.merge_captures([{"t": 1, "trigger": "fail", "window": W1}], [])

    def test_merge_dedupes_identical_windows_and_ignores_capture_time(self):
        raw = [{"t": 1, "g": G, "trigger": "fail", "window": W1}, {"t": 2, "g": G, "trigger": "fail", "window": W1},
               {"t": 3, "g": G, "trigger": "prompt", "window": W2}]
        out = L.merge_captures(raw, [])
        self.assertEqual(len(out), 2)
        self.assertEqual(set(out[0]), {"id", "group", "trigger", "window", "label", "labeler", "split"})
        self.assertEqual((out[0]["label"], out[0]["labeler"]), (None, None))
        self.assertEqual(out[0]["id"], L.record_id(W1))

    def test_merge_keeps_existing_labels_and_adds_only_new_windows(self):
        existing = L.merge_captures([{"t": 1, "g": G, "trigger": "fail", "window": W1}], [])
        existing[0]["label"], existing[0]["labeler"] = True, "A"
        out = L.merge_captures([{"t": 2, "g": G, "trigger": "fail", "window": W1},
                                {"t": 3, "g": G, "trigger": "prompt", "window": W2}], existing)
        self.assertEqual([r["label"] for r in out], [True, None])
        self.assertEqual(out[0]["labeler"], "A")

    def test_relabel_pool_is_seeded_labelled_only_and_skips_answered(self):
        recs = [{"id": "%012x" % i, "label": i % 3 == 0, "window": [], "trigger": "fail"} for i in range(30)]
        recs.append({"id": "f" * 12, "label": None, "window": [], "trigger": "fail"})
        pool = L.relabel_pool(recs, [], 10)
        self.assertEqual(len(pool), 10)
        self.assertNotIn("f" * 12, {r["id"] for r in pool})
        self.assertEqual([r["id"] for r in pool], [r["id"] for r in L.relabel_pool(recs, [], 10)])
        rest = L.relabel_pool(recs, [{"id": pool[0]["id"]}], 10)
        self.assertEqual([r["id"] for r in rest], [r["id"] for r in pool[1:]])

    def test_jsonl_round_trip_is_atomic_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "c.jsonl"
            L.write_jsonl(path, [{"a": 1}, {"b": "é"}])
            self.assertEqual(L.read_jsonl(path), [{"a": 1}, {"b": "é"}])
            self.assertEqual([p.name for p in path.parent.iterdir()], ["c.jsonl"])


if __name__ == "__main__":
    unittest.main()
