Earlier shipped versions of the generated files whose assets have since changed.

`seed_lessons.py --upgrade` refreshes a file only if it is the current version or one of these. Any
other content is the project's own edit (the drain amends these very files on purpose) and is kept.

When a release changes a generated asset, copy the previous version here and list it under
`legacy` in `planned_files`. `tests/test_migrate_v12.py` fails if a pristine v1.2 install still has
a file the upgrade would keep.
