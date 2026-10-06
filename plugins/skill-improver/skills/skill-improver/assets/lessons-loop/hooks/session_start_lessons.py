#!/usr/bin/env python3
"""SessionStart hook: every session begins already knowing the applied lessons.

This is the part of the loop that removes remembering. Nobody opens a file;
nobody is asked to recall a convention. The archive's rules and the queue's
depth are injected into context before the first prompt.

Two guarantees, both learned the hard way:

  * It never invents. An unreadable or missing ledger produces *no output*
    rather than a reassuring one.
  * It never breaks the session that was about to fix it. Any failure exits 0
    silently.

Parsing is delegated to scripts/lessons_graph.py so the hook and the checker
can never disagree about what the archive says.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# --- installer-templated paths (relative to the project root) ---------------
SCRIPTS_REL = "scripts"
ARCHIVE_REL = "docs/LESSONS-ARCHIVE.md"
QUEUE_REL = "docs/lessons.md"
# ---------------------------------------------------------------------------

MAX_QUEUE_TITLES = 12

_DOC_SUFFIXES = (".md", ".rst", ".txt", ".adoc")
_SETTINGS = (".claude/settings.json", ".claude/settings.local.json")


def _hook_commands(root: Path) -> list[str]:
    commands = []
    for rel in _SETTINGS:
        try:
            hooks = json.loads((root / rel).read_text(encoding="utf-8")).get("hooks", {})
            commands += [str(h.get("command", "")) for groups in hooks.values()
                         for g in groups for h in g.get("hooks", [])]
        except (OSError, ValueError, AttributeError, TypeError):
            continue
    return commands


def enforced(home: str, root: Path) -> bool:
    """True only for a single safeguard that exists and is known to run without anyone remembering.

    A gate-shaped path is not evidence: a Claude Code hook must be registered in settings, a git
    hook executable, a pre-commit config installed. A test may never be run and a CI workflow may
    filter out the change, and a Makefile, justfile, nox or tox file runs only when someone invokes
    it, so their rules are restated. A rule wrongly hidden is lost; a rule wrongly injected only
    costs a line.
    """
    raw = home.strip().strip("`").strip()
    h = raw.lower()
    if not h or "," in h or any(c.isspace() for c in h) or h.endswith(_DOC_SUFFIXES):
        return False
    path = root / raw
    if not path.is_file():
        return False
    if h.startswith(".claude/hooks/"):
        return any(raw in command for command in _hook_commands(root))
    if h.startswith(".git/hooks/"):
        return os.access(path, os.X_OK)
    if h == ".pre-commit-config.yaml":
        return os.access(root / ".git" / "hooks" / "pre-commit", os.X_OK)
    return False


def project_root() -> Path:
    """Locate the project root by looking for the ledger, not by counting `..`."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ARCHIVE_REL).exists() or (parent / SCRIPTS_REL / "lessons_graph.py").exists():
            return parent
    return here.parent.parent.parent


def build_context() -> str:
    root = project_root()
    sys.path.insert(0, str(root / SCRIPTS_REL))
    import lessons_graph as lg  # noqa: E402  (path must be set first)

    entries = lg.parse_archive()
    titles = lg.parse_queue()

    # A decline is a decision, not a rule — it is deliberately not injected.
    # A rule that was superseded, reversed, or moved elsewhere is no longer live
    # at its old row; injecting it again would repeat the rule with a stale home.
    retired = {t for e in entries for k, t in e.edges
               if k in ("supersedes", "reverses", "moves")}
    live = [e for e in entries if not e.declined and e.id not in retired]

    gated = {e.id for e in live if enforced(e.home, root)}
    advisory = [e for e in live if e.id not in gated]
    mechanical = [e for e in live if e.id in gated]

    if not live and not titles:
        return ""

    out: list[str] = ["## Lessons this project has already learned", ""]

    if advisory:
        out.append(
            f"These are applied rules from `{ARCHIVE_REL}`. They are doctrine here — "
            f"follow them without being asked."
        )
        out.append("")
        for e in advisory:
            home = f"  [{e.home}]" if e.home else ""
            out.append(f"- **{e.id}** {e.rule}{home}")
        out.append("")
    if mechanical:
        out.append(
            f"{len(mechanical)}{' more' if advisory else ''} applied rule(s) are enforced by a "
            f"registered hook, so they are not restated here:{', '.join(e.id for e in mechanical)}. If one of those checks fires, "
            f"its row in `{ARCHIVE_REL}` says why it exists."
        )
        out.append("")

    if titles:
        # Titles plus a count, never the full entries: pasting six full queue
        # entries into every session start is how a context block stops being read.
        shown = titles[:MAX_QUEUE_TITLES]
        more = len(titles) - len(shown)
        out.append(
            f"**Queue: {len(titles)} lesson(s) waiting to be drained** "
            f"(`{QUEUE_REL}`) — not yet rules:"
        )
        for t in shown:
            out.append(f"- {t}")
        if more:
            out.append(f"- …and {more} more")
        out.append("")
        out.append(
            "Run the `implement-ll` skill at the next checkpoint. Nothing is carried "
            "across two drains."
        )
        out.append("")

    try:
        findings = (len(lg.find_oscillations(entries))
                    + sum(1 for r in lg.find_recurrences(entries) if r["count"] >= 2)
                    + len(lg.find_dangling(entries)))
    except Exception:
        findings = 0
    if findings:
        out.append(
            f"⚠ `{SCRIPTS_REL}/lessons_graph.py` reports {findings} finding(s) — run it "
            f"before adding another rule."
        )
        out.append("")

    out.append(
        "Caught a mistake while working? Use the `lessons` skill to write it down now, "
        "at the moment it was caught — not at the end of the session."
    )
    return "\n".join(out)


def main() -> int:
    try:
        context = build_context()
    except Exception:
        return 0          # never break the session that was about to fix the ledger
    if not context.strip():
        return 0          # never invent
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
