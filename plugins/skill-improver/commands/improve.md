---
description: Improve an existing skill — standard cleanup or a deep, research-backed SOTA pass
---

Load the `skill-improver` skill and run **Workflow 2: Improve a skill** on the
skill the user names in the arguments.

Confirm the depth first:
- **standard** (default) — restructure, tighten prompt quality, fix triggering,
  bundle repeated logic.
- **deep** — the standard pass plus research across web search, Context7 docs,
  the skills marketplace, and GitHub to bring the skill to the state of the art.
  Use this depth if the user said "deep", "SOTA", "best-in-class", or "research it".

Never edit a plugin-cache skill in place (it's overwritten on plugin updates) —
improve a copy. The user's *own* skills (own repo, standalone folder) may be
improved in place. Either way: propose the changes for confirmation before
writing, and explain how to make the improvement persist.
