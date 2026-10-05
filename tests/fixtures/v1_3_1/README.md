Byte-exact v1.3.1 (588a75d). Never edit; it is what users have installed.

    git archive 588a75d plugins/skill-improver/skills/skill-improver/assets/lessons-loop \
        plugins/skill-improver/skills/skill-improver/scripts/seed_lessons.py \
        | tar -x -C tests/fixtures/v1_3_1 --strip-components=4

`test_migrate_v131.py` runs this installer to produce a genuine v1.3.1 project and upgrades it with the current one.
