#!/usr/bin/env python3
"""Install the self-improving lessons loop into a host project.

Six artefacts — a queue, an archive, a SessionStart hook, a graph checker, and
two skills — adapted to the host project's directory conventions. Optionally a
seventh: Jev-assisted lesson detection (see --jev-provider).

    python3 seed_lessons.py --dry-run            # print the plan, change nothing
    python3 seed_lessons.py --seed               # install, files empty + a worked example
    python3 seed_lessons.py --seed-from-session  # install with an empty queue, to be
                                                 # populated from the session transcript
    python3 seed_lessons.py --upgrade            # refresh the machinery, preserve the ledger
    python3 seed_lessons.py --seed --jev-provider openrouter   # + Jev-assisted detection

The queue and the archive are DATA. They are created when absent and never
overwritten, not even by --upgrade: a half-migrated loop that silently drops the
archive is the worst possible outcome of this feature.
"""

from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import os
import posixpath
import re
import stat
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

JEV_PROVIDERS = ("openrouter", "typesafe")
JEV_LABEL = {"openrouter": "OpenRouter", "typesafe": "TypeSafe (direct)"}
JEV_EVENTS = (("PostToolUse", "Bash|Edit|Write|MultiEdit"), ("PostToolUseFailure", None),
              ("UserPromptSubmit", None))
JEV_STATUS = {
    "credit": "key found, but the account has no credit — detection stays paused and warns once",
    "auth": "key found, but the provider rejected it — detection stays paused and warns once",
    "transient": "provider unreachable or erroring — detection will retry silently",
    "malformed": "unexpected response from the provider — detection will skip silently",
}
LOCAL_SETTINGS = ".claude/settings.local.json"
USER_CLAUDE_DIR = Path.home() / ".claude"

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
        self.recovered = False

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

    @property
    def detector(self) -> str:
        return f"{self.hooks}/lesson_detect.py"


def first_existing(root: Path, candidates, default: str) -> str:
    for c in candidates:
        if (root / c).is_dir():
            return c
    return default


class LayoutError(Exception):
    """The installed hook points somewhere the installer cannot reproduce."""


def contained(root: Path, rel: str, what: str) -> str:
    """`rel` as a normalised project-relative path; LayoutError if it lands outside `root`."""
    norm = posixpath.normpath(rel.replace("\\", "/"))
    target = (root / norm).resolve()
    if posixpath.isabs(norm) or not target.is_relative_to(root):
        raise LayoutError(
            f"{what} {rel!r} resolves to {target}, outside the project {root}. Nothing was written. "
            "Pass --docs-dir / --scripts-dir / --tests-dir with a directory inside the project.")
    return norm


def recover_layout(root: Path, args) -> dict:
    """Read an existing install's layout back from its own SessionStart hook.

    The hook carries the directories the installer chose. Re-detecting from the project's
    current directories instead would, once the project grows a `docs/` or `scripts/`, point
    the upgraded hook at an empty ledger and leave the real one orphaned.

    Returns:
        {} when no generated hook is installed; otherwise docs, scripts and (when found) tests.

    Raises:
        LayoutError: The hook's ledger paths are not ones this installer can write.
    """
    try:
        text = (root / ".claude/hooks/session_start_lessons.py").read_text(encoding="utf-8")
    except OSError:
        return {}
    consts = {n: re.search(rf'^{n} = "(.*)"$', text, re.M) for n in ("SCRIPTS_REL", "ARCHIVE_REL", "QUEUE_REL")}
    if not all(consts.values()):
        return {}
    scripts, archive, queue = (consts[n].group(1) for n in ("SCRIPTS_REL", "ARCHIVE_REL", "QUEUE_REL"))
    docs = posixpath.dirname(queue)
    if not args.docs_dir and (posixpath.dirname(archive) != docs or posixpath.basename(queue) != "lessons.md"
                              or posixpath.basename(archive) != "LESSONS-ARCHIVE.md"):
        raise LayoutError(
            f"the installed hook reads its queue from {queue} and its archive from {archive}, which "
            "this installer cannot reproduce. Nothing was written. Pass --docs-dir to say where "
            "lessons.md and LESSONS-ARCHIVE.md live, or reconcile the hook by hand.")
    found = {"docs": docs or ".", "scripts": scripts}
    for candidate in (*(f"{t}/lessons_loop" for t in TEST_DIR_CANDIDATES), f"{scripts}/lessons_loop_tests"):
        if (root / candidate / "test_lessons_loop.py").is_file():
            found["tests"] = candidate
            break
    return found


