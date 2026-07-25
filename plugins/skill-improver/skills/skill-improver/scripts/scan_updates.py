#!/usr/bin/env python3
"""Scan globally installed Claude Code plugins AND standalone skills, and
report which have newer versions available at their source.

Why this exists: update state is spread across four places on disk --
`installed_plugins.json` (what plugin versions are installed),
`known_marketplaces.json` (where each marketplace lives + its GitHub repo),
each marketplace's cloned `marketplace.json` (the source of truth for the
*latest* declared version/sha of every plugin), and `~/.agents/.skill-lock.json`
(the standalone-skill install record: source repo, upstream path, install
hashes). Comparing those by hand is fiddly and error prone. This script does
it deterministically and emits a clean report (table or JSON) so the model can
reason about *what to do*, not *how to diff git shas*.

Comparison policy (learned from a real false positive): when both sides expose
a version string, the version wins. The `gitCommitSha` recorded in
installed_plugins.json can go stale -- installers sometimes bump the recorded
version without refreshing the recorded sha -- so a sha mismatch at equal
versions is reported as up-to-date with a note, never as an update.

Read-only: it may `git fetch` marketplace clones and shallow-clone skill
source repos into a temp dir (to compare against the true latest), but never
checks anything out in place, edits, or deletes. Pass --no-fetch to stay fully
offline; standalone skills then report as unknown (their comparison needs the
clone).

Usage:
    python scan_updates.py                 # human-readable table (fetches)
    python scan_updates.py --json          # machine-readable, for the model
    python scan_updates.py --no-fetch      # offline; plugins vs local clones only
    python scan_updates.py --claude-dir ~/.claude --agents-dir ~/.agents
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Marketplace-clone fetches and skill-repo clones touch the network; keep them
# short so a slow or offline remote degrades to "couldn't check" instead of
# hanging the scan.
GIT_TIMEOUT = 20
CLONE_TIMEOUT = 60


def run_git(args, cwd=None, timeout=GIT_TIMEOUT):
    """Run a git command, returning (ok, stdout). Never raises."""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return out.returncode == 0, out.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False, ""


def load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def default_branch(clone: Path) -> str | None:
    """Best-effort resolve the remote default branch (e.g. 'main')."""
    ok, ref = run_git(["symbolic-ref", "refs/remotes/origin/HEAD"], cwd=clone)
    if ok and ref:
        return ref.rsplit("/", 1)[-1]
    for cand in ("main", "master"):
        ok, _ = run_git(["rev-parse", f"origin/{cand}"], cwd=clone)
        if ok:
            return cand
    return None


def latest_manifest(clone: Path, fetch: bool):
    """Return the newest marketplace.json the source knows about.

    Prefer the freshly-fetched origin copy so we compare against what the user
    *would* get on update, not a stale local checkout. Fall back to the
    working-tree file if git isn't usable here.
    """
    manifest_rel = ".claude-plugin/marketplace.json"
    if fetch:
        run_git(["fetch", "--quiet", "origin"], cwd=clone)
    branch = default_branch(clone)
    if branch:
        ok, blob = run_git(["show", f"origin/{branch}:{manifest_rel}"], cwd=clone)
        if ok and blob:
            try:
                return json.loads(blob)
            except json.JSONDecodeError:
                pass
    return load_json(clone / manifest_rel)


def declared_source_id(plugin_entry: dict):
    """Extract the comparable 'version identity' a manifest declares for a plugin.

    Marketplace entries vary: some carry an explicit `version`, others pin a
    git `sha`/`ref` inside a `source` object, others are a bare local path with
    neither. Return (version, sha, is_local, src_url) — is_local flags a plugin
    that lives inside the marketplace repo itself, so the repo's own HEAD sha
    is its effective version; src_url is the upstream git URL for url-sourced
    plugins (used to resolve version tags against the pin).
    """
    version = plugin_entry.get("version")
    sha = None
    src_url = None
    is_local = False
    src = plugin_entry.get("source")
    if isinstance(src, dict):
        sha = src.get("sha")
        src_url = src.get("url")
        version = version or src.get("ref")
    elif isinstance(src, str):  # e.g. "./plugins/foo" — a subdir of the marketplace
        is_local = True
    return version, sha, is_local, src_url


def market_head_sha(clone: Path, repo: str | None, fetch: bool):
    """Latest sha of the marketplace repo itself.

    Three sources, in order of freshness: the clone's origin HEAD (classic git
    clone), a live ls-remote of the GitHub repo (snapshot marketplaces — the
    plugin system now downloads snapshots with no .git to fetch), and finally
    the snapshot's own .gcs-sha marker (offline fallback, as fresh as the last
    time the plugin system refreshed the snapshot).
    """
    branch = default_branch(clone)
    if branch:
        ok, sha = run_git(["rev-parse", f"origin/{branch}"], cwd=clone)
        if ok and sha:
            return sha
    if fetch and repo:
        ok, out = run_git(["ls-remote", f"https://github.com/{repo}.git", "HEAD"])
        if ok and out:
            return out.split()[0]
    try:
        sha = (clone / ".gcs-sha").read_text().strip()
        if sha:
            return sha
    except OSError:
        pass
    return None


def ls_remote_tags(url: str):
    """{tag_ref: sha} for a remote repo, or None if unreachable."""
    ok, out = run_git(["ls-remote", "--tags", url])
    if not ok:
        return None
    tags = {}
    for line in out.splitlines():
        sha, _, ref = line.partition("\t")
        tags[ref.strip()] = sha.strip()
    return tags


def resolve_version_commit(tags: dict, version: str):
    """Map a version string to an upstream commit via the repo's tags.

    Tries `<ver>` and `v<ver>`, preferring the peeled `^{}` commit of an
    annotated tag over the tag object itself.
    """
    for cand in (version, f"v{version}"):
        peeled = tags.get(f"refs/tags/{cand}^{{}}")
        if peeled:
            return peeled
    for cand in (version, f"v{version}"):
        direct = tags.get(f"refs/tags/{cand}")
        if direct:
            return direct
    return None


def compare(installed_ver, installed_sha, latest_ver, latest_sha):
    """Decide update status from whatever identifiers both sides expose.

    Version beats sha when both sides have a version: the installed record's
    gitCommitSha has a known staleness mode (version bumped, sha not refreshed)
    that produced a real false positive, while version strings are maintained
    on both sides. Sha-vs-sha is the fallback for plugins that expose no
    version (e.g. local-path plugins compared against the repo HEAD).

    Returns up-to-date | update-available | unknown.
    """
    vers_known = (
        installed_ver and latest_ver
        and installed_ver != "unknown" and latest_ver != "unknown"
    )
    if vers_known:
        return "up-to-date" if installed_ver == latest_ver else "update-available"
    if installed_sha and latest_sha:
        return "up-to-date" if installed_sha == latest_sha else "update-available"
    return "unknown"


def parse_iso(ts):
    """ISO-8601 timestamp -> epoch seconds, or None. Tolerates a trailing Z."""
    from datetime import datetime
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def scan_plugins(claude_dir: Path, fetch: bool):
    """Compare installed_plugins.json against the marketplace manifests."""
    plugins_dir = claude_dir / "plugins"
    installed = load_json(plugins_dir / "installed_plugins.json") or {}
    markets = load_json(plugins_dir / "known_marketplaces.json") or {}

    # Cache each marketplace's latest manifest + HEAD sha so N plugins from one
    # marketplace trigger one fetch, not N. Upstream tag listings (for the
    # version-vs-pin disambiguation) are cached per URL the same way.
    manifest_cache: dict[str, dict | None] = {}
    head_cache: dict[str, str | None] = {}
    tags_cache: dict[str, dict | None] = {}
    snapshot_cache: dict[str, tuple | None] = {}

    def snapshot_info(market_name: str):
        """(gcs_sha, mtime) of a snapshot marketplace's marker file, or None."""
        if market_name in snapshot_cache:
            return snapshot_cache[market_name]
        loc = (markets.get(market_name) or {}).get("installLocation")
        info = None
        if loc:
            marker = Path(loc) / ".gcs-sha"
            try:
                info = (marker.read_text().strip(), marker.stat().st_mtime)
            except OSError:
                info = None
        snapshot_cache[market_name] = info
        return info

    def manifest_for(market_name: str):
        if market_name in manifest_cache:
            return manifest_cache[market_name]
        info = markets.get(market_name) or {}
        loc = info.get("installLocation")
        repo = (info.get("source") or {}).get("repo")
        # latest_manifest() runs the fetch; cache HEAD in the same pass.
        m = latest_manifest(Path(loc), fetch) if loc else None
        head_cache[market_name] = market_head_sha(Path(loc), repo, fetch) if loc else None
        manifest_cache[market_name] = m
        return m

    def tags_for(url: str):
        if url not in tags_cache:
            tags_cache[url] = ls_remote_tags(url)
        return tags_cache[url]

    results = []
    for plugin_key, records in (installed.get("plugins") or {}).items():
        # plugin_key looks like "ds-crew@ds-crew" -> name, marketplace
        name, _, market = plugin_key.partition("@")
        for rec in records:
            installed_ver = rec.get("version")
            installed_sha = rec.get("gitCommitSha")
            manifest = manifest_for(market)

            latest_ver = latest_sha = src_url = None
            used_head_fallback = False
            repo = (markets.get(market, {}).get("source") or {}).get("repo")
            if manifest:
                for entry in manifest.get("plugins", []):
                    if entry.get("name") == name:
                        latest_ver, latest_sha, is_local, src_url = declared_source_id(entry)
                        # Plugin lives in the marketplace repo itself and pins no
                        # sha of its own -> the repo's HEAD is its version. For
                        # SNAPSHOT marketplaces, compare against the snapshot's
                        # gcs-sha instead: that is what an update would actually
                        # deliver. (The live repo HEAD can sit ahead of the
                        # snapshot — flagging that gap as UPDATE right after the
                        # user updated is cry-wolf; they can't act on it.)
                        if is_local and not latest_sha and not latest_ver:
                            snap = snapshot_info(market)
                            if snap and snap[0]:
                                latest_sha = snap[0]
                            else:
                                latest_sha = head_cache.get(market)
                            used_head_fallback = True
                        break

            status = compare(installed_ver, installed_sha, latest_ver, latest_sha)
            note = None
            # Disambiguation for sha-pinned, url-sourced plugins (no version on
            # the manifest side, so compare() fell back to shas): the installed
            # record's gitCommitSha has a known staleness mode (the installer
            # bumps the recorded version without refreshing the recorded sha —
            # this exact case produced a false UPDATE for superpowers 6.2.0).
            # Resolve the installed version to an upstream commit via the source
            # repo's tags and compare THAT against the manifest pin.
            if (
                status == "update-available"
                and src_url and latest_sha and not latest_ver
                and installed_ver and installed_ver != "unknown"
            ):
                if not fetch:
                    status = "unknown"
                    note = ("offline: cannot resolve whether installed version "
                            f"{installed_ver} matches the pinned upstream sha")
                else:
                    tags = tags_for(src_url)
                    commit = resolve_version_commit(tags, installed_ver) if tags else None
                    if commit and commit == latest_sha:
                        status = "up-to-date"
                        note = (f"installed version {installed_ver} resolves to the "
                                f"pinned upstream commit; the recorded install sha "
                                f"is stale (bookkeeping artifact, not an update)")
                    elif commit:
                        pass  # pin sits past the installed version's tag: real update
                    else:
                        status = "unknown"
                        note = ("recorded install sha differs from the manifest pin "
                                f"but {installed_ver} has no matching upstream tag "
                                f"in {src_url} to disambiguate")
            # Bookkeeping honesty: equal versions but diverging shas means the
            # installed record's sha is stale (or the marketplace advanced
            # content without bumping the version). Not an update — but say so.
            elif (
                status == "up-to-date"
                and installed_ver and latest_ver
                and installed_sha and latest_sha
                and installed_sha != latest_sha
            ):
                note = ("versions match but recorded install sha differs from "
                        "the manifest pin — the local record's sha is stale, "
                        "not evidence of an update")
            if used_head_fallback and status == "update-available" and note is None:
                # Snapshot marketplaces: a plugin refreshed *after* the snapshot
                # was downloaded provably installed this snapshot's content, so
                # a mismatching recorded sha is the plugin system's stale
                # bookkeeping (observed live: four official plugins refreshed
                # seconds earlier still flagged UPDATE). Only applies when the
                # snapshot IS our comparison target (gcs == HEAD we're using).
                snap = snapshot_info(market)
                if snap:
                    gcs_sha, snap_mtime = snap
                    updated_ts = parse_iso(rec.get("lastUpdated"))
                    if (gcs_sha and gcs_sha == latest_sha
                            and updated_ts and updated_ts >= snap_mtime):
                        status = "up-to-date"
                        note = ("refreshed from the current marketplace snapshot "
                                "after the recorded sha was written — the record's "
                                "sha is stale (plugin-system bookkeeping), the "
                                "installed content is current")
            if used_head_fallback and status == "update-available" and note is None:
                note = ("compared against the marketplace repo's HEAD (the plugin "
                        "pins no version/sha of its own) — any commit in that repo "
                        "advances it, so this plugin's own content may be unchanged")
            results.append(
                {
                    "kind": "plugin",
                    "plugin": name,
                    "marketplace": market,
                    "repo": repo,
                    "installed_version": installed_ver,
                    "installed_sha": (installed_sha or "")[:10] or None,
                    "latest_version": latest_ver,
                    "latest_sha": (latest_sha or "")[:10] or None,
                    "status": status,
                    "note": note,
                    "install_path": rec.get("installPath"),
                    "last_updated": rec.get("lastUpdated"),
                }
            )
    return results


