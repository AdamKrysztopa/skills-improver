"""Installer tests: --jev-provider across every mode, and the guarantees it must not break.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent / "plugins" / "skill-improver" / "skills" / "skill-improver"
_spec = importlib.util.spec_from_file_location("seed_lessons", SKILL / "scripts" / "seed_lessons.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)
DETECT = S.load_detector()

KEY = "sk-or-v1-" + "cd34" * 16
NO_KEYS = {"OPENROUTER_API_KEY": "", "TYPESAFE_API_KEY": ""}
HOOK_REL = ".claude/hooks/lesson_detect.py"
LOCAL = ".claude/settings.local.json"


class SeedJevTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        net = mock.patch.object(DETECT._OPENER, "open", side_effect=AssertionError("network used"))
        net.start()
        self.addCleanup(net.stop)
        home = mock.patch.object(S, "USER_CLAUDE_DIR", self.root.parent / "no-such-home")
        home.start()
        self.addCleanup(home.stop)
        self.probe = mock.Mock()
        p = mock.patch.object(S, "jev_probe", self.probe)
        p.start()
        self.addCleanup(p.stop)

    def seed(self, *args, env=None):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {**NO_KEYS, **(env or {})}), contextlib.redirect_stdout(out):
            rc = S.main(["--root", str(self.root), *args])
        return rc, out.getvalue()

    def read_local(self):
        return json.loads((self.root / LOCAL).read_text())

    def registered_events(self):
        return sorted(self.read_local().get("hooks", {}))

    # --- Jev off: the original behaviour ----------------------------------------
    def test_default_seed_has_no_jev_artefacts_and_makes_no_network_call(self):
        rc, out = self.seed("--seed")
        self.assertEqual(rc, 0, out)
        self.assertFalse((self.root / HOOK_REL).exists())
        self.assertFalse((self.root / LOCAL).exists())
        self.assertNotIn("lesson_detect", (self.root / ".claude/settings.json").read_text())
        self.assertIn("SessionStart", (self.root / ".claude/settings.json").read_text())
        self.assertTrue((self.root / "docs/lessons.md").exists())
        self.assertIn("passed", out)
        self.probe.assert_not_called()

    def test_dry_run_with_a_provider_writes_nothing_and_calls_nothing(self):
        rc, out = self.seed("--dry-run", "--jev-provider", "openrouter", env={"OPENROUTER_API_KEY": KEY})
        self.assertEqual(rc, 0)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertIn("lesson_detect.py", out)
        self.assertIn("dry run", out)
        self.assertNotIn(KEY, out)
        self.probe.assert_not_called()

    # --- enabling ----------------------------------------------------------------
    def test_seed_with_openrouter_installs_script_and_registers_three_hooks_personally(self):
        rc, out = self.seed("--seed", "--jev-provider", "openrouter", env={"OPENROUTER_API_KEY": KEY})
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / HOOK_REL).exists())
        self.assertEqual(self.registered_events(), ["PostToolUse", "PostToolUseFailure", "UserPromptSubmit"])
        self.assertNotIn("lesson_detect", (self.root / ".claude/settings.json").read_text())
        cmd = self.read_local()["hooks"]["UserPromptSubmit"][0]["hooks"][0]
        self.assertEqual(cmd["command"], 'python3 "$CLAUDE_PROJECT_DIR/%s" openrouter || true' % HOOK_REL)
        self.assertEqual(self.read_local()["hooks"]["PostToolUse"][0]["matcher"], "Bash|Edit|Write|MultiEdit")
        self.probe.assert_called_once_with("openrouter", KEY)
        for f in ("Provider", "Credential", "Connectivity", "Base lessons loop"):
            self.assertIn(f, out)
        self.assertIn("Connectivity : OK", out)

    def test_seed_from_session_and_typesafe(self):
        rc, out = self.seed("--seed-from-session", "--jev-provider", "typesafe", env={"TYPESAFE_API_KEY": KEY})
        self.assertEqual(rc, 0, out)
        cmd = self.read_local()["hooks"]["PostToolUseFailure"][0]["hooks"][0]["command"]
        self.assertTrue(cmd.endswith("lesson_detect.py\" typesafe || true"))
        self.probe.assert_called_once_with("typesafe", KEY)

    def test_a_missing_script_can_never_block_a_prompt_or_tool_call(self):
        self.seed("--seed", "--jev-provider", "openrouter")
        command = self.read_local()["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        (self.root / HOOK_REL).unlink()
        proc = subprocess.run(["sh", "-c", command], env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.root)},
                              input="{}", capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)

    def test_the_key_is_never_written_anywhere_in_the_project_or_the_report(self):
        rc, out = self.seed("--seed", "--jev-provider", "openrouter", env={"OPENROUTER_API_KEY": KEY})
        self.assertNotIn(KEY, out)
        for f in self.root.rglob("*"):
            if f.is_file():
                self.assertNotIn(KEY, f.read_text(errors="replace"), str(f))

    def test_key_in_project_dotenv_is_found_and_unignored_dotenv_is_flagged(self):
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        (self.root / ".env").write_text("OPENROUTER_API_KEY=%s\n" % KEY)
        rc, out = self.seed("--seed", "--jev-provider", "openrouter")
        self.assertEqual(rc, 0, out)
        self.probe.assert_called_once_with("openrouter", KEY)
        self.assertIn(".env", out)
        self.assertIn("not git-ignored", out)
        self.assertNotIn(KEY, out)

    def test_key_in_claude_settings_env_block_counts_as_found(self):
        (self.root / ".claude").mkdir()
        (self.root / LOCAL).write_text(json.dumps({"env": {"OPENROUTER_API_KEY": KEY}}))
        rc, out = self.seed("--seed", "--jev-provider", "openrouter")
        self.assertEqual(rc, 0, out)
        self.assertIn("found (Claude Code settings)", out)
        self.probe.assert_called_once_with("openrouter", KEY)
        self.assertNotIn(KEY, out)
        self.assertEqual(self.read_local()["env"], {"OPENROUTER_API_KEY": KEY})

    def test_ignored_dotenv_is_not_flagged(self):
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        (self.root / ".gitignore").write_text(".env\n")
        (self.root / ".env").write_text("OPENROUTER_API_KEY=%s\n" % KEY)
        rc, out = self.seed("--seed", "--jev-provider", "openrouter")
        self.assertNotIn("not git-ignored", out)

    # --- credentials and connectivity never break the base loop ------------------
    def test_missing_credential_installs_everything_and_says_how_to_enable(self):
        rc, out = self.seed("--seed", "--jev-provider", "openrouter")
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "docs/LESSONS-ARCHIVE.md").exists())
        self.assertIn("Credential   : missing", out)
        self.assertIn("OPENROUTER_API_KEY", out)
        self.probe.assert_not_called()

    def test_provider_failures_are_reported_and_never_change_the_exit_code(self):
        cases = {"credit": "no credit", "auth": "rejected", "transient": "unreachable", "malformed": "unexpected"}
        for kind, phrase in cases.items():
            with self.subTest(kind=kind):
                shutil.rmtree(self.root)
                self.root.mkdir()
                self.probe.side_effect = DETECT.JevError(kind)
                rc, out = self.seed("--seed", "--jev-provider", "openrouter", env={"OPENROUTER_API_KEY": KEY})
                self.assertEqual(rc, 0, out)
                self.assertIn(phrase, out)

    # --- upgrade safety ----------------------------------------------------------
    def test_upgrade_preserves_ledger_registration_and_provider_and_never_enables(self):
        self.seed("--seed", "--jev-provider", "typesafe", env={"TYPESAFE_API_KEY": KEY})
        self.probe.reset_mock()
        (self.root / "docs/lessons.md").write_text("# Lessons — queue\n\n## Open\n\n### user entry\n")
        (self.root / "docs/LESSONS-ARCHIVE.md").write_text("# archive mine\n")
        before = (self.root / LOCAL).read_text()
        (self.root / HOOK_REL).write_text("# stale hook\n")
        rc, out = self.seed("--upgrade")
        self.assertEqual(rc, 0, out)
        self.assertIn("user entry", (self.root / "docs/lessons.md").read_text())
        self.assertEqual((self.root / "docs/LESSONS-ARCHIVE.md").read_text(), "# archive mine\n")
        self.assertEqual((self.root / LOCAL).read_text(), before)
        self.assertIn("lesson_detect", (self.root / HOOK_REL).read_text())
        self.assertTrue((self.root / (HOOK_REL + ".bak")).exists())
        self.probe.assert_not_called()

    def test_upgrade_of_a_jev_less_install_does_not_enable_even_with_a_key_present(self):
        self.seed("--seed")
        rc, out = self.seed("--upgrade", env={"OPENROUTER_API_KEY": KEY})
        self.assertEqual(rc, 0, out)
        self.assertFalse((self.root / HOOK_REL).exists())
        self.assertFalse((self.root / LOCAL).exists())
        self.assertNotIn("Jev", out)
        self.probe.assert_not_called()

    def test_upgrade_can_add_jev_and_can_switch_provider(self):
        self.seed("--seed")
        self.seed("--upgrade", "--jev-provider", "openrouter", env={"OPENROUTER_API_KEY": KEY})
        self.assertTrue((self.root / HOOK_REL).exists())
        self.seed("--upgrade", "--jev-provider", "typesafe", env={"TYPESAFE_API_KEY": KEY})
        cmds = [h["command"] for ev in self.read_local()["hooks"].values() for g in ev for h in g["hooks"]]
        self.assertEqual(len(cmds), 3)
        self.assertTrue(all(c.endswith("typesafe || true") for c in cmds))

    def test_off_removes_only_our_registrations_and_leaves_user_hooks_alone(self):
        (self.root / ".claude").mkdir()
        mine = {"hooks": {"PostToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "fmt.sh"}]}]},
                "permissions": {"allow": ["Bash(ls)"]}}
        (self.root / LOCAL).write_text(json.dumps(mine))
        self.seed("--seed", "--jev-provider", "openrouter")
        self.assertEqual(len(self.read_local()["hooks"]["PostToolUse"]), 2)
        rc, out = self.seed("--upgrade", "--jev-provider", "off")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.read_local(), mine)
        self.assertTrue((self.root / HOOK_REL).exists())
        self.assertNotIn("Credential", out)

    def test_enabling_leaves_user_hook_groups_it_does_not_own_untouched(self):
        (self.root / ".claude").mkdir()
        mine = {"hooks": {"PostToolUse": [{"matcher": "X"}, {"matcher": "Y", "hooks": []}]}}
        (self.root / LOCAL).write_text(json.dumps(mine))
        self.seed("--seed", "--jev-provider", "openrouter")
        self.assertEqual(self.read_local()["hooks"]["PostToolUse"][:2], mine["hooks"]["PostToolUse"])
        self.seed("--upgrade", "--jev-provider", "off")
        self.assertEqual(self.read_local(), mine)

    def test_registering_twice_is_idempotent(self):
        self.seed("--seed", "--jev-provider", "openrouter")
        first = (self.root / LOCAL).read_text()
        self.seed("--upgrade", "--jev-provider", "openrouter")
        self.assertEqual((self.root / LOCAL).read_text(), first)

    def test_unparseable_local_settings_are_reported_not_clobbered(self):
        (self.root / ".claude").mkdir()
        (self.root / LOCAL).write_text("{oops")
        rc, out = self.seed("--seed", "--jev-provider", "openrouter")
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.root / LOCAL).read_text(), "{oops")
        self.assertIn("UNPARSEABLE", out)
        rc, out = self.seed("--upgrade", "--jev-provider", "off")
        self.assertIn("UNPARSEABLE", out)
        self.assertNotIn("unregistered", out)

    def test_already_installed_gate_is_unchanged(self):
        self.seed("--seed")
        rc, out = self.seed("--seed", "--jev-provider", "openrouter")
        self.assertEqual(rc, 2)
        self.assertIn("--upgrade", out)
        self.assertFalse((self.root / LOCAL).exists())

    def test_unknown_provider_is_rejected_by_the_parser(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.seed("--seed", "--jev-provider", "banana")


if __name__ == "__main__":
    unittest.main()
