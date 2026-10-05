from __future__ import annotations

import importlib.util
import json
import os
import re
import time
import urllib.request
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / "plugins/skill-improver/skills/skill-improver/assets/lessons-loop/hooks/lesson_detect.py"
_spec = importlib.util.spec_from_file_location("lesson_detect", HOOK)
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)

HAIKU_MODEL = "claude-haiku-4-5"
CORRECTION = re.compile(r"\b(again|still|already told|third time|not what i|wrong|i said)\b", re.I)


def heuristic(rec: dict) -> dict:
    t0 = time.perf_counter()
    sigs = [D.signature(e) for e in rec["window"] if e["k"] == "fail"]
    repeated = any(sigs.count(s) >= 2 for s in set(sigs))
    corrections = sum(1 for e in rec["window"] if e["k"] == "prompt" and CORRECTION.search(e.get("text", "")))
    return {"decision": repeated or corrections >= 1, "score": None,
            "latency_ms": (time.perf_counter() - t0) * 1000, "bytes_out": 0}


def jev(rec: dict, provider: str = "openrouter") -> dict:
    key = os.environ[D.PROVIDERS[provider][2]]
    body = D.build_body(D.PROVIDERS[provider][1], rec["window"], rec["trigger"])
    t0 = time.perf_counter()
    score = D.call_jev(provider, key, body, timeout=10.0)
    return {"decision": score >= D.WORTHY_MIN, "score": score,
            "latency_ms": (time.perf_counter() - t0) * 1000, "bytes_out": len(json.dumps(body))}


def _user_text(rec: dict) -> str:
    return (D.QUESTION + "\n\nEvents (oldest first):\n" + json.dumps(rec["window"], indent=1)
            + '\n\nAnswer with JSON {"worthy": true|false}.')


def claude_haiku(rec: dict) -> dict:
    """What a Claude Code prompt hook does by default: the hook input + a prompt, judged by Haiku."""
    import anthropic

    client = anthropic.Anthropic()
    text = _user_text(rec)
    t0 = time.perf_counter()
    resp = client.messages.create(
        model=HAIKU_MODEL, max_tokens=256,
        messages=[{"role": "user", "content": text}],
        output_config={"format": {"type": "json_schema", "schema": {
            "type": "object", "properties": {"worthy": {"type": "boolean"}},
            "required": ["worthy"], "additionalProperties": False}}},
    )
    worthy = json.loads(next(b.text for b in resp.content if b.type == "text"))["worthy"]
    return {"decision": bool(worthy), "score": None,
            "latency_ms": (time.perf_counter() - t0) * 1000, "bytes_out": len(text)}


def openrouter_llm(rec: dict, model: str) -> dict:
    text = _user_text(rec)
    body = {"model": model, "messages": [{"role": "user", "content": text}],
            "response_format": {"type": "json_object"}, "max_tokens": 64}
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                                          "Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.load(r)
    worthy = json.loads(out["choices"][0]["message"]["content"]).get("worthy") is True
    return {"decision": worthy, "score": None,
            "latency_ms": (time.perf_counter() - t0) * 1000, "bytes_out": len(json.dumps(body))}
