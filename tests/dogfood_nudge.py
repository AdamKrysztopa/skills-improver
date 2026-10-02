#!/usr/bin/env python3
"""Does Claude Code act on a "Possible lesson" nudge? Measured with real headless sessions.

Not part of the unit suite: it spends API credit. It seeds a throwaway project with the lessons
loop, registers a UserPromptSubmit hook that emits a fixed nudge (no Jev call), runs
`claude -p` on a scenario, and records whether Claude invoked the `lessons` skill and whether a
queue entry was written.

    python3 tests/dogfood_nudge.py --wording current --runs 3
    python3 tests/dogfood_nudge.py --wording baseline --runs 3      # the v1.3.0 wording

Scenarios: `recurring` says in the prompt that the mistake is a repeat (so it is confounded: the skill's
own description fires), `subtle` carries no such cue and isolates the nudge, `routine` is a typo that
should not be captured. `--wording none` is the no-nudge control.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "plugins/skill-improver/skills/skill-improver"

BASELINE = (
    "Possible lesson: after your last prompt, Jev scored the last {n} events as lesson-worthy "
    "(Jev only detects; it does not write lessons). If this is durable and would recur, "
    "invoke the `lessons` skill now — What happened / Generalises to / Candidate home — "
    "then carry on. If it is routine, ignore this."
)

SCENARIOS = {
    "recurring": (
        "Third time I'm correcting you on this: jobs/nightly.py keys its cache on the path alone, so "
        "after the input file changed the nightly report reused stale data again. The earlier fixes "
        "only cleared the cache by hand. Please make the cache key include the file's mtime."),
    "subtle": (
        "jobs/nightly.py keeps serving stale data after the input file changes. Could you make the "
        "cache key include the file's mtime?"),
    "routine": "There's a typo in jobs/nightly.py: the comment says 'teh' instead of 'the'. Please fix it.",
}


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def nudge(wording: str) -> str:
    if wording == "none":
        return ""
    if wording == "baseline":
        return BASELINE.format(n=6)
    return load("lesson_detect", SKILL / "assets/lessons-loop/hooks/lesson_detect.py").nudge_text("prompt", 6)


def build_project(root: Path, text: str) -> None:
    subprocess.run([sys.executable, str(SKILL / "scripts/seed_lessons.py"), "--seed-from-session",
                    "--root", str(root)], check=True, capture_output=True)
    (root / "jobs").mkdir()
    (root / "jobs/nightly.py").write_text(
        "# teh nightly report\nimport json\nCACHE = {}\n\n"
        "def load(path):\n    if path not in CACHE:\n        CACHE[path] = json.load(open(path))\n    return CACHE[path]\n")
    emitter = root / ".claude/hooks/fixed_nudge.py"
    if text:
        emitter.write_text("import json, sys\nsys.stdin.read()\nprint(json.dumps({'hookSpecificOutput': "
                           "{'hookEventName': 'UserPromptSubmit', 'additionalContext': %r}}))\n" % text)
    if not text:
        return
    settings = json.loads((root / ".claude/settings.json").read_text())
    settings["hooks"]["UserPromptSubmit"] = [{"hooks": [{"type": "command",
                                                         "command": f"python3 {emitter}"}]}]
    (root / ".claude/settings.json").write_text(json.dumps(settings))


def run_once(wording: str, scenario: str, model: str, budget: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_project(root, nudge(wording))
        pristine = (root / "docs/lessons.md").read_text()
        proc = subprocess.run(
            ["claude", "-p", SCENARIOS[scenario], "--model", model, "--setting-sources", "project",
             "--strict-mcp-config", "--permission-mode", "acceptEdits", "--max-budget-usd", budget,
             "--output-format", "stream-json", "--verbose"],
            cwd=root, capture_output=True, text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)})
        invoked = False
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            message = event.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Skill" \
                        and "lessons" in json.dumps(block.get("input")):
                    invoked = True
        return {"invoked_skill": invoked, "queue_entry_written": (root / "docs/lessons.md").read_text() != pristine}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--wording", choices=("current", "baseline", "none"), default="current")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--model", default="sonnet")
    p.add_argument("--budget", default="0.50", help="USD cap per run")
    p.add_argument("--scenario", choices=(*SCENARIOS, "all"), default="all")
    args = p.parse_args()
    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    for name in names:
        results = [run_once(args.wording, name, args.model, args.budget) for _ in range(args.runs)]
        print(f"{args.wording:9} {name:10} invoked `lessons`: {sum(r['invoked_skill'] for r in results)}/{args.runs}"
              f"   queue entry written: {sum(r['queue_entry_written'] for r in results)}/{args.runs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
