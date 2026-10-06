#!/usr/bin/env python3
"""Hook: Jev-assisted lesson detection (optional).

Watches a small, redacted window of recent events and asks Jev one question: does
this look like a lesson worth capturing? Jev only scores. On a high score the hook
tells Claude to run the `lessons` skill; Claude writes the entry, and the queue,
drain and archive take over unchanged.

Registered in .claude/settings.local.json by `seed_lessons.py --jev-provider`.
Fails open: every error path exits 0 and prints nothing a session could trip on.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

PROVIDERS = {
    "openrouter": ("https://openrouter.ai/api/v1/systemone", "jev-1.13", "OPENROUTER_API_KEY"),
    "typesafe": ("https://api.typesafe.ai/v1/systemone", "jev-1.13.0", "TYPESAFE_API_KEY"),
}

WORTHY_MIN = 0.6
WINDOW = 8
COOLDOWN_S = 600
MAX_NUDGES = 3
MAX_CALLS = 30
TIMEOUT_S = 2.0
STATE_TTL_S = 86400
PAUSE_S = 1800
STATE_VERSION = 1

QUESTION = (
    "Does this event history show a mistake, wrong assumption, drifted document or missing "
    "safeguard whose cause would likely recur in future work on this project unless it is "
    "written down as a lesson? Strong signals: the same failure surviving several fix attempts, "
    "the user correcting the same thing more than once, a documented claim or safeguard that "
    "does not do what it says. Routine iteration, typos, expected failing tests and one-off "
    "command errors are not lessons."
)

_SECRET = re.compile(
    r"""(?ix)
      (?:bearer|basic)\s+\S+
    | ["']?\b[\w-]*(?:key|token|secret|passw(?:or)?d|pwd)["']?\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s,;&]+)
    | \b[A-Za-z0-9+/]{32,}={0,2}\b
    """
)
_EDIT_TOOLS = ("Edit", "Write", "MultiEdit")


def redact(text: str, limit: int) -> str:
    """Strip secret-shaped values, then truncate.

    Args:
        text: Raw text from a tool call or prompt.
        limit: Maximum characters kept after redaction.

    Returns:
        The redacted, truncated text.
    """
    return _SECRET.sub("[redacted]", text)[:limit]


def _relative(path: str, cwd: object) -> str:
    if isinstance(cwd, str) and cwd and path.startswith(cwd.rstrip("/") + "/"):
        return path[len(cwd.rstrip("/")) + 1:]
    return path


def _tool_key(tool: str, tool_input: dict, cwd: object) -> tuple[str, str]:
    command = tool_input.get("command")
    if tool == "Bash" and isinstance(command, str):
        return redact("Bash:" + " ".join(command.split()[:2]), 100), command
    path = tool_input.get("file_path")
    target = _relative(path, cwd) if isinstance(path, str) else ""
    return redact(f"{tool}:{target}", 200), target


def normalize(event: str, payload: dict) -> dict | None:
    """Reduce a hook payload to the compact event Jev sees, or None to skip it.

    Args:
        event: Hook event name.
        payload: The hook's stdin JSON.

    Returns:
        An event dict, or None for noise: interrupts, empty errors, short prompts and
        slash commands, and tools that carry no signal.
    """
    if event == "UserPromptSubmit":
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or len(prompt.strip()) < 12 or prompt.lstrip().startswith("/"):
            return None
        return {"k": "prompt", "text": redact(prompt.strip(), 300)}

    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool, str) or not isinstance(tool_input, dict):
        return None
    key, target = _tool_key(tool, tool_input, payload.get("cwd"))

    if event == "PostToolUseFailure":
        error = payload.get("error")
        if not isinstance(error, str) or not error.strip() or payload.get("is_interrupt"):
            return None
        return {"k": "fail", "key": key, "cmd": redact(target, 100), "err": redact(error, 200)}
    if event == "PostToolUse" and tool == "Bash":
        return {"k": "ok", "key": key, "cmd": redact(target, 100)}
    if event == "PostToolUse" and tool in _EDIT_TOOLS:
        return {"k": "edit", "key": key.split(":", 1)[1]}
    return None


def push(window: list[dict], ev: dict) -> list[dict]:
    """Append an event, keeping only the newest WINDOW events."""
    return (window + [ev])[-WINDOW:]


def signature(ev: dict) -> str:
    """A stable fingerprint for 'the same problem again': digits and paths stripped."""
    basis = ev.get("err") or ev.get("text") or ev.get("key") or ""
    basis = re.sub(r"0x[0-9a-f]+|\d+", "#", basis.lower())
    return re.sub(r"(/[\w.\-]+)+", "<path>", basis)[:80]


def build_body(model: str, window: list[dict], trigger: str) -> dict:
    """The Jev request body: one compact window, one yes/no question."""
    return {
        "model": model,
        "state": {"trigger": trigger, "events": window},
        "questions": {"worthy": {"type": "noul", "instructions": QUESTION}},
    }


def eligible(sig: str, state: dict, *, now: float) -> bool:
    """True when a nudge for this problem could still be emitted: not a repeat, not cooling, under the cap."""
    return sig not in state["fired"] and state["nudges"] < MAX_NUDGES and now >= state["cooldown_until"]


def mark_fired(state: dict, sig: str, *, now: float) -> None:
    """Record a nudge so it is not repeated and the cooldown starts."""
    state["fired"] = state["fired"] + [sig]
    state["nudges"] += 1
    state["cooldown_until"] = now + COOLDOWN_S


def nudge_text(trigger: str, n_events: int) -> str:
    """The text Claude sees. It names the skill; Claude writes the lesson."""
    what = "a tool failure" if trigger == "fail" else "your last prompt"
    return (
        f"Possible lesson: after {what}, Jev scored the last {n_events} events as lesson-worthy "
        "(Jev only detects; it does not write lessons). If this is durable and would recur, "
        "invoke the `lessons` skill now — What happened / Generalises to / Candidate home — "
        "then carry on. If it is routine, ignore this."
    )


# --- credentials --------------------------------------------------------------

def find_key(provider: str, env: dict, project_dir: Path) -> str | None:
    """Find the provider's API key: the process environment first, then project `.env`.

    Args:
        provider: A key of PROVIDERS.
        env: The process environment.
        project_dir: The project root, where `.env` may live.

    Returns:
        The key, or None. Only the provider's own variable is ever read from `.env`.
    """
    name = PROVIDERS[provider][2]
    if env.get(name):
        return env[name]
    try:
        lines = (Path(project_dir) / ".env").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    found = None
    for line in lines:
        line = line.strip()
        if line.startswith("export "):
            line = line[7:]
        var, _, value = line.partition("=")
        if var.strip() == name:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            found = value or None
    return found


# --- Jev client ---------------------------------------------------------------

class JevError(Exception):
    """A failed Jev call. `kind` is auth, credit, transient or malformed; never carries the key."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


_HTTP_KIND = {401: "auth", 402: "credit"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would carry the Authorization header to another host; treat it as an error."""

    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def call_jev(provider: str, key: str, body: dict, *, timeout: float = TIMEOUT_S,
             opener=None) -> float:
    """POST one request to Jev and return the `worthy` probability.

    Args:
        provider: A key of PROVIDERS.
        key: The API key.
        body: A request body from build_body.
        timeout: Seconds before giving up.
        opener: Injected for tests; defaults to a urllib opener that never follows redirects.

    Returns:
        The probability in [0, 1] that the window is lesson-worthy.

    Raises:
        JevError: On any failure, classified by `kind`.
    """
    request = urllib.request.Request(
        PROVIDERS[provider][0], json.dumps(body).encode("utf-8"),
        {"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
    try:
        with (opener or _OPENER.open)(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        exc.close()
        raise JevError(_HTTP_KIND.get(exc.code, "transient")) from None
    except UnicodeEncodeError:
        raise JevError("auth") from None
    except (OSError, http.client.HTTPException):
        raise JevError("transient") from None
    try:
        score = json.loads(raw)["answers"]["worthy"]["noul"]
    except (ValueError, KeyError, TypeError):
        raise JevError("malformed") from None
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
        raise JevError("malformed")
    return float(score)


# --- per-session state --------------------------------------------------------

def new_state() -> dict:
    """An empty per-session state."""
    return {"v": STATE_VERSION, "window": [], "fired": [], "nudges": 0, "cooldown_until": 0,
            "calls": 0, "errs": 0, "paused_until": 0, "blocked": False}


def load_state(path: Path, *, now: float) -> dict:
    """Load a session's state; missing, stale, corrupt or foreign-version files give a fresh one."""
    try:
        if now - path.stat().st_mtime > STATE_TTL_S:
            return new_state()
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return new_state()
    if not isinstance(data, dict) or data.get("v") != STATE_VERSION:
        return new_state()
    return {**new_state(), **data}


def save_state(path: Path, state: dict) -> None:
    """Write state atomically with owner-only permissions. A lost update costs one nudge at most."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name("%s.%d.%d.tmp" % (path.name, os.getpid(), threading.get_ident()))
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        os.replace(str(tmp), str(path))
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def default_state_dir() -> Path:
    """Per-user temp directory: never in the repo, reaped by the OS."""
    return Path(tempfile.gettempdir()) / ("skill-improver-jev-%d" % getattr(os, "getuid", lambda: 0)())


def _sweep(state_dir: Path, now: float) -> None:
    for old in state_dir.glob("*.json"):
        try:
            if now - old.stat().st_mtime > STATE_TTL_S:
                old.unlink()
        except OSError:
            pass


# --- the hook -----------------------------------------------------------------

def _context(event: str, text: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def _on_error(exc: JevError, event: str, provider: str, state: dict, now: float) -> dict | None:
    if exc.kind in ("credit", "auth"):
        state["blocked"] = True
        why = "has no credit left" if exc.kind == "credit" else "rejected the API key"
        return _context(event, (
            f"Jev-assisted lesson detection is paused: {provider} {why}. The lessons loop itself is "
            "unaffected. Tell the user; they can top up or replace the key, or turn the feature off by "
            "re-running /skill-improver:seed-lessons and choosing Off."))
    return None


def _scrub(ev: dict, key: str) -> dict:
    return json.loads(json.dumps(ev).replace(key, "[redacted]")) if len(key) >= 8 else ev


def _save(path: Path, state: dict) -> bool:
    try:
        save_state(path, state)
    except OSError:
        return False
    return True


def _judge(event: str, ev: dict, state: dict, provider: str, key: str, path: Path,
           now: float, transport) -> dict | None:
    if state["errs"] >= 3:
        state["paused_until"], state["errs"] = now + PAUSE_S, 0
    if state["blocked"] or now < state["paused_until"] or state["calls"] >= MAX_CALLS:
        return None
    sig = signature(ev)
    if not eligible(sig, state, now=now):
        return None
    state["calls"] += 1
    state["errs"] += 1  # cleared on success, so a hook killed mid-call still counts toward the pause
    if not _save(path, state):
        return None
    body = build_body(PROVIDERS[provider][1], state["window"], ev["k"])
    try:
        score = transport(provider, key, body)
    except JevError as exc:
        return _on_error(exc, event, provider, state, now)
    state["errs"] = 0
    if score < WORTHY_MIN:
        return None
    mark_fired(state, sig, now=now)
    return _context(event, nudge_text(ev["k"], len(state["window"])))


def run(event: str, payload: dict, provider: str, *, env: dict, project_dir: Path,
        state_dir: Path, now: float, transport=call_jev) -> dict | None:
    """Handle one hook event.

    Args:
        event: Hook event name.
        payload: The hook's stdin JSON.
        provider: A key of PROVIDERS.
        env: The process environment.
        project_dir: The project root.
        state_dir: Where per-session state lives.
        now: Current time in seconds.
        transport: Injected Jev call; defaults to call_jev.

    Returns:
        The hook's JSON output, or None when there is nothing to say. Without writable state
        the caps cannot be enforced, so the detector stays inactive rather than call unbounded.
    """
    key = find_key(provider, env, project_dir)
    ev = normalize(event, payload) if key else None
    if ev is None:
        return None
    ev = _scrub(ev, key)
    session = re.sub(r"[^\w.-]", "_", str(payload.get("session_id") or "nosession"))[:64]
    path = state_dir / (session + ".json")
    state = load_state(path, now=now)
    state["window"] = push(state["window"], ev)
    if not _save(path, state):
        return None
    out = None
    if ev["k"] in ("fail", "prompt"):
        out = _judge(event, ev, state, provider, key, path, now, transport)
        _save(path, state)
    _sweep(state_dir, now)
    return out


def main() -> int:
    """Entry point: `lesson_detect.py <provider>` with the hook payload on stdin. Always exits 0."""
    try:
        provider = sys.argv[1] if len(sys.argv) > 1 else ""
        if provider not in PROVIDERS:
            return 0
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ".")
        out = run(payload.get("hook_event_name"), payload, provider, env=dict(os.environ),
                  project_dir=project, state_dir=default_state_dir(), now=time.time())
    except Exception:  # fail open: a detector must never break the session it watches
        return 0
    if out:
        json.dump(out, sys.stdout)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