def detect_layout(args) -> Layout:
    root = Path(args.root).resolve()
    known = recover_layout(root, args) if root.is_dir() else {}
    docs = args.docs_dir or known.get("docs") or first_existing(root, DOC_DIR_CANDIDATES, "docs")
    scripts = args.scripts_dir or known.get("scripts") or first_existing(root, SCRIPT_DIR_CANDIDATES, "scripts")
    if args.tests_dir:
        tests = f"{args.tests_dir}/lessons_loop"
    elif "tests" in known:
        tests = known["tests"]
    else:
        tests_base = first_existing(root, TEST_DIR_CANDIDATES, "")
        tests = f"{tests_base}/lessons_loop" if tests_base else f"{scripts}/lessons_loop_tests"
    docs = contained(root, docs, "docs directory")
    scripts = contained(root, scripts, "scripts directory")
    tests = contained(root, tests, "tests directory")
    lay = Layout(root, docs, scripts, ".claude/hooks", ".claude/skills", tests)
    lay.recovered = bool(known)
    return lay


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


def planned_files(lay: Layout, empty_queue: bool, *, with_jev: bool = False) -> list[dict]:
    """Every file the loop installs, with its kind. `data` is never overwritten."""
    tests_root_up = os.path.relpath(lay.root, lay.root / lay.tests)
    files = [
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
         "legacy": ["legacy/hooks/session_start_lessons.v1.3.1.py"],
         "couples": f"{lay.tests}/test_lessons_loop.py",
         "constants": {"SCRIPTS_REL": lay.scripts, "ARCHIVE_REL": lay.archive,
                       "QUEUE_REL": lay.queue}},
        {"dest": f"{lay.skills}/lessons/SKILL.md", "src": "skills/lessons/SKILL.md",
         "kind": "code", "role": "capture — writes one entry and stops",
         "legacy": ["legacy/skills/lessons/SKILL.v1.2.0.md"]},
        {"dest": f"{lay.skills}/implement-ll/SKILL.md",
         "src": "skills/implement-ll/SKILL.md", "kind": "code",
         "role": "drain — group, route, apply, verify, archive"},
        {"dest": f"{lay.tests}/test_lessons_loop.py", "src": "tests/test_lessons_loop.py",
         "kind": "code", "role": "proves the checker and hook actually fire",
         "legacy": ["legacy/tests/test_lessons_loop.v1.3.1.py"],
         "couples": lay.hook,
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
    if with_jev:
        files.append({"dest": lay.detector, "src": "hooks/lesson_detect.py", "kind": "code",
                      "role": "Jev-assisted detection — Jev scores, Claude still writes the lesson",
                      "legacy": ["legacy/hooks/lesson_detect.v1.3.0.py",
                                 "legacy/hooks/lesson_detect.v1.3.1.py"]})
    return files


def strip_example(text: str) -> str:
    """Drop the worked example from the queue, leaving `## Open` genuinely empty."""
    head, sep, _ = text.partition("### Example —")
    if not sep:
        return text
    return head.rstrip() + "\n"


# --- journal ----------------------------------------------------------------

class Journal:
    """Every file the installer touches goes through here, so a failed run can be undone exactly.

    A backup is only ever added, never overwritten: the first one holds the file as the user
    left it, and a later upgrade must not replace it with a machine-generated version.
    """

    def __init__(self):
        self._undo: list[tuple[Path, bytes | None, int, Path | None]] = []
        self._dirs: list[Path] = []

    def _backup_for(self, path: Path, prior: bytes) -> Path | None:
        n = 0
        while True:
            candidate = path.with_name(path.name + ".bak" + (f".{n}" if n else ""))
            if not candidate.exists():
                return candidate
            if candidate.read_bytes() == prior:
                return None
            n += 1

    def _mkdirs(self, directory: Path) -> None:
        missing = []
        while not directory.exists():
            missing.append(directory)
            directory = directory.parent
        for d in reversed(missing):
            d.mkdir()
            self._dirs.append(d)

    def write(self, path: Path, text: str, *, backup: bool = True, mode: int | None = None) -> None:
        prior = path.read_bytes() if path.exists() else None
        prior_mode = stat.S_IMODE(path.stat().st_mode) if prior is not None else 0o644
        self._mkdirs(path.parent)
        bak = self._backup_for(path, prior) if prior is not None and backup else None
        if bak:
            bak.write_bytes(prior)
        tmp = path.with_name(path.name + ".tmp")
        try:
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            tmp.chmod(mode if mode is not None else prior_mode)
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            if bak:
                bak.unlink(missing_ok=True)
            raise
        self._undo.append((path, prior, prior_mode, bak))

    def rollback(self) -> None:
        for path, prior, mode, bak in reversed(self._undo):
            if prior is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(prior)
                path.chmod(mode)
            if bak:
                bak.unlink(missing_ok=True)
        for directory in reversed(self._dirs):
            try:
                directory.rmdir()
            except OSError:
                pass
        self._undo, self._dirs = [], []


# --- settings.json ----------------------------------------------------------

def hook_command(lay: Layout) -> str:
    return f'python3 "$CLAUDE_PROJECT_DIR/{lay.hook}"'


def check_hooks_shape(settings: object) -> None:
    """Raise ValueError unless settings has the shape Claude Code documents for hooks."""
    if not isinstance(settings, dict):
        raise ValueError("top level is not a JSON object")
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" is not an object')
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            raise ValueError(f'"hooks.{event}" is not a list')
        for i, group in enumerate(groups):
            inner = group.get("hooks", []) if isinstance(group, dict) else None
            if not isinstance(inner, list) or not all(isinstance(h, dict) for h in inner):
                raise ValueError(f'"hooks.{event}[{i}]" is not a hook group')


def settings_action(lay: Layout) -> tuple[str, dict]:
    """Return (verdict, merged-settings) without writing anything."""
    path = lay.root / ".claude" / "settings.json"
    try:
        settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        check_hooks_shape(settings)
    except (OSError, ValueError) as exc:
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


def write_settings(path: Path, merged: dict, journal: Journal, *, private: bool = False) -> None:
    """Write a settings file through the journal.

    Settings that hold an `env` block may hold credentials, and a `.bak` beside them is an
    untracked copy that is one `git add .` from a commit — so those are not backed up.
    """
    journal.write(path, json.dumps(merged, indent=2) + "\n", backup=not private and "env" not in merged,
                  mode=0o600 if private and not path.exists() else None)


# --- Jev-assisted lesson detection -------------------------------------------

@functools.lru_cache(maxsize=1)
def load_detector():
    """The installed hook's own module, so provider names, key lookup and the client live once."""
    spec = importlib.util.spec_from_file_location("lesson_detect", ASSETS / "hooks" / "lesson_detect.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def settings_env(root: Path) -> dict:
    """The `env` blocks Claude Code exports to hooks: user, project, then personal project settings."""
    merged: dict = {}
    for path in (USER_CLAUDE_DIR / "settings.json", root / ".claude" / "settings.json", root / LOCAL_SETTINGS):
        try:
            block = json.loads(path.read_text(encoding="utf-8")).get("env", {})
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(block, dict):
            merged.update({k: v for k, v in block.items() if isinstance(v, str)})
    return merged


def find_jev_key(provider: str, root: Path) -> tuple[str | None, str]:
    """(key, where it was found). Mirrors what the hook will see at runtime."""
    det = load_detector()
    name = det.PROVIDERS[provider][2]
    from_settings = settings_env(root)
    env = {**from_settings, **{k: v for k, v in os.environ.items() if v}}
    source = "environment" if os.environ.get(name) else (
        "Claude Code settings" if from_settings.get(name) else ".env")
    return det.find_key(provider, env, root), source


def jev_probe(provider: str, key: str) -> None:
    """One minimal call: proves the key, the endpoint and the credit. Raises JevError."""
    det = load_detector()
    body = det.build_body(det.PROVIDERS[provider][1], [{"k": "ok", "key": "probe"}], "fail")
    det.call_jev(provider, key, body)


def jev_command(lay: Layout, provider: str) -> str:
    return f'python3 "$CLAUDE_PROJECT_DIR/{lay.detector}" {provider} || true'  # a missing script must never exit 2


def _ours(hook: dict) -> bool:
    return "lesson_detect.py" in str(hook.get("command", ""))


def _strip_detector(hooks: dict) -> None:
    for event in list(hooks):
        kept = []
        for group in hooks[event]:
            if any(_ours(h) for h in group.get("hooks", [])):
                group["hooks"] = [h for h in group["hooks"] if not _ours(h)]
                if not group["hooks"]:
                    continue
            kept.append(group)
        hooks[event] = kept
        if not kept:
            del hooks[event]


def _is_registered(hooks: dict, command: str) -> bool:
    for event, matcher in JEV_EVENTS:
        found = any(g.get("matcher") == matcher and any(h.get("command") == command for h in g.get("hooks", []))
                    for g in hooks.get(event, []))
        if not found:
            return False
    return True


def jev_settings_action(lay: Layout, provider: str) -> tuple[str, dict]:
    """Return (verdict, merged-settings) for .claude/settings.local.json, writing nothing.

    Opt-in lives in this personal, git-ignored file so that no commit can enable external
    calls for a teammate. `off` removes only this detector's entries.
    """
    path = lay.root / LOCAL_SETTINGS
    try:
        settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        check_hooks_shape(settings)
        hooks = settings.setdefault("hooks", {})
    except (OSError, ValueError) as exc:
        return (f"UNPARSEABLE ({exc}) — register the Jev hooks by hand", {})

    if provider != "off" and is_tracked(lay.root, LOCAL_SETTINGS):
        return ("REFUSED (tracked by git — a registration here would be shared with teammates; "
                "untrack the file or register by hand)", {})
    command = jev_command(lay, provider)
    if provider != "off" and _is_registered(hooks, command):
        return ("already registered", settings)
    had_any = any(_ours(h) for groups in hooks.values() for g in groups for h in g.get("hooks", []))
    _strip_detector(hooks)
    if provider == "off":
        if not hooks:
            del settings["hooks"]
        return ("remove Jev hooks" if had_any else "not registered", settings)
    for event, matcher in JEV_EVENTS:
        group = {"hooks": [{"type": "command", "command": command, "timeout": 5}]}
        if matcher:
            group = {"matcher": matcher, **group}
        hooks.setdefault(event, []).append(group)
    return (f"register Jev hooks ({provider})", settings)


def jev_state(lay: Layout) -> tuple[str, str | None]:
    """What this project's personal settings say about Jev, read from the artefacts alone.

    Returns:
        ("enabled", provider), ("off", None) when the detector script is installed but nothing
        registers it, or ("absent", None) — a project seeded before Jev existed, or one that
        never chose it. The last two are not told apart and need not be: neither is acted on.
    """
    try:
        hooks = json.loads((lay.root / LOCAL_SETTINGS).read_text(encoding="utf-8")).get("hooks", {})
        for groups in hooks.values():
            for group in groups:
                for hook in group.get("hooks", []):
                    found = re.search(r"lesson_detect\.py\"?\s+(\w+)", str(hook.get("command", "")))
                    if _ours(hook) and found and found.group(1) in JEV_PROVIDERS:
                        return ("enabled", found.group(1))
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return ("off", None) if (lay.root / lay.detector).exists() else ("absent", None)


def report_jev_state(lay: Layout) -> None:
    """The Jev status of an existing loop when the run was not asked to change it."""
    state, provider = jev_state(lay)
    label = "JEV-ASSISTED LESSON DETECTION"
    if state == "enabled":
        print(f"\n{label}: enabled ({provider}) — unchanged by this run.")
        print(f"  Health (run from the project root): python3 {lay.detector} --status --probe")
        return
    lead = ("installed but not registered (off)" if state == "off"
            else "not enabled — projects seeded before v1.3 have no Jev registration; that is their normal state")
    print(f"\n{label}: {lead}. Nothing is sent anywhere, and this run did not change that.")
    keys = []
    for name in JEV_PROVIDERS:
        key, source = find_jev_key(name, lay.root)
        keys.append(f"{name}: key " + (f"found ({source})" if key else "not found"))
    print(f"  Enable it explicitly with --jev-provider openrouter|typesafe ({'; '.join(keys)}).")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    except OSError:
        return None


def is_tracked(root: Path, rel: str) -> bool:
    proc = _git(root, "ls-files", "--error-unmatch", rel)
    return proc is not None and proc.returncode == 0


def ensure_local_exclude(root: Path, rel: str) -> None:
    """Keep `rel` out of commits via this clone's .git/info/exclude, unless git already ignores it.

    Claude Code only excludes settings.local.json when it writes the file itself; ours is written here.
    """
    proc = _git(root, "check-ignore", "-q", rel)
    if proc is None or proc.returncode != 1:
        return
    where = _git(root, "rev-parse", "--git-path", "info/exclude")
    if where is None or where.returncode != 0:
        return
    exclude = root / where.stdout.strip()
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open("a", encoding="utf-8") as handle:
        handle.write(rel + "\n")


def dotenv_unignored(root: Path) -> bool:
    """True when a project `.env` exists inside a git repo that does not ignore it."""
    if not (root / ".env").is_file():
        return False
    try:
        proc = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=root, capture_output=True)
    except OSError:
        return False
    return proc.returncode == 1


def report_jev(lay: Layout, provider: str, verdict: str, *, dry_run: bool) -> None:
    """The Jev report, or a plain statement that it could not be enabled."""
    if verdict.startswith(("UNPARSEABLE", "REFUSED")):
        if provider != "off":
            print("\nJev-assisted lesson detection is NOT enabled (see above). "
                  "The base lessons loop is installed and unaffected.")
        return
    jev_report(lay, provider, dry_run=dry_run)


def jev_report(lay: Layout, provider: str, *, dry_run: bool) -> None:
    """Say plainly what is and is not active. A Jev problem never changes the exit code."""
    if provider == "off":
        print("\nJEV-ASSISTED LESSON DETECTION: off (its hooks are unregistered; nothing is sent anywhere).")
        return
    det = load_detector()
    name = det.PROVIDERS[provider][2]
    key, source = find_jev_key(provider, lay.root)
    status = "skipped — no credential"
    if key and dry_run:
        status = "skipped (dry run)"
    elif key:
        try:
            jev_probe(provider, key)
            status = "OK"
        except det.JevError as exc:
            status = JEV_STATUS[exc.kind]
    rows = [
        ("Provider", JEV_LABEL[provider]),
        ("Credential", f"found ({source})" if key else
         f"missing — set {name} (shell profile, or a git-ignored .env in the project); "
         "detection stays inactive until it is found"),
        ("Connectivity", status),
        ("Registration", f"{LOCAL_SETTINGS} (personal, git-ignored by Claude Code)"),
        ("Health", f"python3 {lay.detector} --status --probe (run from the project root)"),
    ]
    print("\nJEV-ASSISTED LESSON DETECTION (optional — Jev scores a compact window; Claude writes the lesson)")
    for label, value in rows:
        print(f"  {label:<13}: {value}")
    if key and source == ".env" and dotenv_unignored(lay.root):
        print("  !! .env holds the key and is not git-ignored — add it to .gitignore.")
    print("Base lessons loop installed successfully — nothing above affects it.")


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

def render(lay: Layout, f: dict, src: str | None = None) -> str:
    text = (ASSETS / (src or f["src"])).read_text(encoding="utf-8")
    if f.get("transform"):
        text = f["transform"](text)
    return retarget(text, lay, constants=f.get("constants"))


def file_state(lay: Layout, f: dict) -> str:
    """What the installer would find at this destination.

    create | data | current | outdated (an earlier shipped version, safe to refresh) |
    customised (anything else: the project's own edit, which the drain makes on purpose).
    """
    dest = lay.root / f["dest"]
    if not dest.exists():
        return "create"
    if f["kind"] == "data":
        return "data"
    try:
        found = dest.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "customised"
    if found == render(lay, f):
        return "current"
    return "outdated" if any(found == render(lay, f, old) for old in f.get("legacy", ())) else "customised"


def hold_coupled(files: list[dict], states: dict[str, str]) -> dict[str, str]:
    """Mark an outdated file `held` when the file it is tested against carries the project's edits.

    The hook and its test assert each other's behaviour, so refreshing one beside a customised
    other makes the upgrade's own verification fail.
    """
    held = dict(states)
    for f in files:
        partner = f.get("couples")
        if states[f["dest"]] == "outdated" and partner and states.get(partner) == "customised":
            held[f["dest"]] = "held"
    return held


def install(lay: Layout, files: list[dict], upgrade: bool, journal: Journal,
            states: dict[str, str]) -> list[str]:
    """Write what is missing, and with --upgrade what is stale. Rendering finishes before the first write."""
    todo = [(f, render(lay, f)) for f in files if states[f["dest"]] == "create"
            or (upgrade and states[f["dest"]] == "outdated")]
    written = []
    for f, text in todo:
        dest = lay.root / f["dest"]
        existed = dest.exists()
        journal.write(dest, text, mode=0o755 if f["src"].endswith(".py") else None)
        written.append(f["dest"] + (" (previous version kept as .bak)" if existed else ""))
    return written


def verify(lay: Layout) -> int:
    """Run the machinery and show what it prints. A hook is code, not a claim."""
    root = lay.root
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root),
           "PYTHONDONTWRITEBYTECODE": "1"}
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
    p.add_argument("--jev-provider", choices=("off", *JEV_PROVIDERS),
                   help="enable Jev-assisted lesson detection through this provider, or `off` to "
                        "remove it; omitted = leave as is (a fresh install is off)")
    p.add_argument("--dry-run", action="store_true",
                   help="print what would be created and where it would wire in")
    p.add_argument("--root", default=".", help="the host project (default: cwd)")
    p.add_argument("--docs-dir", help="override the detected docs directory")
    p.add_argument("--scripts-dir", help="override the detected scripts directory")
    p.add_argument("--tests-dir", help="override the detected tests directory")
    args = p.parse_args(argv)

    if not (args.seed or args.seed_from_session or args.upgrade or args.dry_run):
        p.error("pick one of --seed, --seed-from-session, --upgrade, or --dry-run")

    try:
        lay = detect_layout(args)
    except LayoutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not lay.root.is_dir():
        print(f"error: {lay.root} is not a directory", file=sys.stderr)
        return 1

    provider = args.jev_provider
    wants_jev = provider in JEV_PROVIDERS or (args.upgrade and (lay.root / lay.detector).exists())
    files = planned_files(lay, empty_queue=args.seed_from_session, with_jev=wants_jev)
    try:
        for f in files:
            contained(lay.root, f["dest"], "destination")
    except LayoutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    present = [f for f in files if (lay.root / f["dest"]).exists()]
    installed_already = any(f["kind"] == "code" for f in present)

    states = hold_coupled(files, {f["dest"]: file_state(lay, f) for f in files})
    outdated = [d for d, st in states.items() if st == "outdated"]
    customised = [d for d, st in states.items() if st == "customised"]
    held = {f["dest"]: f["couples"] for f in files if states[f["dest"]] == "held"}
    print(f"project root : {lay.root}")
    print(f"layout       : docs={lay.docs}/  scripts={lay.scripts}/  "
          f"hooks={lay.hooks}/  skills={lay.skills}/  tests={lay.tests}/"
          + ("   (read from the installed hook)" if lay.recovered else ""))
    if installed_already:
        print(f"\nEXISTING LOOP DETECTED — {len(outdated)} generated file(s) are an older shipped version, "
              f"{len(customised)} carry your own edits.")
        print("  The queue and the archive are data and are never touched; this is an upgrade, not a seed.")
    print()

    # --- the plan -----------------------------------------------------------
    print("PLAN")
    for f in files:
        state = states[f["dest"]]
        if state == "create":
            verdict = "create"
        elif state == "data":
            verdict = "PRESERVE (data — never overwritten)"
        elif state == "current":
            verdict = "up to date"
        elif state == "customised":
            verdict = "KEEP (edited in this project)"
        elif state == "held":
            verdict = "HELD (its partner carries your edits)"
        elif args.upgrade:
            verdict = "upgrade (.bak kept)"
        else:
            verdict = "older version — needs --upgrade"
        print(f"  {verdict:34} {f['dest']}")
        print(f"  {'':34} └─ {f['role']}")
    verdict, merged = settings_action(lay)
    print(f"  {verdict:34} {lay.hooks.rsplit('/', 1)[0]}/settings.json")
    print(f"  {'':34} └─ {hook_command(lay)}")
    if provider:
        jev_verdict, jev_merged = jev_settings_action(lay, provider)
        print(f"  {jev_verdict:34} {LOCAL_SETTINGS}")
        print(f"  {'':34} └─ {jev_command(lay, provider) if provider != 'off' else 'no Jev hooks registered'}")

    # --- upgrade gate -------------------------------------------------------
    if installed_already and not args.upgrade and not args.dry_run:
        print("\nSTOP — an installation is already here.")
        for f in present:
            print(f"  found: {f['dest']}")
        print("\nNothing was written. Re-run with --upgrade to refresh the machinery")
        print("(hook, checker, skills, tests — each backed up to .bak first).")
        print("The queue and the archive are preserved either way: a half-migrated")
        print("loop that silently drops the archive is the worst outcome here.")
        if not provider:
            report_jev_state(lay)
        return 2

    if args.dry_run:
        if provider:
            report_jev(lay, provider, jev_verdict, dry_run=True)
        elif installed_already:
            report_jev_state(lay)
        report_customised(customised, held)
        report_wiring(lay)
        print("\n--dry-run: nothing was written.")
        if installed_already:
            print("Upgrade: --upgrade [--jev-provider openrouter|typesafe|off]")
        return 0

    # --- write --------------------------------------------------------------
    journal = Journal()
    try:
        written = install(lay, files, upgrade=args.upgrade, journal=journal, states=states)
        print("\nWROTE")
        for w in written:
            print(f"  {w}")
        if not written:
            print("  (nothing — every file was already current or preserved)")
        wrote_settings(lay, merged, verdict, provider, jev_merged if provider else None,
                       jev_verdict if provider else "", journal)
    except OSError as exc:
        journal.rollback()
        print(f"\n!! write failed ({exc}) — rolled back: every file is as it was before this run.")
        return 1

    rc = verify(lay)
    if rc and args.upgrade:
        journal.rollback()
        print("\n!! the upgraded machinery failed its own checks (above) — rolled back: every file is "
              "as it was before this run, and the previous loop is still in place.")
        return rc
    if provider:
        report_jev(lay, provider, jev_verdict, dry_run=False)
    elif installed_already:
        report_jev_state(lay)
    report_customised(customised, held)
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


