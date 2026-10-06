"""Migration tests: a project seeded by the real v1.2.0 installer, upgraded by the current one.

The v1.2 project is produced by running the v1.2.0 installer itself (tests/fixtures/v1_2, a
byte-for-byte snapshot of commit 6f19174), not by hand-writing what it would have produced.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent / "plugins" / "skill-improver" / "skills" / "skill-improver"
V12_INSTALLER = HERE / "fixtures" / "v1_2" / "scripts" / "seed_lessons.py"
_spec = importlib.util.spec_from_file_location("seed_lessons", SKILL / "scripts" / "seed_lessons.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)
DETECT = S.load_detector()

KEY = "sk-or-v1-" + "ab12" * 16
TS_KEY = "ts-" + "9f3c" * 16
NO_KEYS = {"OPENROUTER_API_KEY": "", "TYPESAFE_API_KEY": ""}
LOCAL = ".claude/settings.local.json"
DETECTOR = ".claude/hooks/lesson_detect.py"
LOOP_TEST = "tests/lessons_loop/test_lessons_loop.py"

USER_QUEUE_ENTRY = """
### Migration must not lose me

- **What happened:** the nightly job reused a stale cache (`jobs/nightly.py:41`); found by running it.
- **Generalises to:** Any cache keyed on a path alone must also be keyed on the file's mtime.
- **Candidate home:** `.claude/hooks/check_cache.py`
"""

USER_ARCHIVE_SECTION = """
## 2026-02-03 — drain 1