def folders_differ(local: Path, upstream: Path):
    """True if the two skill folders differ in content (diff -rq).

    Returns True/False, or None if the comparison itself failed. We compare
    file trees rather than trusting the lock's skillFolderHash so the answer
    does not depend on reverse-engineering the installer's hash recipe.
    """
    try:
        out = subprocess.run(
            ["diff", "-rq", "--exclude=.DS_Store", str(local), str(upstream)],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if out.returncode == 0:
        return False
    if out.returncode == 1:
        return True
    return None


def scan_standalone_skills(agents_dir: Path, fetch: bool):
    """Compare ~/.agents standalone skills against their upstream GitHub repos.

    The lock file records, per skill: sourceUrl (a git repo), skillPath (the
    SKILL.md path inside that repo — its dirname is the skill's folder), and
    install timestamps. No upstream sha is recorded, so update state is a
    content comparison: shallow-clone each distinct repo once, then diff each
    installed folder against its upstream counterpart. A skill whose folder
    vanished upstream is reported removed-upstream (the installer can't update
    what no longer exists — the user should decide to keep or delete it).
    """
    lock = load_json(agents_dir / ".skill-lock.json")
    if not lock or not isinstance(lock.get("skills"), dict):
        return []
    skills = lock["skills"]

    def record(name, rec, status, note=None):
        return {
            "kind": "skill",
            "plugin": name,
            "marketplace": rec.get("source"),
            "repo": rec.get("sourceUrl"),
            "installed_version": None,
            "installed_sha": (rec.get("skillFolderHash") or "")[:10] or None,
            "latest_version": None,
            "latest_sha": None,
            "status": status,
            "note": note,
            "install_path": str(agents_dir / "skills" / name),
            "last_updated": rec.get("updatedAt"),
        }

    if not fetch:
        return [
            record(name, rec, "unknown",
                   "offline: standalone-skill comparison needs to clone the source repo")
            for name, rec in skills.items()
        ]

    # Group by repo so 33 skills from one repo cost one clone, not 33.
    by_repo: dict[str, list] = {}
    for name, rec in skills.items():
        url = rec.get("sourceUrl")
        if url and rec.get("sourceType") == "github":
            by_repo.setdefault(url, []).append((name, rec))
        # Non-github or malformed entries simply never enter the scan.

    results = []
    for url, entries in by_repo.items():
        tmp = tempfile.mkdtemp(prefix="skill-scan-")
        ok, _ = run_git(["clone", "--depth", "1", "--quiet", url, tmp],
                        timeout=CLONE_TIMEOUT)
        if not ok:
            results.extend(
                record(n, r, "unknown", f"could not clone {url}") for n, r in entries
            )
            shutil.rmtree(tmp, ignore_errors=True)
            continue
        try:
            for name, rec in entries:
                # skillPath points at SKILL.md inside the repo; its folder is
                # the unit that gets installed and compared.
                rel = os.path.dirname(rec.get("skillPath") or "")
                upstream = Path(tmp) / rel if rel else Path(tmp)
                local = agents_dir / "skills" / name
                if not upstream.is_dir():
                    results.append(record(
                        name, rec, "removed-upstream",
                        f"{rel or '<repo root>'} no longer exists in {url}"))
                elif not local.is_dir():
                    results.append(record(
                        name, rec, "unknown",
                        "locked but not found on disk under ~/.agents/skills"))
                else:
                    differs = folders_differ(local, upstream)
                    if differs is None:
                        results.append(record(name, rec, "unknown",
                                              "diff against upstream failed"))
                    elif differs:
                        results.append(record(name, rec, "update-available"))
                    else:
                        results.append(record(name, rec, "up-to-date"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return results


def print_table(results):
    order = {"update-available": 0, "removed-upstream": 0, "unknown": 1, "up-to-date": 2}
    marks = {"update-available": "UPDATE", "removed-upstream": "REMOVED",
             "unknown": "?", "up-to-date": "ok"}
    n_upd = sum(r["status"] == "update-available" for r in results)
    n_rm = sum(r["status"] == "removed-upstream" for r in results)
    print(f"\nScanned {len(results)} installed plugin(s)/skill(s) — "
          f"{n_upd} with updates available"
          + (f", {n_rm} removed upstream" if n_rm else "") + ".\n")
    width = max((len(r["plugin"]) for r in results), default=10)
    noted = []
    for kind, title in (("plugin", "Plugins (marketplaces)"),
                        ("skill", "Standalone skills (~/.agents)")):
        group = [r for r in results if r.get("kind", "plugin") == kind]
        if not group:
            continue
        print(f"  {title}")
        for r in sorted(group, key=lambda r: (order.get(r["status"], 9), r["plugin"])):
            mark = marks.get(r["status"], r["status"])
            cur = (r["installed_version"] if r["installed_version"] not in (None, "unknown")
                   else (r["installed_sha"] or "?"))
            new = (r["latest_version"] if r["latest_version"] not in (None, "unknown")
                   else (r["latest_sha"] or "?"))
            arrow = f"{cur} -> {new}" if r["status"] == "update-available" and new != cur else cur
            star = "*" if r.get("note") and r["status"] == "up-to-date" else ""
            print(f"    [{mark:>6}] {r['plugin']:<{width}}  {arrow}{star}")
            if r.get("note") and r["status"] != "up-to-date":
                print(f"             {'':<{width}}  ({r['note']})")
            if star:
                noted.append(r["plugin"])
        print()
    for name in noted:
        print(f"  * {name}: version matches but recorded install sha is stale "
              f"(bookkeeping artifact, not an update)")
    if n_upd:
        print("Plugins: run `/plugin` (or the marketplace's update flow).")
        print("Standalone skills: re-run the skills installer for the repo "
              "(e.g. `npx skills add <owner/repo>`), then re-scan.")
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--claude-dir", default=os.path.expanduser("~/.claude"),
                    help="Path to the .claude config dir (default: ~/.claude)")
    ap.add_argument("--agents-dir", default=os.path.expanduser("~/.agents"),
                    help="Path to the .agents dir holding .skill-lock.json "
                         "(default: ~/.agents)")
    ap.add_argument("--json", action="store_true", help="Emit JSON, not a table")
    ap.add_argument("--no-fetch", dest="fetch", action="store_false",
                    help="Don't git-fetch/clone; plugins compare against local "
                         "clones only, standalone skills report unknown")
    args = ap.parse_args()

    claude_dir = Path(args.claude_dir).expanduser()
    agents_dir = Path(args.agents_dir).expanduser()
    if not (claude_dir / "plugins" / "installed_plugins.json").exists():
        print(f"No installed_plugins.json under {claude_dir}/plugins — "
              "is this the right --claude-dir?", file=sys.stderr)
        sys.exit(2)

    results = scan_plugins(claude_dir, args.fetch)
    results += scan_standalone_skills(agents_dir, args.fetch)
    results.sort(key=lambda r: (r["status"] != "update-available", r["plugin"]))
    if args.json:
        print(json.dumps({"results": results, "fetched": args.fetch}, indent=2))
    else:
        print_table(results)


if __name__ == "__main__":
    main()
