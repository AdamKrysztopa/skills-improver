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

Always work on a writable copy (never edit a plugin cache in place), propose the
changes for confirmation, and explain how to make the improvement persist.