| id | rule | home | commit | edges |
|------|------|------|--------|-------|
| L1.1 | Every environment variable a script reads must be documented next to the script. | `scripts/check_env.py` | a1b2c3d | — |
| L1.2 | declined: a naming convention nobody could state a failure for. | — | a1b2c3d | — |
"""


def snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and not {".git", "__pycache__"} & set(p.relative_to(root).parts)}


class MigrationBase(unittest.TestCase):
    installer = V12_INSTALLER
    skeleton = ("docs", "scripts", "tests")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.root = base / "project"
        self.root.mkdir()
        self.home = base / "home"
        self.home.mkdir()
        for name in self.skeleton:
            (self.root / name).mkdir()
        net = mock.patch.object(DETECT._OPENER, "open", side_effect=AssertionError("network used"))
        net.start()
        self.addCleanup(net.stop)
        home = mock.patch.object(S, "USER_CLAUDE_DIR", self.home / ".claude")
        home.start()
        self.addCleanup(home.stop)
        self.probe = mock.Mock()
        p = mock.patch.object(S, "jev_probe", self.probe)
        p.start()
        self.addCleanup(p.stop)

    # --- drivers ----------------------------------------------------------------------
    def env(self, extra=None):
        return {**os.environ, "HOME": str(self.home), "GIT_CONFIG_GLOBAL": os.devnull,
                "XDG_CONFIG_HOME": str(self.home / "xdg"), **NO_KEYS, **(extra or {})}

    def seed_old(self, *args):
        proc = subprocess.run([sys.executable, str(self.installer), "--root", str(self.root),
                               *(args or ("--seed",))],
                              env=self.env(), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def seed_fresh(self, root: Path, *args):
        with mock.patch.dict(os.environ, self.env()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(S.main(["--root", str(root), "--seed", *args]), 0)

    def run_installer(self, *args, env=None):
        out = io.StringIO()
        with mock.patch.dict(os.environ, self.env(env)), contextlib.redirect_stdout(out):
            rc = S.main(["--root", str(self.root), *args])
        return rc, out.getvalue()

    def cli(self, *args, env=None):
        """The installer exactly as a user runs it: a subprocess, no mocks (so: no key, no network)."""
        proc = subprocess.run([sys.executable, str(SKILL / "scripts" / "seed_lessons.py"),
                               "--root", str(self.root), *args],
                              env=self.env(env), capture_output=True, text=True)
        return proc.returncode, proc.stdout + proc.stderr

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, env=self.env(),
                              capture_output=True, text=True).stdout

    def git_init(self):
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True, env=self.env())

    # --- the realistic starting state ------------------------------------------------------
    def make_old_project(self, *seed_args, docs="docs"):
        """A project seeded by `self.installer` that has been lived in: real queue entry, real drained archive."""
        self.seed_old(*seed_args)
        with (self.root / docs / "lessons.md").open("a", encoding="utf-8") as q:
            q.write(USER_QUEUE_ENTRY)
        with (self.root / docs / "LESSONS-ARCHIVE.md").open("a", encoding="utf-8") as a:
            a.write(USER_ARCHIVE_SECTION)
        self.ledger = {p: (self.root / p).read_bytes() for p in (docs + "/lessons.md", docs + "/LESSONS-ARCHIVE.md")}

    def assert_ledger_intact(self):
        for rel, before in self.ledger.items():
            self.assertEqual((self.root / rel).read_bytes(), before, rel + " was modified")

    def layout(self):
        return S.detect_layout(argparse.Namespace(root=str(self.root), docs_dir=None,
                                                  scripts_dir=None, tests_dir=None))

    def read_local(self):
        return json.loads((self.root / LOCAL).read_text())

    def local_commands(self):
        return [h["command"] for groups in self.read_local().get("hooks", {}).values()
                for g in groups for h in g["hooks"]]

    def tree_without_baks(self):
        return {k: v for k, v in snapshot(self.root).items() if ".bak" not in k}

    def assert_machinery_matches_a_fresh_install(self, *fresh_args):
        fresh = Path(self._tmp.name) / "fresh"
        fresh.mkdir()
        for name in self.skeleton:
            (fresh / name).mkdir()
        self.seed_fresh(fresh, *fresh_args)
        migrated, pristine = self.tree_without_baks(), snapshot(fresh)
        data = {"docs/lessons.md", "docs/LESSONS-ARCHIVE.md"}
        for rel, content in pristine.items():
            if rel not in data:
                self.assertEqual(migrated.get(rel), content, rel)
        self.assertEqual(set(migrated) - set(pristine), set())


class InstallLeavesNoBytecode(MigrationBase):
    def test_a_fresh_seed_writes_no_pycache_anywhere_in_the_project(self):
        env = {k: v for k, v in self.env().items() if k != "PYTHONDONTWRITEBYTECODE"}
        env.pop("PYTHONPYCACHEPREFIX", None)
        proc = subprocess.run([sys.executable, str(SKILL / "scripts" / "seed_lessons.py"),
                               "--root", str(self.root), "--seed"],
                              env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual([str(p) for p in self.root.rglob("__pycache__")], [])


class SnapshotIsGenuine(unittest.TestCase):
    def test_the_v12_fixture_is_the_v12_release_not_an_approximation(self):
        for rel, fixture in (("scripts/seed_lessons.py", V12_INSTALLER),
                             ("assets/lessons-loop/skills/lessons/SKILL.md",
                              HERE / "fixtures/v1_2/assets/lessons-loop/skills/lessons/SKILL.md"),
                             ("assets/lessons-loop/hooks/session_start_lessons.py",
                              HERE / "fixtures/v1_2/assets/lessons-loop/hooks/session_start_lessons.py")):
            git_path = "plugins/skill-improver/skills/skill-improver/" + rel
            proc = subprocess.run(["git", "show", "6f19174:" + git_path], cwd=HERE,
                                  capture_output=True)
            if proc.returncode != 0:
                self.skipTest("commit 6f19174 is not in this clone")
            self.assertEqual(fixture.read_bytes(), proc.stdout, rel)

    def test_v12_has_no_jev_capability(self):
        self.assertNotIn("jev", V12_INSTALLER.read_text().lower())
        self.assertFalse((HERE / "fixtures/v1_2/assets/lessons-loop/hooks/lesson_detect.py").exists())


class UpgradeFromV12(MigrationBase):
    def setUp(self):
        super().setUp()
        self.make_old_project()

    def test_dry_run_recognises_the_existing_loop_and_changes_nothing(self):
        before = snapshot(self.root)
        rc, out = self.cli("--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("EXISTING LOOP DETECTED", out)
        self.assertIn("--upgrade", out)
        self.assertIn("JEV-ASSISTED LESSON DETECTION: not enabled", out)
        self.assertEqual(snapshot(self.root), before)

    def test_seed_over_a_v12_project_is_refused_and_points_at_upgrade(self):
        before = snapshot(self.root)
        rc, out = self.cli("--seed")
        self.assertEqual(rc, 2)
        self.assertIn("--upgrade", out)
        self.assertEqual(snapshot(self.root), before)

    def test_plain_upgrade_refreshes_machinery_preserves_ledger_and_does_not_enable_jev(self):
        rc, out = self.run_installer("--upgrade", env={"OPENROUTER_API_KEY": KEY, "TYPESAFE_API_KEY": TS_KEY})
        self.assertEqual(rc, 0, out)
        self.assert_ledger_intact()
        self.assertFalse((self.root / DETECTOR).exists())
        self.assertFalse((self.root / LOCAL).exists())
        self.assertIn("JEV-ASSISTED LESSON DETECTION: not enabled", out)
        self.assertIn("--jev-provider", out)
        self.probe.assert_not_called()
        self.assertNotIn(KEY, out)
        self.assertNotIn(TS_KEY, out)

    def test_upgraded_machinery_is_identical_to_a_fresh_v13_install(self):
        self.run_installer("--upgrade")
        self.assert_machinery_matches_a_fresh_install()

    def test_the_migrated_loop_actually_works_on_the_real_ledger(self):
        rc, out = self.run_installer("--upgrade")
        self.assertIn("passed", out)
        env = {**self.env(), "CLAUDE_PROJECT_DIR": str(self.root)}
        hook = subprocess.run([sys.executable, str(self.root / ".claude/hooks/session_start_lessons.py")],
                              env=env, capture_output=True, text=True, cwd=self.root)
        context = json.loads(hook.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Every environment variable a script reads", context)
        self.assertIn("Migration must not lose me", context)
        checker = subprocess.run([sys.executable, str(self.root / "scripts/lessons_graph.py")],
                                 env=env, capture_output=True, text=True)
        self.assertEqual(checker.returncode, 0, checker.stdout)

    def test_upgrade_with_openrouter_enables_jev_only_because_it_was_asked(self):
        rc, out = self.run_installer("--upgrade", "--jev-provider", "openrouter", env={"OPENROUTER_API_KEY": KEY})
        self.assertEqual(rc, 0, out)
        self.assert_ledger_intact()
        self.assertTrue((self.root / DETECTOR).exists())
        self.assertEqual(sorted(self.read_local()["hooks"]), ["PostToolUse", "PostToolUseFailure", "UserPromptSubmit"])
        self.assertTrue(all(c.endswith("openrouter || true") for c in self.local_commands()))
        self.probe.assert_called_once_with("openrouter", KEY)
        self.assertIn("Connectivity : OK", out)
        self.assertNotIn(KEY, out)

    def test_upgrade_with_typesafe_enables_that_provider_and_not_the_other(self):
        rc, out = self.run_installer("--upgrade", "--jev-provider", "typesafe",
                                     env={"TYPESAFE_API_KEY": TS_KEY, "OPENROUTER_API_KEY": KEY})
        self.assertEqual(rc, 0, out)
        self.assertTrue(all(c.endswith("typesafe || true") for c in self.local_commands()))
        self.probe.assert_called_once_with("typesafe", TS_KEY)

    def test_a_later_plain_upgrade_keeps_the_chosen_provider(self):
        self.run_installer("--upgrade", "--jev-provider", "typesafe", env={"TYPESAFE_API_KEY": TS_KEY})
        self.probe.reset_mock()
        before = (self.root / LOCAL).read_text()
        rc, out = self.run_installer("--upgrade", env={"OPENROUTER_API_KEY": KEY})
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.root / LOCAL).read_text(), before)
        self.assertIn("enabled (typesafe)", out)
        self.probe.assert_not_called()

    def test_missing_provider_key_still_migrates_and_says_how_to_finish(self):
        rc, out = self.run_installer("--upgrade", "--jev-provider", "openrouter")
        self.assertEqual(rc, 0, out)
        self.assert_ledger_intact()
        self.assertIn("Credential   : missing", out)
        self.assertIn("OPENROUTER_API_KEY", out)
        self.probe.assert_not_called()

    def test_provider_failures_never_fail_the_migration(self):
        self.probe.side_effect = DETECT.JevError("credit")
        rc, out = self.run_installer("--upgrade", "--jev-provider", "openrouter", env={"OPENROUTER_API_KEY": KEY})
        self.assertEqual(rc, 0, out)
        self.assertIn("no credit", out)
        self.assert_ledger_intact()

    def test_explicit_off_on_a_legacy_project_changes_no_files(self):
        self.run_installer("--upgrade")
        before = snapshot(self.root)
        rc, out = self.run_installer("--upgrade", "--jev-provider", "off")
        self.assertEqual(rc, 0, out)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((self.root / LOCAL).exists())

    def test_migrate_then_enable_then_off_leaves_user_settings_and_ledger_as_they_were(self):
        mine = {"hooks": {"PostToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "fmt.sh"}]}]},
                "permissions": {"allow": ["Bash(ls)"]}}
        (self.root / LOCAL).write_text(json.dumps(mine))
        self.run_installer("--upgrade", "--jev-provider", "openrouter", env={"OPENROUTER_API_KEY": KEY})
        self.assertEqual(len(self.read_local()["hooks"]["PostToolUse"]), 2)
        rc, out = self.run_installer("--upgrade", "--jev-provider", "off")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.read_local(), mine)
        self.assert_ledger_intact()
        self.assertTrue((self.root / DETECTOR).exists())

    def test_a_second_upgrade_is_a_no_op(self):
        self.run_installer("--upgrade", "--jev-provider", "openrouter", env={"OPENROUTER_API_KEY": KEY})
        after_first = snapshot(self.root)
        rc, out = self.run_installer("--upgrade", "--jev-provider", "openrouter", env={"OPENROUTER_API_KEY": KEY})
        self.assertEqual(rc, 0, out)
        self.assertEqual(snapshot(self.root), after_first)

    def test_a_second_plain_upgrade_is_a_no_op_and_keeps_the_first_backups(self):
        self.run_installer("--upgrade")
        after_first = snapshot(self.root)
        self.assertIn("docs/lessons.md", after_first)
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertEqual(snapshot(self.root), after_first)

    def test_a_pristine_v12_install_has_nothing_the_upgrade_would_keep(self):
        rc, out = self.cli("--dry-run")
        self.assertIn("0 carry your own edits", out)
        self.assertNotIn("KEEP", out)

    def test_a_file_the_project_amended_is_kept_untouched_and_reported(self):
        implement = self.root / ".claude/skills/implement-ll/SKILL.md"
        hook = self.root / ".claude/hooks/session_start_lessons.py"
        loop_test = self.root / LOOP_TEST
        implement.write_text(implement.read_text() + "\n- Learned rule: always rerun the nightly job twice.\n")
        hook.write_text(hook.read_text() + "\n# MY LOCAL TWEAK\n")
        edited = {p: p.read_bytes() for p in (implement, hook)}
        held = loop_test.read_bytes()
        for args in (("--upgrade",), ("--upgrade", "--jev-provider", "openrouter"), ("--upgrade",)):
            rc, out = self.run_installer(*args)
            self.assertEqual(rc, 0, out)
            self.assertIn("KEPT AS YOU LEFT THEM", out)
            self.assertIn(".claude/skills/implement-ll/SKILL.md", out)
            self.assertIn(f"{LOOP_TEST} held at its previous version because "
                          ".claude/hooks/session_start_lessons.py carries your edits", out)
            for path, content in edited.items():
                self.assertEqual(path.read_bytes(), content)
            self.assertEqual(loop_test.read_bytes(), held)
        self.assertTrue((self.root / DETECTOR).exists())
        dry = self.run_installer("--dry-run")[1]
        self.assertIn("KEEP (edited in this project)", dry)
        self.assertIn("HELD (its partner carries your edits)", dry)

    def test_an_amended_loop_test_holds_the_hook_at_its_previous_version(self):
        hook = self.root / ".claude/hooks/session_start_lessons.py"
        loop_test = self.root / LOOP_TEST
        loop_test.write_text(loop_test.read_text() + "\n# MY LOCAL CHECK\n")
        edited, held = loop_test.read_bytes(), hook.read_bytes()
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertEqual(loop_test.read_bytes(), edited)
        self.assertEqual(hook.read_bytes(), held)
        self.assertIn(f".claude/hooks/session_start_lessons.py held at its previous version because "
                      f"{LOOP_TEST} carries your edits", out)

    def test_an_amended_checker_is_kept_while_the_rest_upgrades(self):
        checker = self.root / "scripts/lessons_graph.py"
        checker.write_text(checker.read_text() + "\n# MY LOCAL TWEAK\n")
        edited = checker.read_bytes()
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertEqual(checker.read_bytes(), edited)
        self.assertNotIn("held at its previous version", out)

    def test_moving_an_amended_file_aside_lets_the_upgrade_install_the_current_one(self):
        hook = self.root / ".claude/hooks/session_start_lessons.py"
        hook.write_text(hook.read_text() + "\n# MY LOCAL TWEAK\n")
        hook.rename(hook.with_name("session_start_lessons.py.mine"))
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("MY LOCAL TWEAK", hook.read_text())
        self.assertIn("MY LOCAL TWEAK", hook.with_name("session_start_lessons.py.mine").read_text())

    def test_the_previous_shipped_detector_is_refreshed_and_its_backup_survives_repeats(self):
        self.run_installer("--upgrade", "--jev-provider", "openrouter")
        detector = self.root / DETECTOR
        legacy = SKILL / "assets/lessons-loop/legacy/hooks/lesson_detect.v1.3.0.py"
        detector.write_text(legacy.read_text())
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertNotEqual(detector.read_text(), legacy.read_text())
        self.assertEqual(detector.with_name("lesson_detect.py.bak").read_text(), legacy.read_text())
        self.run_installer("--upgrade")
        self.assertEqual(detector.with_name("lesson_detect.py.bak").read_text(), legacy.read_text())


class WiringIsPreserved(MigrationBase):
    def test_registration_user_hooks_and_permissions_survive_byte_for_byte(self):
        (self.root / ".claude").mkdir()
        settings = {
            "permissions": {"allow": ["Bash(ls)"], "deny": ["Bash(rm -rf:*)"]},
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "guard.sh"}]}],
                      "SessionStart": [{"hooks": [{"type": "command", "command": "echo mine"}]}]},
            "statusLine": {"type": "command", "command": "status.sh"},
        }
        (self.root / ".claude/settings.json").write_text(json.dumps(settings, indent=4))
        self.seed_old()
        registered = (self.root / ".claude/settings.json").read_text()
        self.assertEqual(registered.count("session_start_lessons.py"), 1)
        for key in ("PreToolUse", "guard.sh", "echo mine", "statusLine", "Bash(rm -rf:*)"):
            self.assertIn(key, registered)
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.root / ".claude/settings.json").read_text(), registered)
        self.assertIn("already registered", out)

    def test_a_customised_session_start_command_is_respected_not_duplicated(self):
        self.seed_old()
        path = self.root / ".claude/settings.json"
        settings = json.loads(path.read_text())
        settings["hooks"]["SessionStart"][0]["hooks"][0]["command"] = (
            'uv run python "$CLAUDE_PROJECT_DIR/.claude/hooks/session_start_lessons.py"')
        path.write_text(json.dumps(settings))
        before = path.read_text()
        self.run_installer("--upgrade")
        self.assertEqual(path.read_text(), before)

    def test_unrelated_personal_hooks_and_env_survive_enabling(self):
        self.seed_old()
        mine = {"env": {"FOO": "bar"},
                "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "log.sh"}]}]}}
        (self.root / LOCAL).write_text(json.dumps(mine))
        self.run_installer("--upgrade", "--jev-provider", "openrouter")
        local = self.read_local()
        self.assertEqual(local["env"], {"FOO": "bar"})
        self.assertEqual(local["hooks"]["UserPromptSubmit"][0], mine["hooks"]["UserPromptSubmit"][0])
        self.assertEqual(len(local["hooks"]["UserPromptSubmit"]), 2)

    def test_a_loop_seeded_before_the_project_grew_new_directories_is_upgraded_in_place(self):
        for name in self.skeleton:
            (self.root / name).rmdir()
        for name in ("doc", "bin", "test"):
            (self.root / name).mkdir()
        self.make_old_project(docs="doc")
        self.assertTrue((self.root / "doc/lessons.md").exists())
        for name in ("docs", "scripts", "tests"):
            (self.root / name).mkdir()
        rc, out = self.run_installer("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assert_ledger_intact()
        self.assertFalse((self.root / "docs/lessons.md").exists())
        self.assertFalse((self.root / "scripts/lessons_graph.py").exists())
        self.assertFalse((self.root / "tests").joinpath("lessons_loop").exists())
        self.assertTrue((self.root / "test/lessons_loop/test_lessons_loop.py").exists())
        self.assertTrue((self.root / "bin/lessons_graph.py").exists())
        self.assertIn("doc/", out)

    def test_an_edited_hook_that_points_somewhere_unrecognisable_stops_the_upgrade(self):
        self.make_old_project()
        hook = self.root / ".claude/hooks/session_start_lessons.py"
        hook.write_text(hook.read_text().replace('QUEUE_REL = "docs/lessons.md"', 'QUEUE_REL = "notes/todo.md"'))
        before = snapshot(self.root)
        rc, out = self.cli("--upgrade")
        self.assertNotEqual(rc, 0)
        self.assertEqual(snapshot(self.root), before)
        self.assertIn("--docs-dir", out)


class NoCredentialLeaks(MigrationBase):
    def test_no_untracked_unignored_or_backup_file_ever_holds_a_key(self):
        self.git_init()
        self.make_old_project()
        (self.root / ".claude").mkdir(exist_ok=True)
        (self.root / LOCAL).write_text(json.dumps({"env": {"OPENROUTER_API_KEY": KEY}}))
        self.run_installer("--upgrade", "--jev-provider", "openrouter")
        self.run_installer("--upgrade", "--jev-provider", "typesafe", env={"TYPESAFE_API_KEY": TS_KEY})
        self.run_installer("--upgrade", "--jev-provider", "off")
        visible = self.git("ls-files", "--others", "--exclude-standard").split()
        self.assertTrue(visible)
        for rel in visible:
            text = (self.root / rel).read_text(errors="replace")
            self.assertNotIn(KEY, text, rel)
            self.assertNotIn(TS_KEY, text, rel)
        holders = [p for p, data in snapshot(self.root).items() if KEY.encode() in data]
        self.assertEqual(holders, [LOCAL])
        self.assertNotIn("settings.local", self.git("ls-files", "--others", "--exclude-standard"))

    def test_a_key_held_in_the_shared_settings_file_is_not_copied_into_a_backup(self):
        self.seed_old()
        path = self.root / ".claude/settings.json"
        settings = json.loads(path.read_text())
        settings["env"] = {"OPENROUTER_API_KEY": KEY}
        settings["hooks"]["SessionStart"] = []
        path.write_text(json.dumps(settings))
        self.run_installer("--upgrade")
        holders = [p for p, data in snapshot(self.root).items() if KEY.encode() in data]
        self.assertEqual(holders, [".claude/settings.json"])


class FailureCannotDamageTheLoop(MigrationBase):
    def setUp(self):
        super().setUp()
        self.make_old_project()

    def test_a_write_failure_midway_restores_every_file_already_replaced(self):
        before = snapshot(self.root)
        tests_dir = self.root / ".claude/hooks"
        os.chmod(tests_dir, stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(os.chmod, tests_dir, stat.S_IRWXU)
        if os.access(tests_dir, os.W_OK):
            self.skipTest("directory permissions are not enforced here (running as root?)")
        rc, out = self.run_installer("--upgrade", "--jev-provider", "openrouter", env={"OPENROUTER_API_KEY": KEY})
        os.chmod(tests_dir, stat.S_IRWXU)
        self.assertNotEqual(rc, 0, out)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((self.root / LOCAL).exists())

    def test_a_failing_post_upgrade_check_rolls_the_upgrade_back(self):
        before = snapshot(self.root)
        with mock.patch.object(S, "verify", return_value=["a forced failure"]):
            rc, out = self.run_installer("--upgrade", "--jev-provider", "openrouter", env={"OPENROUTER_API_KEY": KEY})
        self.assertNotEqual(rc, 0)
        self.assertIn("rolled back", out)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((self.root / LOCAL).exists())

    def test_the_rollback_is_real_because_the_new_machinery_is_checked_by_running_it(self):
        before = snapshot(self.root)
        with mock.patch.object(S, "ASSETS", self._tampered_assets()):
            rc, out = self.run_installer("--upgrade")
        self.assertNotEqual(rc, 0, out)
        self.assertIn("rolled back", out)
        self.assertEqual(snapshot(self.root), before)

    def _tampered_assets(self) -> Path:
        copy = Path(self._tmp.name) / "tampered-assets"
        shutil.copytree(SKILL / "assets/lessons-loop", copy, ignore=shutil.ignore_patterns("__pycache__"))
        (copy / "skills/lessons/SKILL.md").write_text("---\nname: lessons\n---\n")
        return copy


if __name__ == "__main__":
    unittest.main()
