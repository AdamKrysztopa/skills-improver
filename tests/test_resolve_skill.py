"""resolve_skill: where a skill lives decides whether it may be edited in place."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins/skill-improver/skills/skill-improver/scripts"
_spec = importlib.util.spec_from_file_location("resolve_skill", SCRIPTS / "resolve_skill.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


class Resolve(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name).resolve()
        self.claude, self.agents = base / ".claude", base / ".agents"
        (self.claude / "skills").mkdir(parents=True)
        (self.agents / "skills").mkdir(parents=True)

    def kinds(self, name):
        return [r["kind"] for r in R.resolve(name, self.claude, self.agents)]

    def test_own_directory(self):
        (self.claude / "skills/mine").mkdir()
        self.assertEqual(self.kinds("mine"), ["own-standalone"])

    def test_symlink_into_agents_tree_with_lock_provenance(self):
        (self.agents / "skills/cli").mkdir()
        os.symlink(self.agents / "skills/cli", self.claude / "skills/cli")
        (self.agents / ".skill-lock.json").write_text(json.dumps(
            {"skills": {"cli": {"sourceUrl": "https://example.invalid/r.git", "updatedAt": "2026-01-01"}}}))
        [hit] = R.resolve("cli", self.claude, self.agents)
        self.assertEqual(hit["kind"], "agents-standalone")
        self.assertEqual(hit["lock_source"], "https://example.invalid/r.git")

    def test_symlink_into_plugin_cache_and_cache_hit(self):
        cached = self.claude / "plugins/cache/mkt/plug/1.0.0/skills/cached"
        cached.mkdir(parents=True)
        os.symlink(cached, self.claude / "skills/cached")
        hits = R.resolve("cached", self.claude, self.agents)
        self.assertEqual([h["kind"] for h in hits], ["plugin-cache", "plugin-cache"])
        self.assertEqual(hits[1]["plugin"], "plug")

    def test_dangling_symlink_is_reported_not_crashed(self):
        os.symlink(self.claude / "nowhere", self.claude / "skills/ghost")
        [hit] = R.resolve("ghost", self.claude, self.agents)
        self.assertFalse(hit["exists"])

    def test_agents_prefix_lookalike_is_not_agents(self):
        lookalike = self.agents.parent / ".agents-other/skills/x"
        lookalike.mkdir(parents=True)
        os.symlink(lookalike, self.claude / "skills/x")
        self.assertEqual(self.kinds("x"), ["own-standalone"])

    def test_missing(self):
        self.assertEqual(R.resolve("absent", self.claude, self.agents), [])


if __name__ == "__main__":
    unittest.main()
