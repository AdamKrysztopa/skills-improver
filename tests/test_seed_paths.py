"""Install paths: everything the installer writes must resolve inside the project root."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest

SKILL = Path(__file__).resolve().parent.parent / "plugins" / "skill-improver" / "skills" / "skill-improver"
_spec = importlib.util.spec_from_file_location("seed_lessons", SKILL / "scripts" / "seed_lessons.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


class PathContainment(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name).resolve()
        self.root = base / "project"
        self.root.mkdir()
        self.outside = base / "outside"

    def seed(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = S.main(["--root", str(self.root), "--seed", *args])
        return rc, out.getvalue()

    def assertNothingOutside(self):
        self.assertFalse(self.outside.exists(), "installer wrote outside the project")

    def test_parent_relative_docs_dir_is_refused(self):
        rc, out = self.seed("--docs-dir", "../outside")
        self.assertEqual(rc, 1)
        self.assertIn("outside the project", out)
        self.assertNothingOutside()

    def test_absolute_scripts_dir_is_refused(self):
        rc, _ = self.seed("--scripts-dir", str(self.outside))
        self.assertEqual(rc, 1)
        self.assertNothingOutside()

    def test_tests_dir_escaping_after_normalisation_is_refused(self):
        rc, _ = self.seed("--tests-dir", "tests/../../outside")
        self.assertEqual(rc, 1)
        self.assertNothingOutside()

    def test_paths_recovered_from_a_tampered_hook_are_refused_on_upgrade(self):
        self.assertEqual(self.seed()[0], 0)
        hook = self.root / ".claude/hooks/session_start_lessons.py"
        hook.write_text(hook.read_text().replace('SCRIPTS_REL = "scripts"', 'SCRIPTS_REL = "../outside"'))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = S.main(["--root", str(self.root), "--upgrade"])
        self.assertEqual(rc, 1)
        self.assertNothingOutside()

    def test_symlinked_docs_dir_outside_root_is_refused_with_a_way_out(self):
        self.outside.mkdir()
        os.symlink(self.outside, self.root / "docs")
        rc, out = self.seed()
        self.assertEqual(rc, 1)
        self.assertIn("--docs-dir", out)
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_nested_paths_inside_the_project_still_work(self):
        rc, out = self.seed("--docs-dir", "docs/process", "--scripts-dir", "tools/lessons")
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "docs/process/LESSONS-ARCHIVE.md").is_file())


if __name__ == "__main__":
    unittest.main()
