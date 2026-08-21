#!/usr/bin/env python3
"""Install the self-improving lessons loop into a host project.

Six artefacts — a queue, an archive, a SessionStart hook, a graph checker, and
two skills — adapted to the host project's directory conventions.

    python3 seed_lessons.py --dry-run            # print the plan, change nothing
    python3 seed_lessons.py --seed               # install, files empty + a worked example
    python3 seed_lessons.py --seed-from-session  # install with an empty queue, to be
                                                 # populated from the session transcript
    python3 seed_lessons.py --upgrade            # refresh the machinery, preserve the ledger

The queue and the archive are DATA. They are created when absent and never
overwritten, not even by --upgrade: a half-migrated loop that silently drops the
archive is the worst possible outcome of this feature.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "lessons-loop"

DOC_DIR_CANDIDATES = ("docs", "doc", "documentation")
SCRIPT_DIR_CANDIDATES = ("scripts", "bin", "tools")
TEST_DIR_CANDIDATES = ("tests", "test")

DOCS_INDEX_CANDIDATES = (
    "docs/README.md", "docs/index.md", "docs/SUMMARY.md",
    "mkdocs.yml", "README.md",
)
CHECKPOINT_HINTS = (
    "definition of done", "before you commit", "before committing", "checklist",
    "pull request", "contributing", "when you are done", "acceptance",
)

HOOK_COMMENT = (
    "Injects the applied lessons archive into every session. A process improvement "
    "you have to remember to apply is one that decays, so nothing in this loop "
    "depends on anyone opening a file."
)


# --- layout -----------------------------------------------------------------

class Layout:
    def __init__(self, root: Path, docs: str, scripts: str, hooks: str,
                 skills: str, tests: str):
        self.root = root
        self.docs = docs
        self.scripts = scripts
        self.hooks = hooks
        self.skills = skills
        self.tests = tests

    @property
    def archive(self) -> str:
        return f"{self.docs}/LESSONS-ARCHIVE.md"

    @property
    def queue(self) -> str:
        return f"{self.docs}/lessons.md"

    @property
    def checker(self) -> str:
        return f"{self.scripts}/lessons_graph.py"

    @property
    def hook(self) -> str:
        return f"{self.hooks}/session_start_lessons.py"


def first_existing(root: Path, candidates, default: str) -> str:
    for c in candidates:
        if (root / c).is_dir():
            return c
    return default


def detect_layout(args) -> Layout:
    root = Path(args.root).resolve()
    docs = args.docs_dir or first_existing(root, DOC_DIR_CANDIDATES, "docs")
    scripts = args.scripts_dir or first_existing(root, SCRIPT_DIR_CANDIDATES, "scripts")
    tests_base = args.tests_dir or first_existing(root, TEST_DIR_CANDIDATES, "")
    tests = f"{tests_base}/lessons_loop" if tests_base else f"{scripts}/lessons_loop_tests"
    return Layout(root, docs, scripts, ".claude/hooks", ".claude/skills", tests)


# --- retargeting ------------------------------------------------------------

def retarget(text: str, lay: Layout, *, constants: dict | None = None) -> str:
    """Rewrite the asset's default paths to the host project's conventions."""
    for old, new in (
        ("docs/LESSONS-ARCHIVE.md", lay.archive),
        ("docs/lessons.md", lay.queue),
        ("scripts/lessons_graph.py", lay.checker),
        ("hooks/session_start_lessons.py", lay.hook),
    ):
        if old != new:
            text = text.replace(old, new)
    for name, value in (constants or {}).items():
        text = re.sub(rf'^{name} = ".*"$', f'{name} = "{value}"', text, flags=re.M)
    return text


def planned_files(lay: Layout, empty_queue: bool) -> list[dict]:
    """Every file the loop installs, with its kind. `data` is never overwritten."""
    tests_root_up = os.path.relpath(lay.root, lay.root / lay.tests)
    return [
        {"dest": lay.queue, "src": "docs/lessons.md", "kind": "data",
         "role": "the queue — empty is the healthy state",
         "transform": (lambda t: strip_example(t)) if empty_queue else None},
        {"dest": lay.archive, "src": "docs/LESSONS-ARCHIVE.md", "kind": "data",
         "role": "the graph — one dated section per drain, newest first"},
        {"dest": lay.checker, "src": "scripts/lessons_graph.py", "kind": "code",
         "role": "the mechanical check — oscillation, recurrence, dangling edges",
         "constants": {"ARCHIVE_REL": lay.archive, "QUEUE_REL": lay.queue}},
        {"dest": lay.hook, "src": "hooks/session_start_lessons.py", "kind": "code",
         "role": "the part that removes remembering",
         "constants": {"SCRIPTS_REL": lay.scripts, "ARCHIVE_REL": lay.archive,
                       "QUEUE_REL": lay.queue}},
        {"dest": f"{lay.skills}/lessons/SKILL.md", "src": "skills/lessons/SKILL.md",
         "kind": "code", "role": "capture — writes one entry and stops"},
        {"dest": f"{lay.skills}/implement-ll/SKILL.md",
         "src": "skills/implement-ll/SKILL.md", "kind": "code",
         "role": "drain — group, route, apply, verify, archive"},
        {"dest": f"{lay.tests}/test_lessons_loop.py", "src": "tests/test_lessons_loop.py",
         "kind": "code", "role": "proves the checker and hook actually fire",
         "constants": {"ROOT_UP": tests_root_up, "CHECKER_REL": lay.checker,
                       "HOOK_REL": lay.hook, "SKILLS_REL": lay.skills,
                       "TEMPLATE_ARCHIVE_REL": f"{lay.tests}/template-archive.md",
                       "TEMPLATE_QUEUE_REL": f"{lay.tests}/template-queue.md"}},
        {"dest": f"{lay.tests}/fixture-broken.md", "src": "tests/fixture-broken.md",
         "kind": "code", "role": "seeded oscillation + 2x recurrence + typo edge"},
        {"dest": f"{lay.tests}/fixture-clean.md", "src": "tests/fixture-clean.md",
         "kind": "code", "role": "a healthy archive the checker must stay quiet about"},
        {"dest": f"{lay.tests}/template-archive.md", "src": "docs/LESSONS-ARCHIVE.md",
         "kind": "code", "role": "pristine archive — guards the fenced-example defence"},
        {"dest": f"{lay.tests}/template-queue.md", "src": "docs/lessons.md",
         "kind": "code", "role": "pristine queue"},
    ]


def strip_example(text: str) -> str:
    """Drop the worked example from the queue, leaving `## Open` genuinely empty."""
    head, sep, _ = text.partition("### Example —")
    if not sep:
        return text
    return head.rstrip() + "\n"


# --- settings.json ----------------------------------------------------------

def hook_command(lay: Layout) -> str:
    return f'python3 "$CLAUDE_PROJECT_DIR/{lay.hook}"'


def settings_action(lay: Layout) -> tuple[str, dict]:
    """Return (verdict, merged-settings) without writing anything."""
    path = lay.root / ".claude" / "settings.json"
    try:
        settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError) as exc:
        return (f"UNPARSEABLE ({exc}) — register the hook by hand", {})

    starts = settings.setdefault("hooks", {}).setdefault("SessionStart", [])
    for group in starts:
        for h in group.get("hooks", []):
            if "session_start_lessons.py" in str(h.get("command", "")):
                return ("already registered", settings)
    starts.append({
        "$comment": HOOK_COMMENT,
        "hooks": [{"type": "command", "command": hook_command(lay)}],
    })
    verb = "register SessionStart hook" if path.exists() else "create with SessionStart hook"
    return (verb, settings)


# --- wiring reconnaissance --------------------------------------------------

def wiring_candidates(lay: Layout) -> dict:
    root = lay.root
    out: dict[str, list[str]] = {"instructions": [], "docs_index": [],
                                 "checkpoints": [], "skills": []}
    for name in ("CLAUDE.md", "AGENTS.md", ".claude/CLAUDE.md", "CONTRIBUTING.md"):
        if (root / name).is_file():
            out["instructions"].append(name)
    for name in DOCS_INDEX_CANDIDATES:
        if (root / name).is_file():
            out["docs_index"].append(name)
    for name in out["instructions"]:
        try:
            body = (root / name).read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        hits = sorted({h for h in CHECKPOINT_HINTS if h in body})
        if hits:
            out["checkpoints"].append(f"{name}: mentions {', '.join(hits)}")
    skills_dir = root / lay.skills
    if skills_dir.is_dir():
        out["skills"] = sorted(p.name for p in skills_dir.iterdir() if p.is_dir())
    return out


# --- install ----------------------------------------------------------------

def install(lay: Layout, files: list[dict], upgrade: bool) -> list[str]:
    written = []
    for f in files:
        dest = lay.root / f["dest"]
        exists = dest.exists()
        if exists and (f["kind"] == "data" or not upgrade):
            continue
        text = (ASSETS / f["src"]).read_text(encoding="utf-8")
        if f.get("transform"):
            text = f["transform"](text)
        text = retarget(text, lay, constants=f.get("constants"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        if exists:
            shutil.copy2(dest, dest.with_suffix(dest.suffix + ".bak"))
        dest.write_text(text, encoding="utf-8")
        if f["src"].endswith(".py"):
            dest.chmod(0o755)
        written.append(f["dest"] + (" (was backed up to .bak)" if exists else ""))
    return written


def verify(lay: Layout) -> int:
    """Run the machinery and show what it prints. A hook is code, not a claim."""
    root = lay.root
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    rc = 0

    print("\n--- the checker, against the seeded-defect fixture "
          "(must exit 1 and print a chain) ---")
    proc = subprocess.run(
        [sys.executable, str(root / lay.checker)],
        env={**env, "LESSONS_ARCHIVE": str(root / lay.tests / "fixture-broken.md")},
        capture_output=True, text=True)
    print(proc.stdout.rstrip() or proc.stderr.rstrip())
    print(f"[exit {proc.returncode}]")
    if proc.returncode != 1:
        print("!! the checker did not fire on a deliberately broken archive")
        rc = 1

    print("\n--- the checker, against this project's real archive ---")
    proc = subprocess.run([sys.executable, str(root / lay.checker)],
                          env=env, capture_output=True, text=True)
    print(proc.stdout.rstrip() or proc.stderr.rstrip())
    print(f"[exit {proc.returncode}]")

    print("\n--- the SessionStart hook, triggered (this is what lands in every session) ---")
    proc = subprocess.run([sys.executable, str(root / lay.hook)],
                          env=env, capture_output=True, text=True, cwd=str(root))
    if proc.returncode != 0:
        print(f"!! hook exited {proc.returncode}; it must always exit 0")
        rc = 1
    if not proc.stdout.strip():
        print("(no output — the ledger is empty, which is correct for a fresh install)")
    else:
        try:
            ctx = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
            print(ctx)
        except (json.JSONDecodeError, KeyError) as exc:
            print(f"!! hook emitted something that is not SessionStart context: {exc}")
            print(proc.stdout)
            rc = 1

    print("\n--- the loop's own test suite ---")
    proc = subprocess.run([sys.executable, str(root / lay.tests / "test_lessons_loop.py")],
                          env=env, capture_output=True, text=True)
    tail = proc.stdout.rstrip().splitlines()
    print("\n".join(tail[-3:]) if tail else proc.stderr.rstrip())
    if proc.returncode != 0:
        print("\n".join(l for l in tail if l.strip().startswith("FAIL")))
        rc = 1
    return rc


# --- main -------------------------------------------------------------------

def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--seed", action="store_true",
                      help="install with the files empty and a worked example in each")
    mode.add_argument("--seed-from-session", action="store_true",
                      help="install with an empty queue, to be populated from the transcript")
    mode.add_argument("--upgrade", action="store_true",
                      help="refresh hook, checker, skills and tests; never touch the ledger")
    p.add_argument("--dry-run", action="store_true",
                   help="print what would be created and where it would wire in")
    p.add_argument("--root", default=".", help="the host project (default: cwd)")
    p.add_argument("--docs-dir", help="override the detected docs directory")
    p.add_argument("--scripts-dir", help="override the detected scripts directory")
    p.add_argument("--tests-dir", help="override the detected tests directory")
    args = p.parse_args(argv)

    if not (args.seed or args.seed_from_session or args.upgrade or args.dry_run):
        p.error("pick one of --seed, --seed-from-session, --upgrade, or --dry-run")

    lay = detect_layout(args)
    if not lay.root.is_dir():
        print(f"error: {lay.root} is not a directory", file=sys.stderr)
        return 1

    files = planned_files(lay, empty_queue=args.seed_from_session)
    present = [f for f in files if (lay.root / f["dest"]).exists()]
    installed_already = any(f["kind"] == "code" for f in present)

    print(f"project root : {lay.root}")
    print(f"layout       : docs={lay.docs}/  scripts={lay.scripts}/  "
          f"hooks={lay.hooks}/  skills={lay.skills}/  tests={lay.tests}/")
    print()

    # --- the plan -----------------------------------------------------------
    print("PLAN")
    for f in files:
        exists = (lay.root / f["dest"]).exists()
        if not exists:
            verdict = "create"
        elif f["kind"] == "data":
            verdict = "PRESERVE (data — never overwritten)"
        elif args.upgrade:
            verdict = "upgrade (.bak kept)"
        else:
            verdict = "exists — needs --upgrade"
        print(f"  {verdict:34} {f['dest']}")
        print(f"  {'':34} └─ {f['role']}")
    verdict, merged = settings_action(lay)
    print(f"  {verdict:34} {lay.hooks.rsplit('/', 1)[0]}/settings.json")
    print(f"  {'':34} └─ {hook_command(lay)}")

    # --- upgrade gate -------------------------------------------------------
    if installed_already and not args.upgrade and not args.dry_run:
        print("\nSTOP — an installation is already here.")
        for f in present:
            print(f"  found: {f['dest']}")
        print("\nNothing was written. Re-run with --upgrade to refresh the machinery")
        print("(hook, checker, skills, tests — each backed up to .bak first).")
        print("The queue and the archive are preserved either way: a half-migrated")
        print("loop that silently drops the archive is the worst outcome here.")
        return 2

    if args.dry_run:
        report_wiring(lay)
        print("\n--dry-run: nothing was written.")
        return 0

    # --- write --------------------------------------------------------------
    written = install(lay, files, upgrade=args.upgrade)
    print("\nWROTE")
    for w in written:
        print(f"  {w}")
    if not written:
        print("  (nothing — every file was already present and preserved)")

    if merged and verdict not in ("already registered",) and not verdict.startswith("UNPARSEABLE"):
        settings_path = lay.root / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        if settings_path.exists():
            shutil.copy2(settings_path, settings_path.with_suffix(".json.bak"))
        settings_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        print(f"  .claude/settings.json ({verdict})")
    elif verdict.startswith("UNPARSEABLE"):
        print(f"  !! .claude/settings.json {verdict}")

    rc = verify(lay)
    report_wiring(lay)

    if args.seed_from_session:
        print("""
