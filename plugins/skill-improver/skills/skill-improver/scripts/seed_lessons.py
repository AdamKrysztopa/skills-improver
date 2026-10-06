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
import ast
import functools
import importlib.util
import inspect
import io
import json
import os
import posixpath
import re
import stat
import subprocess
import sys
import tempfile
import tokenize
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "lessons-loop"

DOC_DIR_CANDIDATES = ("docs", "doc", "documentation")
SCRIPT_DIR_CANDIDATES = ("scripts", "bin", "tools")
TEST_DIR_CANDIDATES = ("tests", "test")
ARCHIVE_NAME = "LESSONS-ARCHIVE.md"
QUEUE_NAME = "lessons.md"
LEDGER_SEARCH_DEPTH = 3
REPORT_LINES = 20

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
        self.archive_name = ARCHIVE_NAME
        self.queue_name = QUEUE_NAME
        self.recovered = False
        self.located = False

    @property
    def archive(self) -> str:
        return f"{self.docs}/{self.archive_name}"

    @property
    def queue(self) -> str:
        return f"{self.docs}/{self.queue_name}"

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
    archive_name, queue_name = posixpath.basename(archive), posixpath.basename(queue)
    if not args.docs_dir and (posixpath.dirname(archive) != docs or queue_name.lower() != QUEUE_NAME.lower()
                              or archive_name.lower() != ARCHIVE_NAME.lower()):
        raise LayoutError(
            f"the installed hook reads its queue from {queue} and its archive from {archive}, which "
            "this installer cannot reproduce. Nothing was written. Pass --docs-dir to say where "
            f"{QUEUE_NAME} and {ARCHIVE_NAME} live, or reconcile the hook by hand.")
    found = {"docs": docs or ".", "scripts": scripts, "archive_name": archive_name, "queue_name": queue_name}
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
    if root.is_dir() and not args.docs_dir and not known:
        locate_ledger(lay)
    if known and not args.docs_dir:
        lay.archive_name, lay.queue_name = known["archive_name"], known["queue_name"]
    else:
        lay.archive_name = on_disk_name(root / lay.docs, ARCHIVE_NAME) or ARCHIVE_NAME
        lay.queue_name = on_disk_name(root / lay.docs, QUEUE_NAME) or QUEUE_NAME
    return lay


def on_disk_name(directory: Path, name: str) -> str | None:
    """The entry in `directory` that is `name` up to case, spelled as the filesystem holds it.

    A case-insensitive filesystem answers `exists()` for either spelling, so only the listing can
    tell which one a second, differently-cased file would collide with on Linux.
    """
    try:
        names = os.listdir(directory)
    except OSError:
        return None
    if name in names:
        return name
    return next((n for n in sorted(names) if n.lower() == name.lower()), None)


def find_archives(root: Path) -> list[str]:
    """Every directory holding a lessons archive: the project root, and the doc trees below it."""
    hits = {"."} if on_disk_name(root, ARCHIVE_NAME) else set()
    for top in DOC_DIR_CANDIDATES:
        base = root / top
        if base.is_symlink() or not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            rel = Path(dirpath).relative_to(root).as_posix()
            dirnames[:] = [d for d in dirnames if not d.startswith(".")] if rel.count("/") < LEDGER_SEARCH_DEPTH else []
            if any(n.lower() == ARCHIVE_NAME.lower() for n in filenames):
                hits.add(rel)
    return sorted(hits)


def locate_ledger(lay: Layout) -> None:
    """Point `lay` at an existing loop's ledger, found by its archive.

    A queue alone does not locate the ledger: a stale one left in the default docs directory would
    otherwise put a new, empty archive beside it while the real one lives elsewhere.

    Raises:
        LayoutError: A loop is installed but its ledger is not in exactly one place; creating an
            empty one beside it would split the record.
    """
    root = lay.root
    present = [f["dest"] for f in planned_files(lay, False, with_jev=True)
               if f["kind"] == "code" and (root / f["dest"]).exists()]
    if not present:
        return
    found = find_archives(root)
    if len(found) == 1:
        lay.located = found[0] != lay.docs
        lay.docs = found[0]
        return
    if not found and on_disk_name(root / lay.docs, QUEUE_NAME):
        return
    where = (f"{len(found)} archives were found ({', '.join(d + '/' for d in found)})" if found
             else f"no {ARCHIVE_NAME} was found at the root or under {', '.join(d + '/' for d in DOC_DIR_CANDIDATES)}")
    raise LayoutError(
        f"an existing lessons loop is installed here ({present[0]}), but its ledger cannot be "
        f"located: {where}. Nothing was written, and a second ledger is never created. "
        f"Pass --docs-dir with the directory that holds {QUEUE_NAME} and the archive.")


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
    return with_constants(text, constants)


