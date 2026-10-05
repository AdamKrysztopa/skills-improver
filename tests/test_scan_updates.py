"""scan_updates: ordering, stale-fetch handling, and the snapshot exception."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins/skill-improver/skills/skill-improver/scripts"
_spec = importlib.util.spec_from_file_location("scan_updates", SCRIPTS / "scan_updates.py")
U = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(U)


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})


def manifest(version: str) -> str:
    return json.dumps({"plugins": [{"name": "p", "source": "./plugins/p", "version": version}]})


class Compare(unittest.TestCase):
    def test_ordering(self):
        cases = [("1.3.1", "1.3.1", "up-to-date"), ("1.3.1", "1.4.0", "update-available"),
                 ("1.4.0", "1.3.1", "up-to-date"), ("1.3", "1.3.0", "up-to-date"),
                 ("v1.2.0", "1.10.0", "update-available"), ("1.4.0-rc1", "1.4.0", "update-available")]
        for installed, latest, want in cases:
            with self.subTest(installed=installed, latest=latest):
                self.assertEqual(U.compare(installed, None, latest, None), want)

    def test_sha_fallback_and_unknown(self):
        self.assertEqual(U.compare(None, "a" * 40, None, "a" * 40), "up-to-date")
        self.assertEqual(U.compare(None, "a" * 40, None, "b" * 40), "update-available")
        self.assertEqual(U.compare(None, None, None, None), "unknown")


class StaleFetch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.upstream = base / "upstream"
        (self.upstream / ".claude-plugin").mkdir(parents=True)
        (self.upstream / ".claude-plugin/marketplace.json").write_text(manifest("1.0.0"))
        git(self.upstream, "init", "-q", "-b", "main")
        git(self.upstream, "add", ".")
        git(self.upstream, "commit", "-qm", "v1")
        self.clone = base / "clone"
        git(base, "clone", "-q", str(self.upstream), str(self.clone))

    def test_successful_fetch_sees_the_new_version(self):
        (self.upstream / ".claude-plugin/marketplace.json").write_text(manifest("1.1.0"))
        git(self.upstream, "commit", "-qam", "v1.1")
        m, stale = U.latest_manifest(self.clone, True)
        self.assertFalse(stale)
        self.assertEqual(m["plugins"][0]["version"], "1.1.0")

    def test_failed_fetch_is_reported_stale(self):
        git(self.clone, "remote", "set-url", "origin", str(self.upstream) + "-gone")
        m, stale = U.latest_manifest(self.clone, True)
        self.assertTrue(stale)
        self.assertEqual(m["plugins"][0]["version"], "1.0.0")

    def test_no_fetch_requested_is_not_stale(self):
        _, stale = U.latest_manifest(self.clone, False)
        self.assertFalse(stale)

    def test_snapshot_marketplace_is_not_marked_stale(self):
        snap = Path(self._tmp.name) / "snapshot"
        (snap / ".claude-plugin").mkdir(parents=True)
        (snap / ".claude-plugin/marketplace.json").write_text(manifest("1.0.0"))
        m, stale = U.latest_manifest(snap, True)
        self.assertFalse(stale)
        self.assertEqual(m["plugins"][0]["version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