NEXT — populate the queue from this session
  The loop is installed but carrying no evidence, which is what makes a first
  drain theoretical rather than worth running. Re-read this session's transcript
  and write one queue entry per mistake that was actually caught in it:
  a check that turned out to be prose, a claim from intuition falsified by a
  measurement, a recommendation that contradicted settled text, a defect found
  by running the software rather than by its tests.
  Each entry needs `What happened` (with path:line and how it was caught),
  `Generalises to` (one sentence, as a rule — this is the filter), and
  `Candidate home` (a suggestion, not a decision). Do not implement any of them:
  routing happens at the drain, where they can be grouped.""")

    print("\nDone." if rc == 0 else "\nDone, with failures above.")
    return rc


def report_wiring(lay: Layout) -> None:
    c = wiring_candidates(lay)
    print("""
WIRE IT IN — the two skills must be called from checkpoints that already fire.
Leaving them as things to remember is the exact failure this design exists to
prevent. Found in this project:""")
    print(f"  instructions files : {', '.join(c['instructions']) or 'NONE — create one line in a CLAUDE.md contribution section'}")
    print(f"  docs index         : {', '.join(c['docs_index']) or 'none found — register the two documents wherever docs are listed'}")
    print(f"  checkpoint text    : {'; '.join(c['checkpoints']) or 'no definition-of-done wording found — create exactly one'}")
    print(f"  existing skills    : {', '.join(c['skills']) or 'none'}")
    print("""  → Add `lessons` to the project's definition of done, and `implement-ll`
    to its "decision is settled" moment. Amend an existing checkpoint; do not
    invent a second ceremony beside one that already exists.""")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
