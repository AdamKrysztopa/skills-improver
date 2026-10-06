"""Migration tests: a project seeded by the real v1.4.0 installer, upgraded by the current one.

The v1.4.0 project is produced by running the v1.4.0 installer itself (tests/fixtures/v1_4_0, a
byte-for-byte snapshot of commit c09ea43).

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import unittest

from test_migrate_v12 import LOOP_TEST, MigrationBase

HERE = Path(__file__).resolve().parent
V140_INSTALLER = HERE / "fixtures" / "v1_4_0" / "scripts" / "seed_lessons.py"
HOOK = ".claude/hooks/session_start_lessons.py"


class SnapshotIsGenuine(unittest.TestCase):
    def test_the_v140_fixture_is_the_v140_release_not_an_approximation(self):
        for rel in ("scripts/seed_lessons.py",
                    "assets/lessons-loop/hooks/lesson_detect.py",
                    "assets/lessons-loop/hooks/session_start_lessons.py",
                    "assets/lessons-loop/tests/test_lessons_loop.py"):
            proc = subprocess.run(["git", "show", "c09ea43:plugins/skill-improver/skills/skill-improver/" + rel],
                                  cwd=HERE, capture_output=True)
            if proc.returncode != 0:
                self.skipTest("commit c09ea43 is not in this clone")
            self.assertEqual((HERE / "fixtures/v1_4_0" / rel).read_bytes(), proc.stdout, rel)


class UpgradeFromV140(MigrationBase):
    installer = V140_INSTALLER

    def test_pristine_v140_has_nothing_the_upgrade_would_keep(self):
        self.seed_old("--seed")
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("KEPT AS YOU LEFT THEM", out)
        self.assertNotIn("held at its previous version", out)

    def test_pristine_v140_with_jev_upgrades_and_keeps_nothing(self):
        self.seed_old("--seed", "--jev-provider", "openrouter")
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("KEPT AS YOU LEFT THEM", out)
        self.assertNotIn("held at its previous version", out)

    def test_upgrade_replaces_the_hook_that_hid_test_and_ci_homed_rules(self):
        self.seed_old("--seed")
        hook = self.root / HOOK
        self.assertIn('".github/workflows/"', hook.read_text())
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertNotIn('".github/workflows/"', hook.read_text())

    def test_upgrade_preserves_the_ledger_byte_for_byte(self):
        self.make_old_project("--seed")
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assert_ledger_intact()

    def test_an_edited_v140_hook_is_kept_and_the_suite_skips_its_checks(self):
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