def with_constants(text: str, constants: dict | None) -> str:
    """Set each installer-templated `NAME = "..."` line; the installer owns these lines, not the project."""
    for name, value in (constants or {}).items():
        text = re.sub(rf'^{name} = ".*"$', lambda _m, n=name, v=value: f'{n} = "{v}"', text, flags=re.M)
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
        {"dest": lay.checker, "src": "scripts/lessons_graph.py", "kind": "code", "part": "checker",
         "role": "the mechanical check — oscillation, recurrence, dangling edges",
         "constants": {"ARCHIVE_REL": lay.archive, "QUEUE_REL": lay.queue}},
        {"dest": lay.hook, "src": "hooks/session_start_lessons.py", "kind": "code", "part": "hook",
         "role": "the part that removes remembering",
         "legacy": ["legacy/hooks/session_start_lessons.v1.3.1.py",
                    "legacy/hooks/session_start_lessons.v1.4.0.py"],
         "couples": f"{lay.tests}/test_lessons_loop.py",
         "constants": {"SCRIPTS_REL": lay.scripts, "ARCHIVE_REL": lay.archive,
                       "QUEUE_REL": lay.queue}},
        {"dest": f"{lay.skills}/lessons/SKILL.md", "src": "skills/lessons/SKILL.md",
         "kind": "code", "part": "lessons", "role": "capture — writes one entry and stops",
         "legacy": ["legacy/skills/lessons/SKILL.v1.2.0.md"]},
        {"dest": f"{lay.skills}/implement-ll/SKILL.md",
         "src": "skills/implement-ll/SKILL.md", "kind": "code", "part": "implement-ll",
         "role": "drain — group, route, apply, verify, archive"},
        {"dest": f"{lay.tests}/test_lessons_loop.py", "src": "tests/test_lessons_loop.py",
         "kind": "code", "suite": True, "role": "proves the checker and hook actually fire",
         "legacy": ["legacy/tests/test_lessons_loop.v1.3.1.py",
                    "legacy/tests/test_lessons_loop.v1.4.0.py",
                    "legacy/tests/test_lessons_loop.v1.4.1.py"],
         "constants": {"ROOT_UP": tests_root_up, "CHECKER_REL": lay.checker,
                       "HOOK_REL": lay.hook, "SKILLS_REL": lay.skills,
                       "TEMPLATE_ARCHIVE_REL": f"{lay.tests}/template-archive.md",
                       "TEMPLATE_QUEUE_REL": f"{lay.tests}/template-queue.md",
                       "ARCHIVE_IN_PROJECT": lay.archive, "QUEUE_IN_PROJECT": lay.queue,
                       "SCRIPTS_IN_PROJECT": lay.scripts, "PROJECT_OWNED": ""}},
        {"dest": f"{lay.tests}/fixture-broken.md", "src": "tests/fixture-broken.md",
         "kind": "code", "suite": True, "role": "seeded oscillation + 2x recurrence + typo edge"},
        {"dest": f"{lay.tests}/fixture-clean.md", "src": "tests/fixture-clean.md",
         "kind": "code", "suite": True, "role": "a healthy archive the checker must stay quiet about"},
        {"dest": f"{lay.tests}/template-archive.md", "src": "docs/LESSONS-ARCHIVE.md",
         "kind": "code", "suite": True, "role": "pristine archive — guards the fenced-example defence"},
        {"dest": f"{lay.tests}/template-queue.md", "src": "docs/lessons.md",
         "kind": "code", "suite": True, "role": "pristine queue"},
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
            if not os.path.lexists(candidate):
                return candidate
            if not candidate.is_symlink() and candidate.read_bytes() == prior:
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
            _create_new(bak, prior)
        try:
            _replace_with(path, text.encode("utf-8"), mode if mode is not None else prior_mode)
        except BaseException:
            if bak:
                bak.unlink(missing_ok=True)
            raise
        self._undo.append((path, prior, prior_mode, bak))

    def rollback(self) -> None:
        for path, prior, mode, bak in reversed(self._undo):
            if prior is None:
                path.unlink(missing_ok=True)
            else:
                _replace_with(path, prior, mode)
            if bak:
                bak.unlink(missing_ok=True)
        for directory in reversed(self._dirs):
            try:
                directory.rmdir()
            except OSError:
                pass
        self._undo, self._dirs = [], []


