from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parent / "dogfood_nudge.py"
spec = importlib.util.spec_from_file_location("dogfood_nudge", PATH)
dogfood = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dogfood)


def runs(invoked: int, n: int, written: int = 0) -> list:
    return [{"invoked_skill": i < invoked, "queue_entry_written": i < written} for i in range(n)]


class SummaryLine(unittest.TestCase):
    def test_prints_counts_and_wilson_interval(self):
        line = dogfood.summary_line("current", "subtle", runs(5, 10, 0))
        self.assertIn("invoked `lessons`: 5/10 [0.24, 0.76]", line)
        self.assertIn("queue entry written: 0/10 [0.00, 0.28]", line)

    def test_only_recurring_is_marked_confounded(self):
        suffix = "(confounded: prompt states it is a repeat)"
        self.assertTrue(dogfood.summary_line("current", "recurring", runs(3, 3)).endswith(suffix))
        self.assertNotIn("confounded", dogfood.summary_line("current", "subtle", runs(3, 3)))
        self.assertNotIn("confounded", dogfood.summary_line("current", "routine", runs(3, 3)))


if __name__ == "__main__":
    unittest.main()
