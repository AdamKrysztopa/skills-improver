"""Parallel hook invocations must not lose events or overspend the call/nudge budget."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

HOOK = (Path(__file__).resolve().parent.parent / "plugins" / "skill-improver" / "skills"
        / "skill-improver" / "assets" / "lessons-loop" / "hooks" / "lesson_detect.py")
_spec = importlib.util.spec_from_file_location("lesson_detect", HOOK)
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)

ENV = {"OPENROUTER_API_KEY": "sk-or-v1-" + "cd34" * 16}


def bash_ok(i: int) -> dict:
    return {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash",
            "tool_input": {"command": f"echo step-{i}"}, "tool_response": {}}


def bash_fail(i: int) -> dict:
    return {"hook_event_name": "PostToolUseFailure", "session_id": "s1", "tool_name": "Bash",
            "tool_input": {"command": f"pytest tests/test_{i}.py"}, "error": f"AssertionError in case {i}"}


class Concurrency(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.state = self.root / "state"
        self.now = time.time()
        real = D.load_state

        def slow_load(path, *, now):
            data = real(path, now=now)
            time.sleep(0.05)
            return data

        p = mock.patch.object(D, "load_state", slow_load)
        p.start()
        self.addCleanup(p.stop)

    def fire(self, payloads, transport=None):
        outs = [None] * len(payloads)

        def one(i, payload):
            outs[i] = D.run(payload["hook_event_name"], payload, "openrouter", env=ENV,
                            project_dir=self.root, state_dir=self.state, now=self.now,
                            transport=transport or (lambda *a: 0.0))

        threads = [threading.Thread(target=one, args=(i, p)) for i, p in enumerate(payloads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return outs

    def test_parallel_events_are_all_kept(self):
        self.fire([bash_ok(i) for i in range(6)])
        self.assertEqual(len(_plain_load(self.state / "s1.json", self.now)["window"]), 6)

    def test_parallel_failures_nudge_once_and_count_every_call(self):
        calls = []

        def transport(*args):
            calls.append(1)
            time.sleep(0.05)
            return 0.95

        outs = self.fire([bash_fail(i) for i in range(4)], transport)
        state = _plain_load(self.state / "s1.json", self.now)
        self.assertEqual(sum(o is not None for o in outs), 1, "cooldown must hold across parallel hooks")
        self.assertEqual(state["nudges"], 1)
        self.assertEqual(state["calls"], len(calls))

    def test_without_fcntl_the_hook_still_runs(self):
        with mock.patch.object(D, "fcntl", None):
            self.fire([bash_ok(0)])
        self.assertEqual(len(_plain_load(self.state / "s1.json", self.now)["window"]), 1)


def _plain_load(path: Path, now: float) -> dict:
    return {**D.new_state(), **json.loads(path.read_text())}


if __name__ == "__main__":
    unittest.main()