def _create_new(path: Path, data: bytes) -> None:
    """Write a file that must not exist yet: O_EXCL refuses a planted file or symlink at `path`."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def _replace_with(path: Path, data: bytes, mode: int) -> None:
    """Atomically replace `path` via a randomly named sibling that no pre-existing link can occupy."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


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


def project_lessons_hook(lay: Layout) -> str | None:
    """A registered SessionStart script of the project's own that is shown to inject this ledger.

    Mentioning a ledger file is not enough: a comment, a queue counter or an archive validator
    names it too. The script is run as Claude Code runs it at session start, and counts only if
    what it injects names the archive or cites a rule the archive holds.
    """
    names = (posixpath.basename(lay.archive).lower(), posixpath.basename(lay.queue).lower())
    for rel in (".claude/settings.json", LOCAL_SETTINGS):
        try:
            settings = json.loads((lay.root / rel).read_text(encoding="utf-8"))
            check_hooks_shape(settings)
        except (OSError, ValueError):
            continue
        for group in settings.get("hooks", {}).get("SessionStart", []):
            for h in group.get("hooks", []):
                command = str(h.get("command", ""))
                if "session_start_lessons.py" in command:
                    continue
                for script in re.findall(r"[\w./-]+\.py", command):
                    script = script.split("CLAUDE_PROJECT_DIR/", 1)[-1]
                    try:
                        body = (lay.root / script).read_text(encoding="utf-8", errors="replace").lower()
                    except OSError:
                        continue
                    if any(name in body for name in names) and injects_archive(lay, script):
                        return script
    return None


