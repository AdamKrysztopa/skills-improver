#!/usr/bin/env python3
"""Prove the lessons loop's machinery actually fires.

A checker only ever run against a clean archive has been verified to print
nothing. So every detector here is shown firing against a fixture that seeds the
defect on purpose, and shown staying quiet against one that does not.

    python3 tests/test_lessons_loop.py

No dependencies. Exits non-zero on the first failure.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# --- installer-templated layout (relative to this file) ---------------------
ROOT_UP = ".."
CHECKER_REL = "scripts/lessons_graph.py"
HOOK_REL = "hooks/session_start_lessons.py"
SKILLS_REL = "skills"
TEMPLATE_ARCHIVE_REL = "docs/LESSONS-ARCHIVE.md"
TEMPLATE_QUEUE_REL = "docs/lessons.md"
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
LOOP = (HERE / ROOT_UP).resolve()
CHECKER = LOOP / CHECKER_REL
HOOK = LOOP / HOOK_REL
ARCHIVE_TEMPLATE = LOOP / TEMPLATE_ARCHIVE_REL
QUEUE_TEMPLATE = LOOP / TEMPLATE_QUEUE_REL
SKILLS = LOOP / SKILLS_REL


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The synthetic projects below are laid out the way the *installed* scripts
# expect, read off the scripts themselves — so this suite keeps working on a
# host project that keeps its scripts in `bin/` or its docs in `documentation/`.
_lg = _load(CHECKER, "_lessons_graph_under_test")
_hk = _load(HOOK, "_session_start_hook_under_test")
ARCHIVE_IN_PROJECT = _lg.ARCHIVE_REL
QUEUE_IN_PROJECT = _lg.QUEUE_REL
SCRIPTS_IN_PROJECT = _hk.SCRIPTS_REL
HOOK_IN_PROJECT = HOOK_REL

failures: list[str] = []
passed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed
    if condition:
        passed += 1
        print(f"  ok   {name}")
    else:
        failures.append(f"{name}: {detail}")
        print(f"  FAIL {name}  {detail}")


def run_checker(archive: Path, queue: Path | None = None):
    env = {**os.environ, "LESSONS_ARCHIVE": str(archive)}
    if queue:
        env["LESSONS_QUEUE"] = str(queue)
    return subprocess.run([sys.executable, str(CHECKER)], env=env,
                          capture_output=True, text=True)


def make_project(archive_text: str | None, queue_text: str | None) -> Path:
    """Assemble a throwaway project laid out the way the installer lays one out."""
    root = Path(tempfile.mkdtemp(prefix="lessons-loop-"))

    def place(rel: str, src: Path) -> Path:
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)
        return dest

    place(f"{SCRIPTS_IN_PROJECT}/lessons_graph.py", CHECKER)
    place(HOOK_IN_PROJECT, HOOK)
    for rel, text in ((ARCHIVE_IN_PROJECT, archive_text), (QUEUE_IN_PROJECT, queue_text)):
        if text is None:
            continue
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    return root


def run_hook(root: Path):
    proc = subprocess.run(
        [sys.executable, str(root / HOOK_IN_PROJECT)],
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)},
        capture_output=True, text=True, cwd=str(root),
    )
    context = ""
    if proc.stdout.strip():
        context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    return proc, context


# --------------------------------------------------------------------------
print("\nCHECKER — fires on a seeded defect")

broken = run_checker(HERE / "fixture-broken.md")
out = broken.stdout

check("exits non-zero on a broken archive", broken.returncode == 1,
      f"returncode={broken.returncode}")
check("reports the oscillation", "OSCILLATION" in out)
check("prints the full reversal chain",
      "L4.1 reverses L3.2 reverses L1.2" in out,
      f"chain line missing from:\n{out}")
check("calls the oscillation a stop, not an entry", "stop, not an entry" in out)
check("reports the recurrence with a count",
      "RECURRENCE" in out and "re-learned 2x" in out)
check("names both re-learners", "L2.1, L3.1" in out)
check("prints the MOVE IT verdict", "MOVE IT" in out)
check("gives the reason for MOVE IT",
      "wrong artefact" in out and "`moves`" in out)
check("reports the typo edge as dangling",
      "DANGLING" in out and "L9.9" in out)
check("does not parse the fenced example rows",
      "L0.1" not in out and "L0.2" not in out,
      "the archive's own format example was read as data")

print("\nCHECKER — quiet on a clean archive")

clean = run_checker(HERE / "fixture-clean.md")
check("exits zero on a clean archive", clean.returncode == 0,
      f"returncode={clean.returncode}\n{clean.stdout}")
check("reports no oscillation or recurrence",
      "OSCILLATION" not in clean.stdout and "RECURRENCE" not in clean.stdout)
check("counts only the real entries (not the fenced example)",
      "4 entries" in clean.stdout, clean.stdout)

print("\nCHECKER — the shipped template parses as empty, not as its own example")

template = run_checker(ARCHIVE_TEMPLATE)
check("template archive exits zero", template.returncode == 0)
check("template archive yields no entries",
      "holds no entries" in template.stdout, template.stdout)

print("\nCHECKER — a deleted archive breaks nothing")

missing = run_checker(HERE / "does-not-exist.md")
check("missing archive exits zero", missing.returncode == 0)
check("missing archive reports cleanly, not as a finding",
      "no archive" in missing.stdout and "OSCILLATION" not in missing.stdout)

# --------------------------------------------------------------------------
print("\nHOOK — injects applied rules in full, queue as titles")

root = make_project(
    (HERE / "fixture-clean.md").read_text(encoding="utf-8"),
    "# Lessons — queue\n\n## Open\n\n### first open thing\n\n- **What happened:** x\n\n"
    "### second open thing\n\n- **What happened:** y\n",
)
proc, ctx = run_hook(root)

check("hook exits zero", proc.returncode == 0, proc.stderr)
check("emits SessionStart additionalContext", bool(ctx), proc.stdout)
check("injects an applied rule in full",
      "Every documented check has a mechanical counterpart or is deleted." in ctx)
check("names the rule's home", ".claude/hooks/check_docs.py" in ctx)
check("excludes declined lines from injection",
      "declined" not in ctx.lower(),
      "a decline is a decision, not a rule")
check("excludes a rule that was moved elsewhere",
      "L1.1" not in ctx, "the stale pre-move row was injected too")
check("prints queue entries as titles plus a count",
      "2 lesson(s) waiting" in ctx and "first open thing" in ctx)
check("does not paste full queue entries",
      "What happened" not in ctx,
      "queue bodies leaked into the session-start block")
check("points at the capture skill", "`lessons` skill" in ctx)

print("\nHOOK — does not report the archive's own format example as data")

root = make_project(
    ARCHIVE_TEMPLATE.read_text(encoding="utf-8"),
    QUEUE_TEMPLATE.read_text(encoding="utf-8"),
)
proc, ctx = run_hook(root)
check("hook exits zero on the shipped templates", proc.returncode == 0, proc.stderr)
check("no rule from the fenced worked example is injected",
      "L4.1" not in ctx and "L4.2" not in ctx,
      f"documentation was injected as doctrine:\n{ctx}")
check("no rule from the edge-vocabulary table is injected",
      "narrows or widens" not in ctx, ctx)

print("\nHOOK — degrades silently, never invents")

root = make_project(None, None)
proc, ctx = run_hook(root)
check("no ledger at all: exits zero", proc.returncode == 0, proc.stderr)
check("no ledger at all: emits nothing", proc.stdout.strip() == "",
      f"invented output: {proc.stdout!r}")

root = make_project("\x00\x01 not markdown \xff" * 200, "")
proc, ctx = run_hook(root)
check("unreadable archive: exits zero", proc.returncode == 0, proc.stderr)
check("unreadable archive: emits nothing rather than something reassuring",
      proc.stdout.strip() == "", f"invented output: {proc.stdout!r}")

root = make_project((HERE / "fixture-clean.md").read_text(encoding="utf-8"), None)
(root / SCRIPTS_IN_PROJECT / "lessons_graph.py").unlink()
proc, ctx = run_hook(root)
check("missing checker: exits zero", proc.returncode == 0, proc.stderr)
check("missing checker: emits nothing", proc.stdout.strip() == "")

print("\nHOOK — an empty queue produces no queue block")

root = make_project((HERE / "fixture-clean.md").read_text(encoding="utf-8"),
                    "# Lessons — queue\n\n## Open\n\n<!-- empty -->\n")
proc, ctx = run_hook(root)
check("empty queue: no waiting-lessons line", "waiting to be drained" not in ctx, ctx)
check("empty queue: rules still injected", "mechanical counterpart" in ctx)

print("\nHOOK — surfaces a graph finding at session start")

root = make_project((HERE / "fixture-broken.md").read_text(encoding="utf-8"), None)
proc, ctx = run_hook(root)
check("broken archive: hook still exits zero", proc.returncode == 0, proc.stderr)
check("broken archive: finding is surfaced, not silently carried",
      "finding(s)" in ctx, ctx)

# --------------------------------------------------------------------------
print("\nSKILLS — descriptions trigger on symptoms, not on a phrase")

for skill, symptoms in (
    ("lessons", ("prose rather than code", "falsified", "contradicts",
                 "running the software")),
    ("implement-ll", ("checkpoint", "release", "queue", "drain")),
):
    text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
    desc = text.split("---")[1]
    check(f"{skill}: description does not lean on the phrase 'lessons learned'",
          "lessons learned" not in desc.lower())
    for s in symptoms:
        check(f"{skill}: triggers on '{s}'", s in desc.lower())

lessons_body = (SKILLS / "lessons" / "SKILL.md").read_text(encoding="utf-8")
check("lessons: states it writes and stops",
      "does not apply the lesson" in lessons_body.lower())
check("lessons: states what is not a lesson",
      "What is not a lesson" in lessons_body)

drain_body = (SKILLS / "implement-ll" / "SKILL.md").read_text(encoding="utf-8")
check("implement-ll: graph check comes before reading the queue",
      drain_body.index("Graph check first") < drain_body.index("Read the whole queue"))
check("implement-ll: hook is the first rung of the ladder",
      drain_body.index("**A hook**") < drain_body.index("**CLAUDE.md**"))
check("implement-ll: carries the fitness check",
      "would a rule already in the archive have caught" in drain_body)

# --------------------------------------------------------------------------
print(f"\n{passed} passed, {len(failures)} failed")
if failures:
    print("\nFAILURES:")
    for f in failures:
        print(f"  - {f}")
sys.exit(1 if failures else 0)
