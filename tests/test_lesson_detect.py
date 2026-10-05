"""Tests for the Jev-assisted lesson detector hook (no live network).

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import http.client
import http.server
import importlib.util
import json
import os
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


class CoreTests(unittest.TestCase):
    def test_redact_strips_bearer_and_key_assignments(self):
        out = D.redact("curl -H 'Authorization: Bearer sk-abc123' OPENROUTER_API_KEY=sk-live-999 x", 200)
        self.assertNotIn("sk-abc123", out)
        self.assertNotIn("sk-live-999", out)

    def test_redact_strips_long_opaque_tokens_and_truncates(self):
        out = D.redact("token " + "a1b2c3d4" * 8 + " tail", 40)
        self.assertNotIn("a1b2c3d4a1b2c3d4", out)
        self.assertLessEqual(len(out), 40)

    def test_normalize_skips_noise(self):
        fail = {"tool_name": "Bash", "tool_input": {"command": "x"}}
        self.assertIsNone(D.normalize("UserPromptSubmit", {"prompt": "/clear"}))
        self.assertIsNone(D.normalize("UserPromptSubmit", {"prompt": "ok"}))
        self.assertIsNone(D.normalize("UserPromptSubmit", {"prompt": None}))
        self.assertIsNone(D.normalize("PostToolUseFailure", {**fail, "error": ""}))
        self.assertIsNone(D.normalize("PostToolUseFailure", {**fail, "error": "Exit code 1\nboom", "is_interrupt": True}))
        self.assertIsNone(D.normalize("PostToolUse", {"tool_name": "Read", "tool_input": {"file_path": "/p/a.py"}}))
        self.assertIsNone(D.normalize("SessionStart", {}))

    def test_normalize_failure_prompt_and_success(self):
        fail = D.normalize("PostToolUseFailure", {
            "tool_name": "Bash", "tool_input": {"command": "pytest tests/test_a.py -x"},
            "error": "Exit code 1\nAssertionError: 3 != 4"})
        self.assertEqual((fail["k"], fail["key"]), ("fail", "Bash:pytest tests/test_a.py"))
        self.assertIn("AssertionError", fail["err"])
        prompt = D.normalize("UserPromptSubmit", {"prompt": "no, we use alembic here, not raw sql"})
        self.assertEqual(prompt["k"], "prompt")
        ok = D.normalize("PostToolUse", {"tool_name": "Bash", "tool_input": {"command": "pytest -q"}})
        self.assertEqual((ok["k"], ok["key"]), ("ok", "Bash:pytest -q"))

    def test_normalize_edit_paths_are_project_relative(self):
        ev = D.normalize("PostToolUse", {"tool_name": "Edit", "cwd": "/home/me/proj",
                                         "tool_input": {"file_path": "/home/me/proj/src/a.py"}})
        self.assertEqual(ev, {"k": "edit", "key": "src/a.py"})

    def test_normalize_tolerates_malformed_payloads(self):
        for bad in ({}, {"tool_name": 5}, {"tool_name": "Bash", "tool_input": "x", "error": 3}):
            for event in ("PostToolUse", "PostToolUseFailure", "UserPromptSubmit"):
                D.normalize(event, bad)

    def test_window_bounded_and_oldest_evicted(self):
        w: list = []
        for i in range(20):
            w = D.push(w, {"k": "ok", "key": "Bash:%d" % i})
        self.assertEqual(len(w), D.WINDOW)
        self.assertEqual(w[0]["key"], "Bash:12")

    def test_signature_ignores_numbers_and_paths(self):
        a = D.signature({"k": "fail", "err": "AssertionError: 3 != 4 in /tmp/x/a.py"})
        b = D.signature({"k": "fail", "err": "AssertionError: 9 != 10 in /var/y/b.py"})
        self.assertEqual(a, b)

    def test_eligible_applies_dedupe_cooldown_and_cap(self):
        fresh = {"fired": [], "nudges": 0, "cooldown_until": 0}
        self.assertTrue(D.eligible("s", dict(fresh), now=0))
        self.assertFalse(D.eligible("s", {**fresh, "fired": ["s"], "nudges": 1}, now=0))
        self.assertFalse(D.eligible("t", {**fresh, "nudges": 1, "cooldown_until": 100}, now=50))
        self.assertTrue(D.eligible("t", {**fresh, "nudges": 1, "cooldown_until": 100}, now=150))
        self.assertFalse(D.eligible("t", {**fresh, "nudges": D.MAX_NUDGES}, now=0))

    def test_mark_fired_records_signature_and_cooldown(self):
        st = {"fired": [], "nudges": 0, "cooldown_until": 0}
        D.mark_fired(st, "s", now=1000)
        self.assertEqual((st["fired"], st["nudges"], st["cooldown_until"]), (["s"], 1, 1000 + D.COOLDOWN_S))

    def test_body_sends_only_compact_window(self):
        window = [{"k": "fail", "key": "Bash:pytest", "err": "x" * 200}] * D.WINDOW
        body = D.build_body("jev-1.13", window, "fail")
        self.assertLess(len(json.dumps(body)), 4000)
        self.assertEqual(list(body["questions"]), ["worthy"])
        self.assertEqual(body["questions"]["worthy"]["type"], "noul")
        self.assertEqual(body["state"]["trigger"], "fail")

    def test_nudge_names_the_skill_and_leaves_authorship_to_claude(self):
        text = D.nudge_text("fail", 5)
        self.assertIn("`lessons` skill", text)
        self.assertIn("routine", text)
        self.assertNotIn("invoke", text.lower())


KEY = "sk-or-v1-" + "ab12" * 16


def fail_payload(cmd="pytest tests/test_a.py", err="Exit code 1\nAssertionError: 3 != 4", sid="s1"):
    return {"session_id": sid, "tool_name": "Bash", "tool_input": {"command": cmd}, "error": err}


class FakeTransport:
    def __init__(self, *scores, error=None):
        self.scores, self.error, self.bodies, self.keys = list(scores), error, [], []

    def __call__(self, provider, key, body):
        self.bodies.append(body)
        self.keys.append(key)
        if self.error:
            raise D.JevError(self.error)
        return self.scores.pop(0) if len(self.scores) > 1 else self.scores[0]


class IoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "proj"
        self.proj.mkdir()
        self.state_dir = Path(self._tmp.name) / "state"
        self.env = {"OPENROUTER_API_KEY": KEY}
        self.now = 1_000_000.0

    def run_hook(self, event, payload, transport, *, env=None, now=None, provider="openrouter"):
        return D.run(event, payload, provider, env=self.env if env is None else env,
                     project_dir=self.proj, state_dir=self.state_dir,
                     now=self.now if now is None else now, transport=transport)

    def seen(self, out):
        return out["hookSpecificOutput"]["additionalContext"] if out else ""

    # --- credentials -----------------------------------------------------------
    def test_no_key_means_no_call_and_no_output(self):
        t = FakeTransport(0.9)
        self.assertIsNone(self.run_hook("PostToolUseFailure", fail_payload(), t, env={}))
        self.assertEqual(t.bodies, [])

    def test_key_from_project_dotenv_and_env_wins(self):
        (self.proj / ".env").write_text("# c\nOTHER=1\r\nexport OPENROUTER_API_KEY='from-dotenv'\r\n")
        self.assertEqual(D.find_key("openrouter", {}, self.proj), "from-dotenv")
        self.assertEqual(D.find_key("openrouter", {"OPENROUTER_API_KEY": "from-env"}, self.proj), "from-env")
        self.assertIsNone(D.find_key("typesafe", {}, self.proj))

    def test_dotenv_double_quotes_and_duplicates(self):
        (self.proj / ".env").write_text('OPENROUTER_API_KEY="first"\nOPENROUTER_API_KEY=second\n')
        self.assertEqual(D.find_key("openrouter", {}, self.proj), "second")

    # --- detection -------------------------------------------------------------
    def test_below_threshold_is_silent_above_nudges_once(self):
        t = FakeTransport(0.3)
        self.assertIsNone(self.run_hook("PostToolUseFailure", fail_payload(), t))
        self.assertEqual(len(t.bodies), 1)
        t = FakeTransport(0.8)
        out = self.run_hook("PostToolUseFailure", fail_payload(cmd="pytest b", err="Exit code 1\nKeyError: 'tenant_id'"), t)
        self.assertIn("`lessons` skill", self.seen(out))
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUseFailure")
        again = self.run_hook("PostToolUseFailure", fail_payload(cmd="pytest b", err="Exit code 1\nKeyError: 'tenant_id'"), t,
                              now=self.now + 10_000)
        self.assertIsNone(again)

    def test_success_and_edit_events_are_recorded_without_a_call(self):
        t = FakeTransport(0.99)
        ok = {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "pytest -q"}}
        self.assertIsNone(self.run_hook("PostToolUse", ok, t))
        self.assertEqual(t.bodies, [])

    def test_window_in_request_includes_earlier_events_and_is_bounded(self):
        t = FakeTransport(0.1)
        for i in range(12):
            self.run_hook("PostToolUse", {"session_id": "s1", "tool_name": "Edit",
                                          "tool_input": {"file_path": "f%d.py" % i}}, t)
        self.run_hook("PostToolUseFailure", fail_payload(), t)
        events = t.bodies[0]["state"]["events"]
        self.assertEqual(len(events), D.WINDOW)
        self.assertEqual(events[0], {"k": "edit", "key": "f5.py"})
        self.assertEqual(events[-1]["k"], "fail")

    def test_user_prompt_triggers_a_call_and_can_nudge(self):
        t = FakeTransport(0.9)
        out = self.run_hook("UserPromptSubmit", {"session_id": "s1", "prompt": "no, I told you, alembic only"}, t)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertEqual(len(t.bodies), 1)

    def test_nudge_cap_and_call_cap(self):
        t = FakeTransport(0.9)
        nudges = 0
        for i in range(6):
            out = self.run_hook("PostToolUseFailure", fail_payload(err="Exit code 1\nerror kind %s" % ("abcdef"[i] * 3)), t,
                                now=self.now + i * 10_000)
            nudges += bool(out)
        self.assertEqual(nudges, D.MAX_NUDGES)
        t2 = FakeTransport(0.1)
        for i in range(D.MAX_CALLS + 5):
            self.run_hook("PostToolUseFailure", fail_payload(sid="s2", err="Exit code 1\n%s" % ("x" * i)), t2)
        self.assertEqual(len(t2.bodies), D.MAX_CALLS)

    def test_calls_that_cannot_nudge_do_not_spend_the_budget(self):
        t = FakeTransport(0.9)
        same = fail_payload(err="Exit code 1\nthe same failure")
        for i in range(D.MAX_CALLS):
            self.run_hook("PostToolUseFailure", same, t, now=self.now + i)
        self.assertEqual(len(t.bodies), 1)
        later = self.run_hook("PostToolUseFailure", fail_payload(err="Exit code 1\na different problem"), t,
                              now=self.now + D.COOLDOWN_S + 60)
        self.assertIn("`lessons` skill", self.seen(later))
        self.assertEqual(len(t.bodies), 2)

    def test_events_during_cooldown_are_still_recorded_for_the_next_call(self):
        t = FakeTransport(0.9)
        self.run_hook("PostToolUseFailure", fail_payload(err="Exit code 1\nfirst"), t, now=self.now)
        self.run_hook("PostToolUseFailure", fail_payload(err="Exit code 1\nsecond"), t, now=self.now + 5)
        self.assertEqual(len(t.bodies), 1)
        self.run_hook("PostToolUseFailure", fail_payload(err="Exit code 1\nthird"), t, now=self.now + D.COOLDOWN_S + 1)
        errs = [e.get("err", "") for e in t.bodies[1]["state"]["events"]]
        self.assertTrue(any("second" in e for e in errs))

    # --- privacy ---------------------------------------------------------------
    def test_structured_and_quoted_credentials_never_reach_state_or_request(self):
        secrets = ("demo-secret-42", "secret with spaces", "hunter2-hunter2")
        cases = (
            ("curl -d '{\"password\": \"demo-secret-42\"}' https://x", "Exit code 1\nboom"),
            ("python app.py", "Exit code 1\nAPI_KEY = demo-secret-42 rejected"),
            ("PASSWORD='secret with spaces' ./run.sh", "Exit code 1\nboom"),
            ("deploy", 'Exit code 1\n{"client_secret":"hunter2-hunter2","ok":false}'),
        )
        t = FakeTransport(0.1)
        for i, (cmd, err) in enumerate(cases):
            self.run_hook("PostToolUseFailure", fail_payload(cmd=cmd, err=err, sid="sx"), t, now=self.now + i)
        self.run_hook("UserPromptSubmit", {"session_id": "sx", "prompt": "my token: demo-secret-42 and PASSWORD=\"secret with spaces\""}, t)
        stored = "".join(f.read_text() for f in self.state_dir.glob("*.json"))
        for secret in secrets:
            self.assertNotIn(secret, stored)
            self.assertNotIn(secret, json.dumps(t.bodies))

    def test_redaction_keeps_ordinary_error_text_readable(self):
        out = D.redact("KeyError: 'tenant_id' while loading monkeypatch fixtures; keyboard interrupt", 200)
        self.assertEqual(out, "KeyError: 'tenant_id' while loading monkeypatch fixtures; keyboard interrupt")

    def test_the_actual_key_never_leaves_even_if_it_appears_in_a_command(self):
        t = FakeTransport(0.1)
        self.run_hook("PostToolUseFailure", fail_payload(cmd="echo " + KEY, err="Exit code 1\nbad " + KEY), t)
        self.assertNotIn(KEY, json.dumps(t.bodies))

    def test_inline_secrets_in_commands_are_redacted_in_state_and_request(self):
        t = FakeTransport(0.1)
        cmd = "OPENROUTER_API_KEY=abcd-1234-efgh-5678-ijkl python x.py"
        self.run_hook("PostToolUseFailure", fail_payload(cmd=cmd, err="Exit code 1\nboom"), t)
        stored = "".join(f.read_text() for f in self.state_dir.glob("*.json"))
        self.assertNotIn("abcd-1234", stored)
        self.assertNotIn("abcd-1234", json.dumps(t.bodies))

    # --- failure model ---------------------------------------------------------
    def test_unwritable_state_dir_means_inactive_not_unbounded_calls(self):
        blocker = Path(self._tmp.name) / "blocker"
        blocker.write_text("a file where the state dir should be")
        self.state_dir = blocker / "state"
        t = FakeTransport(0.9)
        for i in range(5):
            self.assertIsNone(self.run_hook("PostToolUseFailure", fail_payload(err="Exit code 1\ne%d" % i), t))
        self.assertEqual(t.bodies, [])

    def test_a_hook_killed_mid_call_still_counts_toward_the_pause(self):
        class Killed(Exception):
            pass

        def killed(provider, key, body):
            raise Killed()

        for i in range(3):
            with self.assertRaises(Killed):
                self.run_hook("PostToolUseFailure", fail_payload(err="Exit code 1\nk%d" % i), killed)
        t = FakeTransport(0.9)
        self.assertIsNone(self.run_hook("PostToolUseFailure", fail_payload(err="Exit code 1\nafter"), t,
                                         now=self.now + D.STALE_S))
        self.assertEqual(t.bodies, [])

    def test_save_failure_leaves_no_temp_file_behind(self):
        path = self.state_dir / "x.json"
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                D.save_state(path, D.new_state())
        self.assertEqual(list(self.state_dir.glob("*.tmp")), [])

    def test_credit_or_auth_failure_warns_once_per_session_then_pauses_silently(self):
        for kind in ("credit", "auth"):
            with self.subTest(kind=kind):
                self.state_dir = Path(self._tmp.name) / ("state-" + kind)
                t = FakeTransport(error=kind)
                out = self.run_hook("PostToolUseFailure", fail_payload(), t)
                text = self.seen(out)
                self.assertIn("paused", text)
                self.assertIn("lessons loop itself is unaffected", text)
                self.assertNotIn(KEY, text)
                again = self.run_hook("PostToolUseFailure", fail_payload(err="Exit code 1\nother"), t)
                self.assertIsNone(again)
                self.assertEqual(len(t.bodies), 1)
                next_session = self.run_hook("PostToolUseFailure", fail_payload(sid="s9", err="Exit code 1\nthird"), t)
                self.assertIn("paused", self.seen(next_session))

    def test_transient_and_malformed_failures_are_silent_and_pause_after_three(self):
        for kind in ("transient", "malformed"):
            with self.subTest(kind=kind):
                self.state_dir = Path(self._tmp.name) / ("st-" + kind)
                t = FakeTransport(error=kind)
                for i in range(6):
                    out = self.run_hook("PostToolUseFailure", fail_payload(err="Exit code 1\ne%d" % i), t)
                    self.assertIsNone(out)
                self.assertEqual(len(t.bodies), 3)
                resumed = self.run_hook("PostToolUseFailure", fail_payload(err="Exit code 1\nlater"), t,
                                        now=self.now + D.PAUSE_S + 1)
                self.assertIsNone(resumed)
                self.assertEqual(len(t.bodies), 4)

    # --- state -----------------------------------------------------------------
    def test_corrupt_stale_and_mismatched_state_start_fresh(self):
        path = self.state_dir / "s1.json"
        self.state_dir.mkdir(parents=True)
        path.write_text("{not json")
        self.assertEqual(D.load_state(path, now=self.now)["window"], [])
        path.write_text(json.dumps({"v": 99, "window": [{"k": "ok"}]}))
        self.assertEqual(D.load_state(path, now=self.now)["window"], [])
        D.save_state(path, {**D.new_state(), "window": [{"k": "ok", "key": "x"}]})
        self.assertEqual(len(D.load_state(path, now=self.now)["window"]), 1)
        stale = self.now + D.STATE_TTL_S + 5
        os.utime(path, (self.now, self.now))
        self.assertEqual(D.load_state(path, now=stale)["window"], [])

    def test_state_file_is_private_and_holds_no_key(self):
        t = FakeTransport(0.1)
        self.run_hook("PostToolUseFailure", fail_payload(err="Exit code 1\n" + KEY), t)
        files = list(self.state_dir.glob("*.json"))
        self.assertTrue(files)
        for f in files:
            self.assertEqual(f.stat().st_mode & 0o077, 0)
            self.assertNotIn(KEY, f.read_text())

    def test_concurrent_writers_never_leave_invalid_json(self):
        path = self.state_dir / "race.json"
        self.state_dir.mkdir(parents=True)

        def writer(n):
            for i in range(100):
                D.save_state(path, {**D.new_state(), "nudges": n * 1000 + i})

        threads = [threading.Thread(target=writer, args=(n,)) for n in (1, 2)]
        [x.start() for x in threads]
        [x.join() for x in threads]
        self.assertIn("nudges", json.loads(path.read_text()))


class _Handler(http.server.BaseHTTPRequestHandler):
    status, payload, delay, seen, location, gets = 200, {}, 0.0, [], None, []

    def do_GET(self):
        type(self).gets.append(self.path)
        self.send_response(204)
        self.end_headers()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append((self.path, self.headers.get("Authorization"), self.headers.get("Content-Type"), body))
        time.sleep(type(self).delay)
        raw = json.dumps(type(self).payload).encode()
        self.send_response(type(self).status)
        if type(self).location:
            self.send_header("Location", type(self).location)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


class WireTests(unittest.TestCase):
    """call_jev against a real local socket: the request shape and every error class."""

    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:%d/api/v1/systemone" % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _Handler.status, _Handler.payload, _Handler.delay, _Handler.seen, _Handler.gets = (
            200, {"answers": {"worthy": {"type": "noul", "noul": 0.73}}}, 0.0, [], [])
        patcher = mock.patch.dict(D.PROVIDERS, {"openrouter": (self.url, "jev-1.13", "OPENROUTER_API_KEY")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, **kw):
        return D.call_jev("openrouter", KEY, D.build_body("jev-1.13", [{"k": "ok", "key": "x"}], "fail"), **kw)

    def test_request_shape_and_score(self):
        self.assertAlmostEqual(self.call(), 0.73)
        path, auth, ctype, body = _Handler.seen[0]
        self.assertEqual((path, auth, ctype), ("/api/v1/systemone", "Bearer " + KEY, "application/json"))
        self.assertEqual(body["model"], "jev-1.13")
        self.assertEqual(list(body["questions"]), ["worthy"])

    def test_error_classes(self):
        for status, kind in ((401, "auth"), (402, "credit"), (429, "transient"), (529, "transient"), (500, "transient")):
            with self.subTest(status=status):
                _Handler.status = status
                with self.assertRaises(D.JevError) as cm:
                    self.call()
                self.assertEqual(cm.exception.kind, kind)
                self.assertNotIn(KEY, str(cm.exception))

    def test_malformed_responses(self):
        for payload in ({}, {"answers": {}}, {"answers": {"worthy": {"noul": "high"}}}, {"answers": {"worthy": {"noul": 7}}}, [1]):
            with self.subTest(payload=payload):
                _Handler.payload = payload
                with self.assertRaises(D.JevError) as cm:
                    self.call()
                self.assertEqual(cm.exception.kind, "malformed")

    def test_redirects_are_never_followed_so_the_key_cannot_travel(self):
        _Handler.status, _Handler.location = 302, "/elsewhere"
        self.addCleanup(setattr, _Handler, "location", None)
        with self.assertRaises(D.JevError) as cm:
            self.call()
        self.assertEqual(cm.exception.kind, "transient")
        self.assertEqual(_Handler.gets, [])

    def test_unclassified_transport_errors_are_mapped_not_leaked(self):
        def incomplete(request, timeout):
            raise http.client.IncompleteRead(b"x")

        def bad_header(request, timeout):
            raise UnicodeEncodeError("latin-1", "\u2026", 0, 1, "bad key")

        for opener, kind in ((incomplete, "transient"), (bad_header, "auth")):
            with self.subTest(kind=kind):
                with self.assertRaises(D.JevError) as cm:
                    self.call(opener=opener)
                self.assertEqual(cm.exception.kind, kind)

    def test_timeout_and_unreachable_are_transient(self):
        _Handler.delay = 0.5
        with self.assertRaises(D.JevError) as cm:
            self.call(timeout=0.1)
        self.assertEqual(cm.exception.kind, "transient")
        with mock.patch.dict(D.PROVIDERS, {"openrouter": ("http://127.0.0.1:1/x", "m", "OPENROUTER_API_KEY")}):
            with self.assertRaises(D.JevError) as cm:
                self.call(timeout=0.5)
        self.assertEqual(cm.exception.kind, "transient")


class MainTests(unittest.TestCase):
    """The script as Claude Code runs it: stdin JSON in, stdout JSON or nothing, exit 0."""

    def run_main(self, stdin, argv=("lesson_detect.py", "openrouter"), env=None):
        import io, contextlib
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(stdin)), mock.patch("sys.argv", list(argv)), \
                mock.patch.dict(os.environ, env or {}, clear=False), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = D.main()
        return rc, out.getvalue(), err.getvalue()

    def test_garbage_stdin_unknown_provider_and_missing_args_exit_zero_silently(self):
        for stdin, argv in (("not json", None), ("", None), ("[]", None), ("{}", ("x.py",)), ("{}", ("x.py", "nope"))):
            rc, out, err = self.run_main(stdin, argv or ("x.py", "openrouter"))
            self.assertEqual((rc, out), (0, ""))

    def test_any_internal_error_exits_zero_silently(self):
        with mock.patch.object(D, "run", side_effect=RuntimeError("boom " + KEY)):
            rc, out, err = self.run_main(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "x" * 30}))
        self.assertEqual((rc, out), (0, ""))
        self.assertNotIn(KEY, err)

    def test_emits_hook_json_on_a_nudge(self):
        nudge = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "hi"}}
        with mock.patch.object(D, "run", return_value=nudge):
            rc, out, _ = self.run_main(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "x" * 30}))
        self.assertEqual((rc, json.loads(out)), (0, nudge))


if __name__ == "__main__":
    unittest.main()