def wrote_settings(lay: Layout, merged: dict, verdict: str, provider: str | None,
                   jev_merged: dict | None, jev_verdict: str, journal: Journal) -> None:
    if merged and verdict != "already registered" and not verdict.startswith("UNPARSEABLE"):
        write_settings(lay.root / ".claude" / "settings.json", merged, journal)
        print(f"  .claude/settings.json ({verdict})")
    elif verdict.startswith("UNPARSEABLE"):
        print(f"  !! .claude/settings.json {verdict}")
    if not provider:
        return
    if jev_verdict.startswith(("UNPARSEABLE", "REFUSED")):
        print(f"  !! {LOCAL_SETTINGS} {jev_verdict}")
    elif jev_verdict not in ("already registered", "not registered"):
        if provider != "off":
            ensure_local_exclude(lay.root, LOCAL_SETTINGS)
        write_settings(lay.root / LOCAL_SETTINGS, jev_merged, journal, private=True)
        print(f"  {LOCAL_SETTINGS} ({jev_verdict})")


def report_customised(paths: list[str], held: dict[str, str]) -> None:
    if not paths:
        return
    print("\nKEPT AS YOU LEFT THEM — these generated files differ from every version this plugin has shipped,")
    print("so they are your edits (a drain amends them on purpose) and were not overwritten:")
    for path in paths:
        print(f"  {path}")
    print("To take the plugin's version of one, move it aside and re-run --upgrade.")
    for dest, partner in held.items():
        print(f"{dest} held at its previous version because {partner} carries your edits — "
              f"move {partner} aside and re-run --upgrade to take both")


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
