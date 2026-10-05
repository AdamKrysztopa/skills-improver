"""The optional evaluation log: what it records, what it must never record, and that switching it
on changes nothing the session or the state files can observe.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parent.parent / "plugins" / "skill-improver" / "skills" / "skill-improver"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


D = load("lesson_detect", SKILL / "assets/lessons-loop/hooks/lesson_detect.py")
E = load("jev_eval", SKILL / "scripts/jev_eval.py")

KEY = "sk-or-v1-" + "ab12" * 16
SECRET_PROMPT = "please deploy using password=hunter2hunter2 to the staging cluster right now"


def fail(cmd, err, sid="s1"):
    return {"session_id": sid, "tool_name": "Bash", "tool_input": {"command": cmd}, "error": err}


def queue_edit(title, sid="s1", tool="Edit"):
    body = f"### {title}\n\n- **What happened:** x\n- **Generalises to:** y\n"
    key = "new_string" if tool == "Edit" else "content"
    return {"session_id": sid, "tool_name": tool, "tool_input": {"file_path": "/p/docs/lessons.md", key: body},
            "cwd": "/p"}


class Scores:
    def __init__(self, *scores, error=None):
        self.scores, self.error = list(scores), error

    def __call__(self, provider, key, body):
        if self.error:
            raise D.JevError(self.error)
        return self.scores.pop(0)


class Session:
    """One scripted session against the real hook, with or without the eval log."""

    def __init__(self, tmp: Path, eval_target: str | None, scores):
        self.proj, self.state = tmp / "proj", tmp / "state"
        self.proj.mkdir(parents=True, exist_ok=True)
        self.env = {"OPENROUTER_API_KEY": KEY, **({D.EVAL_ENV: eval_target} if eval_target else {})}
        self.transport = scores
        self.now = 1_000_000.0

    def step(self, event, payload):
        self.now += 700
        return D.run(event, payload, "openrouter", env=self.env, project_dir=self.proj,
                     state_dir=self.state, now=self.now, transport=self.transport)

    def script(self):
        return [
            self.step("UserPromptSubmit", {"session_id": "s1", "prompt": SECRET_PROMPT}),
            self.step("PostToolUseFailure", fail("pytest -x", "Exit code 1\nAssertionError: 3 != 4")),
            self.step("PostToolUseFailure", fail("pytest -x tests/b", "Exit code 1\nKeyError: 'tenant_id'")),
            self.step("PostToolUse", queue_edit("Cache key ignores mtime")),
            self.step("PostToolUse", {"session_id": "s1", "tool_name": "Edit",
                                      "tool_input": {"file_path": "/p/src/app.py", "new_string": "### not a queue"}}),
        ]


class EvalLogTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def records(self, name="eval.jsonl"):
        return [json.loads(line) for line in (self.tmp / "proj" / name).read_text().splitlines()]

    def test_off_by_default_writes_no_file_anywhere(self):
        Session(self.tmp, None, Scores(0.2, 0.9, 0.1)).script()
        self.assertEqual(sorted(p.name for p in (self.tmp / "proj").iterdir()), [])

    def test_turning_it_on_changes_neither_output_nor_state(self):
        off = Session(self.tmp / "a", None, Scores(0.2, 0.9, 0.1))
        on = Session(self.tmp / "b", "eval.jsonl", Scores(0.2, 0.9, 0.1))
        self.assertEqual(off.script(), on.script())
        states = lambda s: {p.name: {k: v for k, v in json.loads(p.read_text()).items() if k != "project"}
                            for p in s.state.glob("*.json")}
        self.assertEqual(states(off), states(on))
        self.assertTrue((self.tmp / "b" / "proj" / "eval.jsonl").exists())

    def test_a_log_that_cannot_be_written_never_affects_the_hook(self):
        blocked = self.tmp / "proj" / "eval.jsonl"
        blocked.parent.mkdir(exist_ok=True)
        blocked.mkdir()
        reference = Session(self.tmp / "ref", None, Scores(0.2, 0.9, 0.1))
        broken = Session(self.tmp, "eval.jsonl", Scores(0.2, 0.9, 0.1))
        self.assertEqual(broken.script(), reference.script())

    def test_records_calls_nudges_and_queue_writes_in_order(self):
        Session(self.tmp, "eval.jsonl", Scores(0.2, 0.9, 0.1)).script()
        kinds = [(r["e"], r.get("outcome") or r.get("trigger")) for r in self.records()]
        self.assertEqual(kinds, [("call", "negative"), ("call", "positive"), ("nudge", "fail"),
                                 ("call", "negative"), ("queue_write", None)])
        self.assertEqual(self.records()[-1]["titles"], ["Cache key ignores mtime"])
        self.assertEqual(self.records()[1]["score"], 0.9)

    def test_provider_errors_are_counted_as_errors(self):
        Session(self.tmp, "eval.jsonl", Scores(error="transient")).step("PostToolUseFailure", fail("x", "boom boom"))
        self.assertEqual([(r["e"], r["outcome"]) for r in self.records()], [("call", "error:transient")])

    def test_the_log_holds_no_prompt_command_error_or_key(self):
        Session(self.tmp, "eval.jsonl", Scores(0.2, 0.9, 0.1)).script()
        raw = (self.tmp / "proj" / "eval.jsonl").read_text()
        for secret in (KEY, "hunter2", "deploy", "pytest", "AssertionError", "tenant_id"):
            self.assertNotIn(secret, raw)

    def test_queue_titles_are_redacted(self):
        session = Session(self.tmp, "eval.jsonl", Scores(0.9))
        session.step("PostToolUse", queue_edit("token=abcdef123456 leaked"))
        self.assertNotIn("abcdef123456", (self.tmp / "proj" / "eval.jsonl").read_text())

    def test_write_tool_content_counts_and_the_file_is_owner_only(self):
        session = Session(self.tmp, "eval.jsonl", Scores(0.9))
        session.step("PostToolUse", queue_edit("Via Write", tool="Write"))
        self.assertEqual(self.records()[0]["titles"], ["Via Write"])
        self.assertEqual(stat.S_IMODE((self.tmp / "proj" / "eval.jsonl").stat().st_mode), 0o600)

    def test_an_absolute_path_outside_the_project_is_honoured(self):
        target = self.tmp / "elsewhere" / "log.jsonl"
        Session(self.tmp, str(target), Scores(0.9)).step("PostToolUse", queue_edit("Abs"))
        self.assertEqual(json.loads(target.read_text())["e"], "queue_write")


class ReportTests(unittest.TestCase):
    def write(self, tmp, records):
        path = Path(tmp) / "log.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in records) + "\nnot json\n")
        return path

    def test_counts_followed_ignored_and_organic(self):
        log = [
            {"e": "call", "s": "a", "outcome": "positive"}, {"e": "nudge", "s": "a"},
            {"e": "queue_write", "s": "a", "titles": ["T1"]},
            {"e": "call", "s": "b", "outcome": "positive"}, {"e": "nudge", "s": "b"},
            {"e": "call", "s": "b", "outcome": "negative"},
            {"e": "call", "s": "c", "outcome": "error:auth"},
            {"e": "queue_write", "s": "c", "titles": ["Own capture"]},
            {"e": "queue_write", "s": "a", "titles": ["Second write, one nudge"]},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            summary = E.summarise(E.load(self.write(tmp, log)))
        self.assertEqual((summary["calls"], summary["positive"], summary["negative"], summary["errors"]), (4, 2, 1, 1))
        self.assertEqual((summary["nudges"], summary["followed"], summary["ignored"], summary["organic"]), (2, 1, 1, 2))

    def test_followed_entries_are_split_into_waiting_and_drained(self):
        log = [{"e": "nudge", "s": "a"}, {"e": "queue_write", "s": "a", "titles": ["Still here", "Gone"]}]
        with tempfile.TemporaryDirectory() as tmp:
            queue = Path(tmp) / "lessons.md"
            queue.write_text("# q\n\n```\n### Gone\n```\n\n## Open\n\n### Still here\n\n- **What happened:** x\n")
            summary = E.summarise(E.load(self.write(tmp, log)), queue)
        self.assertEqual((summary["followed_entries_waiting"], summary["followed_entries_drained"]), (1, 1))

    def test_command_line_report_and_missing_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, [{"e": "call", "s": "a", "outcome": "negative"}])
            ok = subprocess.run([sys.executable, str(SKILL / "scripts/jev_eval.py"), str(path)],
                                capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0)
            self.assertIn("Jev calls              : 1", ok.stdout)
            missing = subprocess.run([sys.executable, str(SKILL / "scripts/jev_eval.py"), str(Path(tmp) / "none")],
                                     capture_output=True, text=True)
            self.assertEqual(missing.returncode, 1)


if __name__ == "__main__":
    unittest.main()
