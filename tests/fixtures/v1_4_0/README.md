Byte-exact v1.4.0 (c09ea43). Never edit; it is what users have installed.

    git archive c09ea43 plugins/skill-improver/skills/skill-improver/assets/lessons-loop \
        plugins/skill-improver/skills/skill-improver/scripts/seed_lessons.py \
        | tar -x -C tests/fixtures/v1_4_0 --strip-components=4

`test_migrate_v140.py` runs this installer to produce a genuine v1.4.0 project and upgrades it with the current one.
