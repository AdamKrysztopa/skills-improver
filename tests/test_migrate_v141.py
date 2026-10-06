"""Migration tests: a project seeded by the real v1.4.1 installer, upgraded by the current one.

The v1.4.1 project is produced by running the v1.4.1 installer itself (tests/fixtures/v1_4_1, a
byte-for-byte snapshot of commit 634a5c6).

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import unittest

from test_migrate_v12 import LOOP_TEST, MigrationBase

HERE = Path(__file__).resolve().parent
V141_INSTALLER = HERE / "fixtures" / "v1_4_1" / "scripts" / "seed_lessons.py"
HOOK = ".claude/hooks/session_start_lessons.py"


class SnapshotIsGenuine(unittest.TestCase):
    def test_the_v141_fixture_is_the_v141_release_not_an_approximation(self):
        for rel in ("scripts/seed_lessons.py",
                    "assets/lessons-loop/hooks/lesson_detect.py",
                    "assets/lessons-loop/hooks/session_start_lessons.py",
                    "assets/lessons-loop/tests/test_lessons_loop.py"):
            proc = subprocess.run(["git", "show", "634a5c6:plugins/skill-improver/skills/skill-improver/" + rel],
                                  cwd=HERE, capture_output=True)
            if proc.returncode != 0:
                self.skipTest("commit 634a5c6 is not in this clone")
            self.assertEqual((HERE / "fixtures/v1_4_1" / rel).read_bytes(), proc.stdout, rel)


class UpgradeFromV141(MigrationBase):
    installer = V141_INSTALLER

    def test_pristine_v141_has_nothing_the_upgrade_would_keep(self):
        self.seed_old("--seed")
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("KEPT AS YOU LEFT THEM", out)
        self.assertNotIn("held at its previous version", out)

    def test_pristine_v141_with_jev_upgrades_and_keeps_nothing(self):
        self.seed_old("--seed", "--jev-provider", "openrouter")
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("KEPT AS YOU LEFT THEM", out)
        self.assertNotIn("held at its previous version", out)

    def test_upgrade_replaces_the_suite_that_read_its_layout_off_the_checker(self):
        self.seed_old("--seed")
        suite = self.root / LOOP_TEST
        self.assertIn("_lg.ARCHIVE_REL", suite.read_text())
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("_lg.ARCHIVE_REL", suite.read_text())

    def test_upgrade_preserves_the_ledger_byte_for_byte(self):
        self.make_old_project("--seed")
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assert_ledger_intact()

    def test_an_edited_v141_hook_is_kept_and_the_suite_skips_its_checks(self):
        self.make_old_project("--seed")
        hook, loop_test = self.root / HOOK, self.root / LOOP_TEST
        hook.write_text(hook.read_text() + "\n# MY LOCAL RULE\n")
        edited = hook.read_bytes()
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertIn("KEPT AS YOU LEFT THEM", out)
        self.assertIn("skipped as this project's own: hook", out)
        self.assertEqual(hook.read_bytes(), edited)
        self.assertIn('PROJECT_OWNED = "hook"', loop_test.read_text())
        self.assert_ledger_intact()

    def test_upgraded_machinery_is_identical_to_a_fresh_install(self):
        self.seed_old("--seed")
        self.run_installer("--upgrade")
        self.assert_machinery_matches_a_fresh_install()

    def test_upgraded_machinery_with_jev_is_identical_to_a_fresh_install(self):
        self.seed_old("--seed", "--jev-provider", "openrouter")
        self.run_installer("--upgrade")
        self.assert_machinery_matches_a_fresh_install("--jev-provider", "openrouter")


if __name__ == "__main__":
    unittest.main()
