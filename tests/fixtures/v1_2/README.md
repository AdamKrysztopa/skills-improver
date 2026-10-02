Byte-for-byte snapshot of the v1.2.0 installer and its assets, from commit 6f19174:

    git show 6f19174:plugins/skill-improver/skills/skill-improver/scripts/seed_lessons.py
    git archive 6f19174 plugins/skill-improver/skills/skill-improver/assets

Tests run this installer to produce a genuine v1.2-seeded project, then upgrade it with the
current one. Do not edit these files; `test_migrate_v12.py` checks them against the git object.
