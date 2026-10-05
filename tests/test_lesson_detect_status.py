"""`lesson_detect.py --status`: says whether detection is configured, running and succeeding."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

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


class StatusCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.state = self.root / "state"
        self.state.mkdir()

    def run_main(self, *args):
        err, out = io.StringIO(), io.StringIO()
        env = {"CLAUDE_PROJECT_DIR": str(self.root), "OPENROUTER_API_KEY": KEY}
        with mock.patch.object(D.sys, "argv", ["lesson_detect.py", *args]), \
                mock.patch.dict(os.environ, env), \
                mock.patch.object(D, "default_state_dir", return_value=self.state), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            rc = D.main()
        return rc, out.getvalue(), err.getvalue()

    def test_a_malformed_state_file_fails_loudly_not_open(self):
        (self.state / "a.json").write_text(json.dumps({**D.new_state(), "project": str(self.root), "calls": "x"}))
        rc, out, err = self.run_main("--status")
        self.assertEqual(rc, 1)
        self.assertIn("status: internal error (TypeError)", err)
        self.assertNotIn(KEY, out + err)

    def test_an_unknown_argument_is_rejected(self):
        rc, out, err = self.run_main("--status", "--probee")
        self.assertEqual(rc, 1)
        self.assertIn("status: unknown argument --probee", err)
        self.assertEqual(out, "")

    def test_a_clean_run_prints_the_report(self):
        rc, out, _ = self.run_main("--status", "openrouter")
        self.assertEqual(rc, 0)
        self.assertIn("key: found for openrouter", out)


if __name__ == "__main__":
    unittest.main()
