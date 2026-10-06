"""A failed fresh seed leaves nothing behind; an unwired install is reported as unfinished."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent / "plugins" / "skill-improver" / "skills" / "skill-improver"
_spec = importlib.util.spec_from_file_location("seed_lessons", SKILL / "scripts" / "seed_lessons.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


def tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None for p in sorted(root.rglob("*"))
            if "__pycache__" not in p.relative_to(root).parts}


class Transaction(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        (self.root / "README.md").write_text("host project\n")

    def main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            return S.main(["--root", str(self.root), *args]), out.getvalue()

    def test_fresh_seed_that_fails_verification_is_rolled_back(self):
        before = tree(self.root)
        with mock.patch.object(S, "verify", return_value=["a forced failure"]):
            rc, out = self.main("--seed")
        self.assertEqual(rc, 1)
        self.assertIn("rolled back", out)
        self.assertEqual(tree(self.root), before)

    def test_unparseable_settings_exit_3_and_say_not_wired(self):
        settings = self.root / ".claude/settings.json"
        settings.parent.mkdir()
        settings.write_text("{ not json")
        rc, out = self.main("--seed")
        self.assertEqual(rc, 3)
        self.assertIn("NOT WIRED", out)
        self.assertEqual(settings.read_text(), "{ not json")

    def test_hand_registered_hook_counts_as_wired(self):
        settings = self.root / ".claude/settings.json"
        settings.parent.mkdir()
        settings.write_text("{ not json")
        self.assertEqual(self.main("--seed")[0], 3)
        settings.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [
            {"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/session_start_lessons.py"'}]}]}}))
        rc, out = self.main("--upgrade")
        self.assertEqual(rc, 0, out)

    def test_a_wired_fresh_seed_still_exits_0(self):
        rc, out = self.main("--seed")
        self.assertEqual(rc, 0, out)
        self.assertTrue(S.registered(S.detect_layout(mock.Mock(
            root=str(self.root), docs_dir=None, scripts_dir=None, tests_dir=None))))


if __name__ == "__main__":
    unittest.main()