def injects_archive(lay: Layout, script: str) -> bool:
    try:
        proc = subprocess.run(
            [sys.executable, str(lay.root / script)], cwd=str(lay.root), capture_output=True, text=True,
            input=json.dumps({"hook_event_name": "SessionStart", "source": "startup"}), timeout=10,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(lay.root), "PYTHONDONTWRITEBYTECODE": "1"})
    except (OSError, subprocess.TimeoutExpired):
        return False
    if proc.returncode != 0:
        return False
    try:
        context = str(json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"])
    except (ValueError, KeyError, TypeError):
        context = proc.stdout
    if lay.archive.lower() in context.lower():
        return True
    try:
        archive = (lay.root / lay.archive).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    held = set(re.findall(r"^\|\s*(L\d+\.\d+)\s*\|", archive, re.M))
    return bool(held & set(re.findall(r"\bL\d+\.\d+\b", context)))


def settings_action(lay: Layout, superseded_by: str | None = None) -> tuple[str, dict]:
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
    if superseded_by:
        return ("unchanged (project's own hook)", {})
    starts.append({
        "$comment": HOOK_COMMENT,
        "hooks": [{"type": "command", "command": hook_command(lay)}],
    })
    verb = "register SessionStart hook" if path.exists() else "create with SessionStart hook"
    return (verb, settings)


def registered(lay: Layout) -> bool:
    """True when .claude/settings.json actually registers this loop's SessionStart hook."""
    try:
        settings = json.loads((lay.root / ".claude" / "settings.json").read_text(encoding="utf-8"))
        check_hooks_shape(settings)
    except (OSError, ValueError):
        return False
    return any("session_start_lessons.py" in str(h.get("command", ""))
               for g in settings.get("hooks", {}).get("SessionStart", []) for h in g.get("hooks", []))


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
    return load_detector().settings_env(root, USER_CLAUDE_DIR / "settings.json")


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
    for event, matcher in load_detector().EVENTS:
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
    for event, matcher in load_detector().EVENTS:
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
    rendered = render(lay, f)
    if same_content(found, rendered, f["dest"]):
        return "current"
    pinned = with_constants(found, f.get("constants"))
    if pinned != found and same_content(pinned, rendered, f["dest"]):
        return "outdated"
    if any(same_content(pinned, render(lay, f, old), f["dest"]) for old in f.get("legacy", ())):
        return "outdated"
    return "customised"


def same_content(found: str, shipped: str, dest: str) -> bool:
    """Byte-equal, or for Python equal after formatting: a project formatter is not a project edit."""
    if found == shipped:
        return True
    if not dest.endswith(".py"):
        return False
    fingerprint = code_fingerprint(found)
    return fingerprint is not None and fingerprint == code_fingerprint(shipped)


def code_fingerprint(text: str) -> tuple[str, list[str]] | None:
    """The syntax tree and the comment text: what a formatter such as ruff or black leaves alone.

    Docstrings are compared after cleandoc, since formatters re-indent them and move closing quotes.
    """
    try:
        tree = ast.parse(text)
        comments = [tok.string.lstrip("#").strip()
                    for tok in tokenize.generate_tokens(io.StringIO(text).readline)
                    if tok.type == tokenize.COMMENT]
    except (SyntaxError, ValueError, tokenize.TokenError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                first.value.value = inspect.cleandoc(first.value.value).strip()
    return ast.dump(tree), comments


def plan_states(lay: Layout, files: list[dict], superseded_by: str | None) -> dict[str, str]:
    """Each destination's state, once it is known which parts the project owns and so what the suite tests.

    The suite tests the shipped checker and hook; it is told which parts are the project's own so
    it skips them rather than asserting the shipped behaviour of a file this run did not install.
    With both the checker and the hook the project's own there is nothing of ours to test.
    """
    states = {f["dest"]: file_state(lay, f) for f in files if not f.get("suite")}
    if superseded_by:
        states[lay.hook] = "superseded"
    owned = sorted(f["part"] for f in files if f.get("part") and states[f["dest"]] in ("customised", "superseded"))
    needed = not {"checker", "hook"} <= set(owned)
    for f in files:
        if f.get("suite"):
            if "PROJECT_OWNED" in f.get("constants", {}):
                f["constants"]["PROJECT_OWNED"] = " ".join(owned)
            states[f["dest"]] = file_state(lay, f) if needed else "not needed"
    return hold_coupled(files, states)


def hold_coupled(files: list[dict], states: dict[str, str]) -> dict[str, str]:
    """Mark an outdated file `held` when the file it is tested against carries the project's edits.

    Only the hook is held, behind an edited suite that asserts its behaviour. The suite is never
    held behind an edited hook: it is told the hook is the project's own and skips its checks.
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


def print_capped(text: str, rerun: str) -> None:
    lines = text.rstrip().splitlines()
    print("\n".join(lines[:REPORT_LINES]))
    if len(lines) > REPORT_LINES:
        print(f"… {len(lines) - REPORT_LINES} more line(s); for all of them run: {rerun}")


def verify(lay: Layout, states: dict[str, str], *, superseded_by: str | None,
           ledger_created: bool) -> list[str]:
    """Run the machinery and show what it prints. A hook is code, not a claim.

    Returns:
        Why the machinery failed, one line per cause; empty when it passed.
    """
    root = lay.root
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root),
           "PYTHONDONTWRITEBYTECODE": "1"}
    causes = []
    suite = f"{lay.tests}/test_lessons_loop.py"

    if states[lay.checker] == "customised":
        print(f"\n--- the checker, against the seeded-defect fixture: skipped — {lay.checker} is this "
              "project's own version, and the fixture tests the shipped one ---")
    else:
        print("\n--- the checker, against the seeded-defect fixture "
              "(must exit 1 and print a chain) ---")
        proc = subprocess.run(
            [sys.executable, str(root / lay.checker)],
            env={**env, "LESSONS_ARCHIVE": str(root / lay.tests / "fixture-broken.md")},
            capture_output=True, text=True)
        print_capped(proc.stdout or proc.stderr, f"python3 {lay.checker}")
        print(f"[exit {proc.returncode}]")
        if proc.returncode != 1:
            print("!! the checker did not fire on a deliberately broken archive")
            causes.append(f"{lay.checker} exited {proc.returncode} on the seeded-defect fixture, not 1")

    print("\n--- the checker, against this project's real archive ---")
    proc = subprocess.run([sys.executable, str(root / lay.checker)],
                          env=env, capture_output=True, text=True)
    print_capped(proc.stdout or proc.stderr, f"python3 {lay.checker}")
    print(f"[exit {proc.returncode}]" + (" — findings in this project's archive are the next drain's work, "
                                         "not an install failure" if proc.returncode == 1 else ""))

    if superseded_by:
        print(f"\n--- the SessionStart hook: {superseded_by} is this project's own and already injects "
              "the ledger; not run here ---")
    else:
        print("\n--- the SessionStart hook, triggered (this is what lands in every session) ---")
        proc = subprocess.run([sys.executable, str(root / lay.hook)],
                              env=env, capture_output=True, text=True, cwd=str(root))
        if proc.returncode != 0:
            print(f"!! hook exited {proc.returncode}; it must always exit 0")
            causes.append(f"{lay.hook} exited {proc.returncode}; a SessionStart hook must always exit 0")
        if not proc.stdout.strip():
            print("(no output — the ledger is empty, which is correct for a fresh install)" if ledger_created
                  else f"(no output — the hook found no applied rule in {lay.archive} and nothing queued "
                       f"in {lay.queue})")
        else:
            try:
                ctx = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
                print(ctx)
            except (json.JSONDecodeError, KeyError) as exc:
                print(f"!! hook emitted something that is not SessionStart context: {exc}")
                print(proc.stdout)
                causes.append(f"{lay.hook} printed something that is not SessionStart context ({exc})")

    if states[suite] == "not needed":
        print("\n--- the loop's own test suite: not installed — the checker and the SessionStart hook "
              "it tests are both this project's own ---")
        return causes
    print("\n--- the loop's own test suite ---")
    proc = subprocess.run([sys.executable, str(root / suite)],
                          env=env, capture_output=True, text=True)
    tail = proc.stdout.rstrip().splitlines()
    print("\n".join(tail[-3:]) if tail else proc.stderr.rstrip())
    if proc.returncode != 0:
        failed = [line.strip()[len("FAIL"):].strip().split("  ")[0]
                  for line in tail if line.strip().startswith("FAIL ")]
        print("\n".join(f"  FAIL {name}" for name in failed))
        if failed:
            causes.append(f"{suite} failed {len(failed)} check(s): {'; '.join(failed)}")
        else:
            crash = (proc.stderr.strip().splitlines() or [f"exit {proc.returncode}"])[-1]
            causes.append(f"{suite} crashed before reporting: {crash}")
    return causes


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

    superseded_by = None if registered(lay) else project_lessons_hook(lay)
    states = plan_states(lay, files, superseded_by)
    outdated = [d for d, st in states.items() if st == "outdated"]
    customised = [d for d, st in states.items() if st == "customised"]
    held = {f["dest"]: f["couples"] for f in files if states[f["dest"]] == "held"}
    print(f"project root : {lay.root}")
    print(f"layout       : docs={lay.docs}/  scripts={lay.scripts}/  "
          f"hooks={lay.hooks}/  skills={lay.skills}/  tests={lay.tests}/"
          + ("   (read from the installed hook)" if lay.recovered else "")
          + (f"   (ledger found in {lay.docs}/)" if lay.located else ""))
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
        elif state == "superseded":
            verdict = "SKIP (project has its own hook)"
        elif state == "not needed":
            verdict = "SKIP (nothing of ours to test)"
        elif args.upgrade:
            verdict = "upgrade (.bak kept)"
        else:
            verdict = "older version — needs --upgrade"
        print(f"  {verdict:34} {f['dest']}")
        print(f"  {'':34} └─ " + (f"{superseded_by} already injects the ledger; no second hook is added"
                                       if state == "superseded" else f["role"]))
    verdict, merged = settings_action(lay, superseded_by)
    print(f"  {verdict:34} {lay.hooks.rsplit('/', 1)[0]}/settings.json")
    print(f"  {'':34} └─ " + (f"SessionStart already runs {superseded_by}" if superseded_by
                               else hook_command(lay)))
    also = project_lessons_hook(lay) if not superseded_by and verdict == "already registered" else None
    if also:
        print(f"  !! {also} also injects the ledger at SessionStart, beside {lay.hook} — unregister one of them")
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

    causes = verify(lay, states, superseded_by=superseded_by,
                    ledger_created=all(states[f["dest"]] == "create" for f in files if f["kind"] == "data"))
    if causes:
        journal.rollback()
        if args.upgrade:
            print("\n!! the upgraded machinery failed its own checks — rolled back: every file is "
                  "as it was before this run, and the previous loop is still in place.")
        else:
            print("\n!! the new machinery failed its own checks — rolled back: nothing this run "
                  "created is left behind.")
        print("Cause:")
        for cause in causes:
            print(f"  - {cause}")
        return 1
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

    if not registered(lay) and not superseded_by:
        print(f"""
INSTALLED, NOT WIRED — Claude Code will not run the loop until .claude/settings.json registers:
  {hook_command(lay)}
under hooks.SessionStart. Add it by hand, then re-run --upgrade to confirm.""")
        return 3
    print("\nDone.")
    return 0


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
