"""Optional live check against the real provider. Skipped unless explicitly enabled:

    SKILL_IMPROVER_LIVE_JEV_TEST=1 OPENROUTER_API_KEY=... python3 -m unittest discover -s tests -p 'test_live*.py'

Set TYPESAFE_API_KEY as well to cover the direct provider. Costs a fraction of a cent.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import unittest

HOOK = (Path(__file__).resolve().parent.parent / "plugins" / "skill-improver" / "skills"
        / "skill-improver" / "assets" / "lessons-loop" / "hooks" / "lesson_detect.py")
_spec = importlib.util.spec_from_file_location("lesson_detect", HOOK)
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)

LIVE = os.environ.get("SKILL_IMPROVER_LIVE_JEV_TEST") == "1"

REPEATED_FAILURE = [
    {"k": "fail", "key": "Bash:pytest tests/test_dates.py", "err": "AssertionError: datetime(2024,3,10,2,30) != datetime(2024,3,10,3,30)"},
    {"k": "edit", "key": "src/dates.py"},
    {"k": "fail", "key": "Bash:pytest tests/test_dates.py", "err": "AssertionError: datetime(2024,3,10,2,30) != datetime(2024,3,10,3,30)"},
    {"k": "edit", "key": "src/dates.py"},
    {"k": "fail", "key": "Bash:pytest tests/test_dates.py", "err": "AssertionError: datetime(2024,3,10,2,30) != datetime(2024,3,10,3,30)"},
]
ROUTINE_TYPO = [
    {"k": "edit", "key": "src/x.py"},
    {"k": "fail", "key": "Bash:python src/x.py", "err": "SyntaxError: invalid syntax (x.py, line 14) missing colon"},
]


@unittest.skipUnless(LIVE, "set SKILL_IMPROVER_LIVE_JEV_TEST=1 to call the real provider")
class LiveJevTests(unittest.TestCase):
    def score(self, provider, window):
        key = os.environ.get(D.PROVIDERS[provider][2])
        if not key:
            self.skipTest("no %s" % D.PROVIDERS[provider][2])
        body = D.build_body(D.PROVIDERS[provider][1], window, "fail")
        return D.call_jev(provider, key, body, timeout=10)

    def check(self, provider):
        worthy = self.score(provider, REPEATED_FAILURE)
        routine = self.score(provider, ROUTINE_TYPO)
        self.assertTrue(0 <= worthy <= 1 and 0 <= routine <= 1)
        self.assertGreater(worthy, routine)

    def test_openrouter(self):
        self.check("openrouter")

    def test_typesafe_direct(self):
        self.check("typesafe")


if __name__ == "__main__":
    unittest.main()
