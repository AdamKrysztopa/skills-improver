"""Upgrade tests on mature projects: a loop that has been drained for months, not one just seeded.

Each class reproduces a defect found upgrading a real project from v1.4.1:
  1. a drain-edited checker without the layout constants made the suite crash and roll back;
  2. a ledger in docs/internal/ was not found, so an empty second ledger was planned in docs/;
  3. a project-owned SessionStart lessons hook got a second one registered beside it;
  4. a lowercase lessons-archive.md was matched only because macOS is case-insensitive;
  5. a formatter-reformatted shipped hook was kept as a project edit and never refreshed;
  6. a mature archive's findings flooded the report.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import re
import tokenize
import unittest

from test_migrate_v12 import S, MigrationBase, snapshot

HERE = Path(__file__).resolve().parent
ASSETS = S.ASSETS
CHECKER = "scripts/lessons_graph.py"
HOOK = ".claude/hooks/session_start_lessons.py"
DETECTOR = ".claude/hooks/lesson_detect.py"
SUITE = "tests/lessons_loop/test_lessons_loop.py"
FORMATTED_V131 = HERE / "fixtures" / "formatted" / "lesson_detect.v1.3.1.ruff.py"


def drain_edited(checker: str, archive_rel: str, queue_rel: str) -> str:
    """The checker as a drain leaves it: same API, but the templated layout constants inlined away."""
    text = re.sub(r'^(ARCHIVE_REL|QUEUE_REL) = ".*"\n', "", checker, flags=re.M)
    text = text.replace("ARCHIVE_REL", f'"{archive_rel}"').replace("QUEUE_REL", f'"{queue_rel}"')
    assert "ARCHIVE_REL" not in text
    return text


def mature_archive(roots: int = 30) -> str:
    """An archive whose every early rule was re-learned twice: dozens of real RECURRENCE findings."""
    head = "| id | rule | home | commit | edges |\n|------|------|------|--------|-------|\n"
    drains = []
    for n, (date, edge) in enumerate((("2026-03-01", None), ("2026-04-01", "recurs"), ("2026-05-01", "recurs")), 1):
        rows = "".join(f"| L{n}.{i} | Rule {i} holds{' again' * (n - 1)}. | `CLAUDE.md` | c{n} | "
                       f"{f'{edge} L1.{i}' if edge else '—'} |\n" for i in range(1, roots + 1))
        drains.append(f"## {date} — drain {n}\n\n{head}{rows}")
    return "# Lessons — archive\n\n## Applied\n\n" + "\n".join(reversed(drains))


def reformatted(source: str) -> str:
    """The same program respaced token by token: what a formatter does, and nothing more."""
    out = tokenize.untokenize((t.type, t.string) for t in tokenize.generate_tokens(io.StringIO(source).readline))
    assert out != source
    return out


def session_start_commands(root: Path) -> list[str]:
    settings = json.loads((root / ".claude/settings.json").read_text())
    return [h["command"] for g in settings["hooks"]["SessionStart"] for h in g["hooks"]]


class EditedCheckerWithoutLayoutConstants(MigrationBase):
    """Defect 1 and 6: the drain amended the checker, and the archive has real findings."""

    def setUp(self):
        super().setUp()
        self.seed_fresh(self.root)
        (self.root / "docs/LESSONS-ARCHIVE.md").write_text(mature_archive())
        checker = self.root / CHECKER
        checker.write_text(drain_edited(checker.read_text(), "docs/LESSONS-ARCHIVE.md", "docs/lessons.md"))
        self.checker_bytes = checker.read_bytes()
        self.ledger = {p: (self.root / p).read_bytes() for p in ("docs/lessons.md", "docs/LESSONS-ARCHIVE.md")}

    def assert_one_ledger_one_hook(self):
        self.assertEqual(sorted(os.listdir(self.root / "docs")), ["LESSONS-ARCHIVE.md", "lessons.md"])
        self.assertEqual(len(session_start_commands(self.root)), 1)
        self.assert_ledger_intact()

    def test_upgrade_succeeds_and_the_suite_skips_the_checks_of_the_projects_checker(self):
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("AttributeError", out)
        self.assertIn("skipped as this project's own: checker", out)
        self.assertIn(f"skipped — {CHECKER} is this project's own version", out)
        self.assertEqual((self.root / CHECKER).read_bytes(), self.checker_bytes)
        self.assert_one_ledger_one_hook()

    def test_the_installed_suite_is_told_the_layout_and_never_imports_the_checker(self):
        self.run_installer("--upgrade")
        suite = (self.root / SUITE).read_text()
        self.assertIn('ARCHIVE_IN_PROJECT = "docs/LESSONS-ARCHIVE.md"', suite)
        self.assertIn('PROJECT_OWNED = "checker"', suite)
        self.assertNotIn("_lg.", suite)

    def test_a_suite_missing_from_an_older_loop_is_created_and_passes(self):
        for name in os.listdir(self.root / "tests/lessons_loop"):
            (self.root / "tests/lessons_loop" / name).unlink()
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / SUITE).is_file())
        self.assert_one_ledger_one_hook()

    def test_real_findings_are_capped_and_not_an_install_failure(self):
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        report = out.split("against this project's real archive ---", 1)[1].split("\n---", 1)[0]
        self.assertIn("RECURRENCE", report)
        self.assertIn("[exit 1] — findings in this project's archive are the next drain's work", report)
        self.assertIn(f"for all of them run: python3 {CHECKER}", report)
        self.assertLessEqual(len(report.strip().splitlines()), S.REPORT_LINES + 2)

    def test_a_failing_suite_check_is_named_in_the_rollback(self):
        suite = self.root / SUITE
        text = suite.read_text()
        suite.write_text(text.replace('print(f"\\n{passed} passed', 'check("planted failure", False)\nprint(f"\\n{passed} passed', 1))
        before = snapshot(self.root)
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 1, out)
        cause = out.split("Cause:", 1)[1]
        self.assertIn(f"{SUITE} failed 1 check(s): planted failure", cause)
        self.assertEqual(snapshot(self.root), before)

    def test_a_crashing_suite_is_named_in_the_rollback(self):
        suite = self.root / SUITE
        suite.write_text(suite.read_text().replace("\nHERE = ", '\nraise AttributeError("planted crash")\nHERE = ', 1))
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 1, out)
        self.assertIn(f"{SUITE} crashed before reporting: AttributeError: planted crash", out.split("Cause:", 1)[1])


class UpgradeFromV141WithAnEditedChecker(MigrationBase):
    """Defect 1 on a genuine v1.4.1 install: its suite read ARCHIVE_REL off the checker."""
    installer = HERE / "fixtures" / "v1_4_1" / "scripts" / "seed_lessons.py"

    def test_the_v141_suite_is_replaced_and_the_upgrade_succeeds(self):
        self.make_old_project("--seed")
        checker = self.root / CHECKER
        checker.write_text(drain_edited(checker.read_text(), "docs/LESSONS-ARCHIVE.md", "docs/lessons.md"))
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"upgrade (.bak kept)                {SUITE}", out)
        self.assert_ledger_intact()


class ExistingLoopWithItsOwnHookAndLedger(MigrationBase):
    """Defects 2, 3 and 4: a loop that predates the generated hook, laid out its own way."""

    QUEUE = "docs/internal/lessons.md"
    ARCHIVE = "docs/internal/lessons-archive.md"

    def setUp(self):
        super().setUp()
        root = self.root
        files = {
            "docs/README.md": "# Project docs\n",
            self.QUEUE: "# Lessons — queue\n\n## Open\n\n### the cache key ignored mtime\n\n- **What happened:** x\n",
            self.ARCHIVE: mature_archive(3),
            CHECKER: drain_edited(S.render(self.layout(), {"src": "scripts/lessons_graph.py"}),
                                  self.ARCHIVE, self.QUEUE),
            ".claude/hooks/lessons_context.py": (
                "import pathlib\nDOCS = pathlib.Path(__file__).parents[2] / 'docs' / 'internal'\n"
                "ARCHIVE = DOCS / 'lessons-archive.md'\nprint('')\n"),
            ".claude/settings.json": json.dumps({"hooks": {"SessionStart": [{"hooks": [
                {"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/lessons_context.py"'}]}]}}),
        }
        for skill in ("lessons", "implement-ll"):
            files[f".claude/skills/{skill}/SKILL.md"] = (ASSETS / f"skills/{skill}/SKILL.md").read_text() + "\nOurs.\n"
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        self.ledger = {p: (root / p).read_bytes() for p in (self.QUEUE, self.ARCHIVE)}

    def archives_in(self, rel: str) -> list[str]:
        return [n for n in os.listdir(self.root / rel) if n.lower() == "lessons-archive.md"]

    def assert_no_second_ledger_or_hook(self):
        self.assertEqual(sorted(os.listdir(self.root / "docs")), ["README.md", "internal"])
        self.assertEqual(self.archives_in("docs/internal"), ["lessons-archive.md"])
        self.assertFalse((self.root / HOOK).exists())
        self.assertEqual(session_start_commands(self.root),
                         ['python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/lessons_context.py"'])
        self.assert_ledger_intact()

    def test_upgrade_finds_the_ledger_and_adds_no_second_ledger_or_hook(self):
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertIn("(ledger found in docs/internal/)", out)
        self.assertIn(".claude/hooks/lessons_context.py already injects the ledger", out)
        self.assertNotIn("fresh install", out)
        self.assert_no_second_ledger_or_hook()

    def test_nothing_of_ours_to_test_means_no_suite_in_the_projects_tests(self):
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertFalse((self.root / "tests/lessons_loop").exists())
        self.assertIn("SKIP (nothing of ours to test)", out)

    def test_with_docs_dir_the_lowercase_archive_is_preserved_not_duplicated(self):
        rc, out = self.run_installer("--upgrade", "--docs-dir", "docs/internal")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"PRESERVE (data — never overwritten) {self.ARCHIVE}", out)
        self.assert_no_second_ledger_or_hook()

    def test_the_archive_is_named_as_the_filesystem_spells_it(self):
        for docs_dir in (None, "docs/internal"):
            lay = S.detect_layout(argparse.Namespace(root=str(self.root), docs_dir=docs_dir,
                                                     scripts_dir=None, tests_dir=None))
            self.assertEqual(lay.archive, self.ARCHIVE)

    def test_an_unlocatable_ledger_is_refused_naming_docs_dir(self):
        notes = self.root / "notes"
        notes.mkdir()
        for rel in (self.QUEUE, self.ARCHIVE):
            (self.root / rel).rename(notes / Path(rel).name)
        before = snapshot(self.root)
        rc, out = self.cli("--upgrade")
        self.assertEqual(rc, 1, out)
        self.assertIn("a second ledger is never created", out)
        self.assertIn("--docs-dir", out)
        self.assertEqual(snapshot(self.root), before)

    def test_two_candidate_ledgers_are_refused(self):
        (self.root / "docs/old").mkdir()
        (self.root / "docs/old/LESSONS-ARCHIVE.md").write_text("# old\n")
        before = snapshot(self.root)
        rc, out = self.cli("--upgrade")
        self.assertEqual(rc, 1, out)
        self.assertIn("docs/internal/, docs/old/", out)
        self.assertEqual(snapshot(self.root), before)

    def test_with_the_shipped_checker_the_suite_runs_and_skips_only_the_hook(self):
        lay = S.detect_layout(argparse.Namespace(root=str(self.root), docs_dir=None, scripts_dir=None, tests_dir=None))
        (self.root / CHECKER).write_text(S.render(lay, S.planned_files(lay, False)[2]))
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertIn("skipped as this project's own: hook, lessons, implement-ll", out)
        self.assert_no_second_ledger_or_hook()


class SecondLessonsHookBesideTheGeneratedOne(MigrationBase):
    """Defect 3 when the generated hook is already registered: warn, change nothing."""

    def test_a_project_hook_reading_the_ledger_is_reported(self):
        self.seed_fresh(self.root)
        mine = self.root / ".claude/hooks/my_lessons.py"
        mine.write_text("print(open('docs/LESSONS-ARCHIVE.md').read())\n")
        settings = json.loads((self.root / ".claude/settings.json").read_text())
        settings["hooks"]["SessionStart"].append(
            {"hooks": [{"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/my_lessons.py"'}]})
        (self.root / ".claude/settings.json").write_text(json.dumps(settings))
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertIn(".claude/hooks/my_lessons.py also injects the ledger at SessionStart", out)
        self.assertEqual(len(session_start_commands(self.root)), 2)


class FormatterOnlyDifferences(MigrationBase):
    """Defect 5: a project formatter rewrote the shipped hook; that is not a project edit."""

    def setUp(self):
        super().setUp()
        self.seed_fresh(self.root, "--jev-provider", "openrouter")
        self.detector = self.root / DETECTOR
        self.shipped = self.detector.read_text()

    def test_a_reformatted_older_shipped_version_is_upgraded(self):
        self.detector.write_text(FORMATTED_V131.read_text())
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"upgrade (.bak kept)                {DETECTOR}", out)
        self.assertEqual(self.detector.read_text(), self.shipped)

    def test_the_formatted_fixture_differs_from_v131_only_in_formatting(self):
        v131 = (ASSETS / "legacy/hooks/lesson_detect.v1.3.1.py").read_text()
        formatted = FORMATTED_V131.read_text()
        self.assertNotEqual(formatted, v131)
        self.assertTrue(S.same_content(formatted, v131, DETECTOR))

    def test_a_reformatted_current_version_is_up_to_date_and_left_alone(self):
        self.detector.write_text(reformatted(self.shipped))
        before = self.detector.read_bytes()
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"up to date                         {DETECTOR}", out)
        self.assertEqual(self.detector.read_bytes(), before)

    def test_a_comment_edit_is_still_the_projects_own(self):
        self.detector.write_text(reformatted(self.shipped) + "# our tweak\n")
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"KEEP (edited in this project)      {DETECTOR}", out)

    def test_a_code_edit_is_still_the_projects_own(self):
        self.detector.write_text(self.shipped.replace("MAX_NUDGES = ", "MAX_NUDGES = 1 + ", 1))
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"KEEP (edited in this project)      {DETECTOR}", out)


if __name__ == "__main__":
    unittest.main()
