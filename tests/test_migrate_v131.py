"""Migration tests: a project seeded by the real v1.3.1 installer, upgraded by the current one.

The v1.3.1 project is produced by running the v1.3.1 installer itself (tests/fixtures/v1_3_1, a
byte-for-byte snapshot of commit 588a75d).

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import unittest

from test_migrate_v12 import MigrationBase, S

HERE = Path(__file__).resolve().parent
V131_INSTALLER = HERE / "fixtures" / "v1_3_1" / "scripts" / "seed_lessons.py"


class SnapshotIsGenuine(unittest.TestCase):
    def test_the_v131_fixture_is_the_v131_release_not_an_approximation(self):
        for rel in ("scripts/seed_lessons.py",
                    "assets/lessons-loop/hooks/lesson_detect.py",
                    "assets/lessons-loop/hooks/session_start_lessons.py",
                    "assets/lessons-loop/tests/test_lessons_loop.py"):
            proc = subprocess.run(["git", "show", "588a75d:plugins/skill-improver/skills/skill-improver/" + rel],
                                  cwd=HERE, capture_output=True)
            if proc.returncode != 0:
                self.skipTest("commit 588a75d is not in this clone")
            self.assertEqual((HERE / "fixtures/v1_3_1" / rel).read_bytes(), proc.stdout, rel)


class UpgradeFromV131(MigrationBase):
    installer = V131_INSTALLER

    def test_pristine_v131_has_nothing_the_upgrade_would_keep(self):
        self.seed_old("--seed")
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("KEPT AS YOU LEFT THEM", out)
        self.assertNotIn("held at its previous version", out)

    def test_pristine_v131_with_jev_upgrades_and_keeps_its_provider(self):
        self.seed_old("--seed", "--jev-provider", "openrouter")
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("KEPT AS YOU LEFT THEM", out)
        self.assertNotIn("held at its previous version", out)
        self.assertEqual(S.jev_state(self.layout()), ("enabled", "openrouter"))

    def test_upgrade_preserves_the_ledger_byte_for_byte(self):
        self.make_old_project("--seed")
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
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
