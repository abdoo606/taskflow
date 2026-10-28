# 01 · taskflow — CLI task manager

A dependency-free command line task manager with SQLite storage, typed domain models and 20 tests.

## Why this project
Shows the fundamentals employers probe first: clean layering (models → store → CLI),
explicit transactions, schema versioning, argparse sub-commands, and tests that
don't touch the real filesystem.

## Run
```bash
python -m taskflow add "finish portfolio" --priority high --due +3 --tag work
python -m taskflow list
python -m taskflow start 1
python -m taskflow done 1
python -m taskflow stats
python -m taskflow export --format csv -o tasks.csv
```

## Test
```bash
pytest projects/01-taskflow -q
```

## What it demonstrates
- `dataclass(slots=True)` + `Enum` domain modelling, validation in `__post_init__`
- SQLite with `row_factory`, indexes, parameterised queries (no SQL injection)
- Context manager + rollback-on-error transaction helper
- Pure rendering functions (`render_table`) that are testable without a TTY
