Byte-exact v1.4.1 (634a5c6). Never edit; it is what users have installed.

    git archive 634a5c6 plugins/skill-improver/skills/skill-improver/assets/lessons-loop \
        plugins/skill-improver/skills/skill-improver/scripts/seed_lessons.py \
        | tar -x -C tests/fixtures/v1_4_1 --strip-components=4

`test_migrate_v141.py` runs this installer to produce a genuine v1.4.1 project and upgrades it with the current one.
