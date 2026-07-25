#!/usr/bin/env python3
"""Locate an installed skill by name and classify its home.

Every improve run starts with the same probe: is `<name>` a standalone skill
under ~/.claude/skills (and where does the symlink really point), a skill in
the ~/.agents tree managed by the skills CLI, or a plugin-cache skill? The
answer decides everything downstream — plugin-cache skills are overwritten on
the next plugin update (improve via a copy), skills-CLI installs are
overwritten by `npx skills add` (improve via upstream or a fork), and only the
user's own directories are safe to improve in place.

Read-only: follows symlinks and reads directories, changes nothing.

Usage:
    python3 resolve_skill.py <name>                 # human-readable
    python3 resolve_skill.py <name> --json          # machine-readable
    python3 resolve_skill.py <name> --claude-dir ~/.claude --agents-dir ~/.agents
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def find_in_plugin_cache(claude_dir: Path, name: str):
    """All cache/<marketplace>/<plugin>/<version>/skills/<name> matches."""
    cache = claude_dir / "plugins" / "cache"
    if not cache.is_dir():
        return []
    return sorted(p for p in cache.glob(f"*/*/*/skills/{name}") if p.is_dir())


def classify(cand: Path, agents_dir: Path, claude_dir: Path):
    """(kind, real_path, advice) for a ~/.claude/skills/<name> candidate."""
    real = cand.resolve()
    agents_root = (agents_dir / "skills").resolve()
    cache_root = (claude_dir / "plugins" / "cache").resolve()
    if str(real).startswith(str(agents_root) + os.sep):
        return (
            "agents-standalone",
            real,
            "managed by the skills CLI — `npx skills add` updates overwrite it; "
            "durable homes are a PR to the source repo or a fork. Improve a copy.",
        )
    if str(real).startswith(str(cache_root) + os.sep):
        return (
            "plugin-cache",
            real,
            "plugin cache is overwritten on plugin updates — NEVER edit in place; "
            "improve a copy and ship it upstream or as a local shadow skill.",
        )
    return (
        "own-standalone",
        real,
        "the user's own directory — safe to improve in place after confirmation.",
    )


def resolve(name: str, claude_dir: Path, agents_dir: Path):
    results = []
    cand = claude_dir / "skills" / name
    if cand.exists() or cand.is_symlink():
        kind, real, advice = classify(cand, agents_dir, claude_dir)
        results.append({
            "name": name,
            "kind": kind,
            "path": str(cand),
            "real_path": str(real),
            "exists": real.exists(),
            "advice": advice,
        })
        # Note whether the skills CLI tracks it (extra provenance).
        lock = load_json(agents_dir / ".skill-lock.json") or {}
        entry = (lock.get("skills") or {}).get(name)
        if entry:
            results[-1]["lock_source"] = entry.get("sourceUrl")
            results[-1]["lock_updated"] = entry.get("updatedAt")
    for hit in find_in_plugin_cache(claude_dir, name):
        # cache/<market>/<plugin>/<ver>/skills/<name> -> plugin = parts[-4]
        plugin = hit.parts[-4] if len(hit.parts) >= 4 else "?"
        results.append({
            "name": name,
            "kind": "plugin-cache",
            "path": str(hit),
            "real_path": str(hit.resolve()),
            "exists": True,
            "plugin": plugin,
            "advice": "plugin cache is overwritten on plugin updates — NEVER edit "
                      "in place; improve a copy and ship it upstream or as a "
                      "local shadow skill.",
        })
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name", help="Skill name to locate")
    ap.add_argument("--claude-dir", default=os.path.expanduser("~/.claude"))
    ap.add_argument("--agents-dir", default=os.path.expanduser("~/.agents"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    claude_dir = Path(args.claude_dir).expanduser()
    agents_dir = Path(args.agents_dir).expanduser()
    results = resolve(args.name, claude_dir, agents_dir)

    if args.json:
        print(json.dumps({"results": results}, indent=2))
    elif not results:
        print(f"No skill named '{args.name}' found under "
              f"{claude_dir}/skills or the plugin cache.")
        sys.exit(1)
    else:
        for r in results:
            print(f"[{r['kind']}] {r['path']}")
            if r["path"] != r["real_path"]:
                print(f"    -> {r['real_path']}")
            if not r["exists"]:
                print("    !! symlink target missing")
            src = r.get("lock_source")
            if src:
                print(f"    installed from {src} (updated {r.get('lock_updated')})")
            print(f"    {r['advice']}")
    if not results:
        sys.exit(1)


if __name__ == "__main__":
    main()
