# Update Detection — how the scan works & where it can't reach

Background for when `scan_updates.py` errors, reports something surprising, or
you need to check a source it doesn't cover.

## The four files the scan reads

1. `~/.claude/plugins/installed_plugins.json` — every installed plugin, keyed
   `name@marketplace`, with the installed `version`, `gitCommitSha`, and
   `installPath`.
2. `~/.claude/plugins/known_marketplaces.json` — each marketplace's GitHub
   `repo` and its local clone/snapshot `installLocation`.
3. `<installLocation>/.claude-plugin/marketplace.json` — the marketplace's
   manifest: the source of truth for the *latest* declared version/sha of every
   plugin it offers.
4. `~/.agents/.skill-lock.json` — standalone-skill install record (v3): per
   skill, the `sourceUrl` git repo, the `skillPath` of its SKILL.md inside that
   repo, a `skillFolderHash`, and install timestamps. This is what the
   `npx skills` installer writes; the skills themselves live in
   `~/.agents/skills/<name>/` and are symlinked into `~/.claude/skills/`.

## How "update available" is decided — plugins

For each installed plugin, the script finds its entry in the marketplace
manifest and compares identities:

- **version vs version wins when both sides carry a version.** The installed
  record's `gitCommitSha` has a known staleness mode: installers can bump the
  recorded version without refreshing the recorded sha (observed in the wild:
  superpowers recorded 6.2.0 alongside the 6.1.1-era sha → a sha-first
  comparison cried UPDATE forever). Version strings are maintained on both
  sides; recorded shas are not.
- **sha vs sha** — the fallback when either side has no version (e.g. the
  manifest pins only `source.sha`, or local-path plugins compared against the
  repo HEAD).
- **Tag-resolution disambiguation** — when the manifest pins only a sha but the
  installed side has a version (url-sourced plugins like superpowers), a bare
  sha mismatch is NOT reported as an update. The script `git ls-remote --tags`
  the upstream repo and resolves the installed version to a commit (`v6.2.0^{}`
  etc.); if that commit equals the pin, the record is simply stale → up-to-date
  with a note. No matching tag → `unknown`, not a guessed UPDATE.
- **repo-HEAD fallback** — when a plugin's manifest entry is a bare local path
  (`source: "./plugins/foo"`) with no version or sha, the plugin lives *inside*
  the marketplace repo, so the repo's HEAD sha is its effective version. For
  **snapshot marketplaces** the comparison target is the snapshot's `.gcs-sha`,
  not the live repo HEAD: the snapshot is what an update would actually
  deliver, and the live HEAD can sit ahead of it (flagging that gap right
  after the user updated is cry-wolf — they can't act on it). HEAD-fallback
  results carry a caveat note: any commit anywhere in that repo advances the
  target, so the plugin's own content may be unchanged.
- **Refresh-timestamp disambiguation** — snapshot marketplaces again: the
  plugin system refreshes a plugin from the current snapshot but leaves the
  record's `gitCommitSha` stale (observed live: four official plugins flagged
  UPDATE seconds after being updated). If the record's `lastUpdated` is at or
  after the snapshot's download time (`.gcs-sha` mtime), the installed content
  provably IS the snapshot → up-to-date with a bookkeeping note, never UPDATE.

## Marketplace clones vs snapshots

Marketplaces used to be plain git clones. The plugin system now sometimes
installs them as **snapshots** — a plain file tree with a `.gcs-sha` marker
(the marketplace repo sha the snapshot was taken from) and no `.git`. The scan
handles both:

- Clone: `git fetch` + read the manifest from `origin/<branch>` — the true
  remote latest. HEAD via `rev-parse origin/<branch>`.
- Snapshot: the worktree manifest IS the latest the plugin system knows about
  (it refreshes the snapshot on its own update checks). HEAD via live
  `git ls-remote https://github.com/<repo>.git HEAD` when online, else the
  `.gcs-sha` marker.

Without fetch (`--no-fetch`), clones compare against whatever they have locally
(possibly stale) and snapshots compare against their `.gcs-sha` — say so in the
report. A stale local clone can report an installed version as *newer* than the
manifest (a false "update available") or miss a real update.

## How "update available" is decided — standalone skills (~/.agents)

The lock file records no upstream sha, so update state is a **content
comparison**: for each distinct `sourceUrl` repo, the script shallow-clones it
(`git clone --depth 1`) into a temp dir, then `diff -rq`s each installed skill
folder against its upstream counterpart (the dirname of `skillPath`). Statuses:

- `up-to-date` — folders identical.
- `update-available` — folders differ (upstream moved, or the local copy was
  edited — either way, worth surfacing).
- `removed-upstream` — the skill's folder no longer exists in the source repo.
  The installer can't update what no longer exists; the user should decide to
  keep the local copy or delete it.
- `unknown` — offline (`--no-fetch` skips cloning entirely) or the clone/diff
  failed.

The comparison deliberately diffs file trees instead of trusting
`skillFolderHash`, so it doesn't depend on reverse-engineering the installer's
hash recipe.

## What the scan deliberately does NOT do

- It does not update anything. Updating plugins is a native Claude Code
  operation (`/plugin`); updating standalone skills is the skills installer's
  job (e.g. `npx skills add <owner/repo>`). Editing the versioned plugin cache
  directly is pointless because the plugin system overwrites it.
- It does not cover sources outside these four files (e.g. a skill the user
  hand-copied from somewhere). If a skill has no lock entry and no plugin
  record, ask where it came from and check that origin manually; don't
  fabricate a version.

## Failure modes to expect

- **Network/offline**: fetch/clone failures degrade per-source to `unknown`
  with a note — say so in the report ("couldn't reach source for X").
- **`?` status**: not an error — it means neither side exposed a comparable
  identity (common for local-path plugins whose installed record has no
  `gitCommitSha`), or a sha mismatch that tag resolution couldn't disambiguate.
- **Stale-record notes (`ok*`)**: up-to-date with a footnote means the version
  is current but the recorded install sha disagrees with the source — a
  bookkeeping artifact of the installer, not something to act on.
- **HEAD-proxy updates**: local-path plugins flagged UPDATE because the
  marketplace repo advanced. Real signal, coarse resolution — the flagged
  plugin's own files may be untouched. The note says so; don't over-promise.
