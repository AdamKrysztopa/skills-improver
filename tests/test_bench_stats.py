"""Tests for the detector benchmark's statistics helpers.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

_path = Path(__file__).resolve().parent.parent / "bench" / "stats.py"
_spec = importlib.util.spec_from_file_location("bench_stats", _path)
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


class StatsTests(unittest.TestCase):
    def test_prf(self):
        self.assertEqual(S.prf(8, 2, 2), (0.8, 0.8, 0.8))
        self.assertEqual(S.prf(0, 0, 0), (0.0, 0.0, 0.0))
        self.assertEqual(S.prf(0, 3, 4), (0.0, 0.0, 0.0))

    def test_wilson(self):
        self.assertEqual(S.wilson(0, 10)[0], 0.0)
        lo, hi = S.wilson(5, 10)
        self.assertAlmostEqual(lo, 0.237, places=3)
        self.assertAlmostEqual(hi, 0.763, places=3)
        self.assertEqual(S.wilson(0, 0), (0.0, 1.0))
        self.assertEqual(S.wilson(10, 10)[1], 1.0)

    def test_percentile(self):
        self.assertEqual(S.percentile([1, 2, 3, 4], 0.5), 2.5)
        self.assertEqual(S.percentile([4, 1, 3, 2], 0.0), 1)
        self.assertEqual(S.percentile([4, 1, 3, 2], 1.0), 4)
        self.assertEqual(S.percentile([7], 0.95), 7)

    def test_cohen_kappa(self):
        self.assertEqual(S.cohen_kappa([True, False, True, False], [True, False, True, False]), 1.0)
        self.assertEqual(S.cohen_kappa([True, True, False, False], [True, False, True, False]), 0.0)
        self.assertEqual(S.cohen_kappa([True, False, True, False], [False, True, False, True]), -1.0)
        self.assertAlmostEqual(S.cohen_kappa([True] * 20 + [False] * 5 + [True] * 5 + [False] * 20,
                                             [True] * 20 + [True] * 5 + [False] * 5 + [False] * 20), 0.6)

    def test_cohen_kappa_degenerate_inputs(self):
        self.assertEqual(S.cohen_kappa([], []), 0.0)
        self.assertEqual(S.cohen_kappa([True, True], [True, True]), 1.0)
        with self.assertRaises(ValueError):
            S.cohen_kappa([True], [True, False])


if __name__ == "__main__":
    unittest.main()
