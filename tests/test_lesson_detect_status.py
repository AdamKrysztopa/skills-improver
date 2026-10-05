"""`lesson_detect.py --status`: says whether detection is configured, running and succeeding."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest

HOOK = (Path(__file__).resolve().parent.parent / "plugins" / "skill-improver" / "skills"
        / "skill-improver" / "assets" / "lessons-loop" / "hooks" / "lesson_detect.py")
_spec = importlib.util.spec_from_file_location("lesson_detect", HOOK)
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)
KEY = "sk-or-v1-" + "cd34" * 16
NOW = time.time()


class Status(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.state = self.root / "state"
        self.state.mkdir()

    def write(self, name, **fields):
        (self.state / f"{name}.json").write_text(json.dumps({**D.new_state(), "project": str(self.root), **fields}))

    def test_no_key_is_a_problem(self):
        rc, text = D.status("openrouter", env={}, project_dir=self.root, state_dir=self.state, now=NOW, probe=False)
        self.assertEqual(rc, 1)
        self.assertIn("no OPENROUTER_API_KEY", text)

    def test_recent_success_is_healthy_and_counts_are_shown(self):
        self.write("a", calls=4, nudges=1, last={"t": int(NOW) - 60, "outcome": "negative"})
        rc, text = D.status("openrouter", env={"OPENROUTER_API_KEY": KEY}, project_dir=self.root,
                            state_dir=self.state, now=NOW, probe=False)
        self.assertEqual(rc, 0, text)
        self.assertIn("4 call(s)", text)
        self.assertIn("1 nudge(s)", text)
        self.assertNotIn(KEY, text)

    def test_blocked_session_is_a_problem(self):
        self.write("a", calls=1, blocked=True, last={"t": int(NOW) - 60, "outcome": "error:credit"})
        rc, text = D.status("openrouter", env={"OPENROUTER_API_KEY": KEY}, project_dir=self.root,
                            state_dir=self.state, now=NOW, probe=False)
        self.assertEqual(rc, 1)
        self.assertIn("error:credit", text)

    def test_other_projects_sessions_are_ignored(self):
        (self.state / "x.json").write_text(json.dumps({**D.new_state(), "project": "/elsewhere", "blocked": True}))
        rc, _ = D.status("openrouter", env={"OPENROUTER_API_KEY": KEY}, project_dir=self.root,
                         state_dir=self.state, now=NOW, probe=False)
        self.assertEqual(rc, 0)

    def test_probe_failure_is_reported(self):
        def boom(*a, **k):
            raise D.JevError("auth")
        rc, text = D.status("openrouter", env={"OPENROUTER_API_KEY": KEY}, project_dir=self.root,
                            state_dir=self.state, now=NOW, probe=True, transport=boom)
        self.assertEqual(rc, 1)
        self.assertIn("probe: auth", text)


if __name__ == "__main__":
    unittest.main()
