# Contributing to ocgc

## Reporting bugs

Use the issue templates. Include the output of `ocgc --version` and `ocgc doctor` — most
schema-related questions are answered by those two commands.

## Development setup

This project uses [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/codehands028/ocgc.git
cd ocgc
uv sync
```

## Before opening a pull request

Run these locally and make sure they pass:

```bash
uv run ruff check src/ tests/
uv run mypy src tests
uv run pytest
```

These are the same checks `.github/workflows/ci.yml` defines. **Treat them as required even if
you have not seen a CI run on your branch** — CI may be disabled on the fork, in which case
nothing will catch a regression for you.

When CI is active it runs the test suite on Linux, macOS, and Windows across Python 3.10–3.13.
If your change touches path handling, process detection, or file permissions, please verify on
more than one platform, since those are the areas that historically diverge.

## Working on the database layer

`src/ocgc/db.py` handles both the v1 and v2 OpenCode schemas. Two rules to keep in mind:

1. **Never assume a table or column exists.** OpenCode's schema evolves between versions, and
   this tool is routinely run against DBs it did not create. Guard new queries with a column or
   table existence check (see `_table_columns`) rather than letting them raise.
2. **Read-only by default.** `status`, `sessions`, `analyze`, `projects`, `doctor`, and `export`
   must never write — they connect via `db.connect(readonly=True)` (`?mode=ro`). Only `purge`,
   `checkpoint`, and `vacuum` open the database for writing, and anything that mutates data must
   go through an explicit transaction so a partial failure rolls back.

## Schema drift

If OpenCode adds, removes, or renames tables, prefer discovering them at runtime over adding
another hardcoded name. Storage accounting should degrade gracefully when a table is missing
rather than silently reporting a wrong total — an undercount is what this tool is meant to fix.