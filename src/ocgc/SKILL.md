---
name: ocgc
description: Use when analyzing OpenCode storage, inspecting SQLite database size, cleaning up disk space, purging old sessions, stripping reasoning tokens, removing orphan diffs, or clearing snapshots in OpenCode.
license: MIT
---

# ocgc: OpenCode Storage Analyzer & Garbage Collector

## Overview

OpenCode maintains its historical sessions, messages, part data, and reasoning tokens in a local SQLite database that grows continuously without automatic garbage collection. Large reasoning parts and git snapshots can consume tens of gigabytes of disk space and cause query latency.

`ocgc` provides safe, granular inspection and cleanup for both **OpenCode v1 and v2** databases across macOS, Linux, and Windows.

## When to Use

- When disk space is low and OpenCode data directories consume gigabytes
- When OpenCode becomes sluggish during startup or session loading
- When inspecting which sessions or subagents consume the most storage
- When stripping bulky reasoning tokens (thinking parts) while keeping chat history intact
- When removing stale sessions older than a specific timeframe (e.g. 14 days, 30 days)
- When cleaning up sessions or snapshots scoped to a specific project or workspace directory
- When cleaning up orphan session diffs or git snapshot directories

## When NOT to Use

- When OpenCode is actively running heavy tasks with uncommitted edits (close or pause OpenCode before modifying the database).
- When the user wants to clear git project files in their workspace rather than OpenCode's internal data directory (`~/.local/share/opencode`, `~/.config/opencode`, or `%LOCALAPPDATA%\opencode`).

## Quick Reference

| Action | Command |
| :--- | :--- |
| **Check Dashboard** | `uvx --from git+https://github.com/codehands028/ocgc.git ocgc status` |
| **Deep Analysis** | `uvx --from git+https://github.com/codehands028/ocgc.git ocgc analyze` |
| **List Top 10 Sessions** | `uvx --from git+https://github.com/codehands028/ocgc.git ocgc sessions --sort size -l 10` |
| **Filter by Project/Dir** | `uvx --from git+https://github.com/codehands028/ocgc.git ocgc sessions --project <name>` |
| **Preview Purge (Dry-run)** | `uvx --from git+https://github.com/codehands028/ocgc.git ocgc purge --older-than 30d --dry-run` |
| **Targeted Project Purge**| `uvx --from git+https://github.com/codehands028/ocgc.git ocgc purge --project <name> --dry-run` |
| **Strip Reasoning Only** | `uvx --from git+https://github.com/codehands028/ocgc.git ocgc purge --strip-reasoning` |
| **Flush & Reset WAL Log** | `uvx --from git+https://github.com/codehands028/ocgc.git ocgc checkpoint` |
| **Reclaim SQLite Disk Space**| `uvx --from git+https://github.com/codehands028/ocgc.git ocgc vacuum` |

> *Note: If `ocgc` is installed globally via `uv tool install` or `pipx`, replace the `uvx ...` prefix with `ocgc`.*

---

## Recommended Workflow

Always follow the **Inspect -> Dry-Run -> Purge -> Checkpoint / Vacuum** sequence to prevent unintended data loss.

### 1. Inspect Storage State

Run `status` and `analyze` to understand current disk distribution:

```bash
ocgc status
ocgc analyze
```

Review:
- SQLite DB size vs WAL journal size
- Space occupied by `reasoning` vs `text` vs snapshots
- Top largest sessions

### 2. Preview Before Deletion (Always use `--dry-run`)

Test your filter criteria with `--dry-run` (`-n`) before deleting anything:

```bash
# Preview deleting sessions older than 30 days
ocgc purge --older-than 30d --dry-run

# Preview deleting sessions larger than 50MB
ocgc purge --larger-than 50M --dry-run

# Preview deleting sessions for a specific project or directory
ocgc purge --project legacy-repo --dry-run
ocgc purge --directory ~/Projects/legacy-repo --dry-run

# Preview cleaning orphan diffs and snapshots
ocgc purge --clean-orphans --clean-snapshots --dry-run
```

### 3. Execute Target Purge

Once confirmed, execute the purge without `--dry-run`. Interactive confirmation is requested by default (use `-f` / `--force` for non-interactive automation):

```bash
# Delete old sessions
ocgc purge --older-than 30d

# Or strip reasoning tokens across all sessions without losing message history
ocgc purge --strip-reasoning

# Or clean only subagents (spawned child sessions)
ocgc purge --subagents

# Or clean sessions / snapshots for a specific project
ocgc purge --project legacy-repo
ocgc purge --clean-snapshots --project legacy-repo
```

### 4. Fast WAL Checkpoint (`ocgc checkpoint`)

SQLite in Write-Ahead Logging (WAL) mode appends write transactions into `opencode.db-wal`. To synchronously flush WAL frames into `opencode.db` and reset the WAL file to 0 bytes in milliseconds without running a slow VACUUM:

```bash
ocgc checkpoint
```

### 5. Shrink SQLite File (VACUUM)

Deleting rows in SQLite marks pages as free but does not shrink the `.db` file on disk. Run `vacuum` to physically reclaim the storage:

```bash
ocgc vacuum
```

**Prerequisites for VACUUM:**
- OpenCode must NOT be running (ensure no locks).
- Free disk space must be at least equal to the current database size during compaction.

---

## Detailed Purge Options

Filters can be combined:

- `--older-than <duration>`: Duration string (`15m`, `1h`, `7d`, `2w`, `1mo`).
- `--larger-than <size>`: Size string (`50M`, `1G`, `500K`).
- `--keep-latest <N>`: Retain the most recent `N` sessions and purge older ones.
- `--subagents`: Only target subagent sessions (`parent_id IS NOT NULL`).
- `--strip-reasoning`: Remove bulky reasoning parts without deleting the session records.
- `--session <ID>`: Target specific session IDs (repeatable).
- `--clean-snapshots`: Remove git snapshot cache directories.
- `--clean-orphans`: Remove orphaned session diff files not referenced in the DB.
- `--clean-tool-output`: Remove cached tool execution output files.

---

## Common Mistakes & Troubleshooting

| Problem | Cause | Solution |
| :--- | :--- | :--- |
| `Database is locked` | OpenCode is running in the background | Terminate `opencode` / `opencode-server` processes before running `purge` or `vacuum`. |
| WAL log (`opencode.db-wal`) is huge | SQLite retains unmerged WAL frames | Run `ocgc checkpoint` to immediately flush and truncate WAL to 0 bytes. |
| DB size didn't decrease after `purge` | SQLite keeps free pages internally | Run `ocgc vacuum` to compact the database file. |
| `Insufficient disk space for VACUUM` | SQLite creates a copy during vacuum | Free temporary space elsewhere, or move the DB to an external drive temporarily. |
| Windows permission error on snapshots | Git packfiles are marked read-only | `ocgc` automatically clears read-only attributes with `_rmtree_safe`; ensure no editor holds file locks. |
