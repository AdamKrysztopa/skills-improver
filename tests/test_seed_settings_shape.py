"""Valid JSON of an unexpected shape must produce a diagnostic and leave the file byte-identical."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

SKILL = Path(__file__).resolve().parent.parent / "plugins" / "skill-improver" / "skills" / "skill-improver"
_spec = importlib.util.spec_from_file_location("seed_lessons", SKILL / "scripts" / "seed_lessons.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)

ODD_SHAPES = {
    "hooks is a list": {"hooks": []},
    "SessionStart is an object": {"hooks": {"SessionStart": {}}},
    "group is a string": {"hooks": {"SessionStart": ["python3 x.py"]}},
    "group.hooks is a string": {"hooks": {"SessionStart": [{"hooks": "python3 x.py"}]}},
    "top level is a list": [],
}


class SettingsShape(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def test_odd_shapes_are_reported_and_left_untouched(self):
        for name, settings in ODD_SHAPES.items():
            with self.subTest(name):
                path = self.root / ".claude/settings.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(settings))
                before = path.read_bytes()
                lay = S.Layout(self.root, "docs", "scripts", ".claude/hooks", ".claude/skills", "tests/lessons_loop")
                verdict, merged = S.settings_action(lay)
                self.assertTrue(verdict.startswith("UNPARSEABLE"), verdict)
                self.assertEqual(merged, {})
                self.assertEqual(path.read_bytes(), before)

    def test_local_settings_with_list_hooks_are_not_silently_replaced(self):
        path = self.root / ".claude/settings.local.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"hooks": [{"note": "mine"}]}))
        lay = S.Layout(self.root, "docs", "scripts", ".claude/hooks", ".claude/skills", "tests/lessons_loop")
        verdict, merged = S.jev_settings_action(lay, "openrouter")
        self.assertTrue(verdict.startswith("UNPARSEABLE"), verdict)
        self.assertEqual(merged, {})


if __name__ == "__main__":
    unittest.main()
