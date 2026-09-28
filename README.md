# ocgc: OpenCode Storage Analyzer & Garbage Collector

[ **English** | [简体中文](README_CN.md) ]

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](pyproject.toml)
[![OpenCode v1 & v2](https://img.shields.io/badge/OpenCode-v1%20%7C%20v2-green.svg)](https://github.com/anomalyco/opencode)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](https://github.com/codehands028/ocgc)
[![Tests](https://img.shields.io/badge/tests-15%20passed-brightgreen.svg)](tests/test_v1_and_v2.py)

Analyze, visualize, and reclaim storage used by [OpenCode](https://github.com/anomalyco/opencode) sessions, diffs, and snapshots. Supports both **OpenCode v1 and v2** schemas natively across **Windows, macOS, and Linux**.

OpenCode stores sessions, messages, and part data in a local SQLite database that grows without bound and has [no built-in cleanup](https://github.com/anomalyco/opencode/issues/4980). It also stores file diffs and git snapshots on disk. As you use OpenCode, thinking tokens (reasoning), snapshots, and historical sessions can easily consume tens of gigabytes of disk space and slow down queries.

`ocgc` provides comprehensive visibility into where your OpenCode storage goes and gives you fine-grained, safe controls to reclaim it.

---

## ⚡ Why This Fork? (Differences from Upstream)

This repository is an enhanced, production-ready fork of the original [whtsky/ocgc](https://github.com/whtsky/ocgc). While the original project laid the groundwork for OpenCode storage inspection, it only supported the legacy OpenCode v1 schema and had significant limitations on non-Unix environments.

OpenCode's major architecture upgrade to **v2** completely redesigned the database schema (introducing `session_v2`, `session_message`, embedded JSON content arrays, and multiple reference tables), causing upstream `ocgc` to fail. Furthermore, Windows users faced path detection issues, process detection crashes, and permission errors during snapshot deletion.

This fork addresses these critical limitations with full v1 & v2 dual-engine compatibility, first-class cross-platform support, and advanced storage analytics:

### 📊 Feature Comparison Matrix

| Feature / Capability | Original Upstream (`whtsky/ocgc`) | This Fork (`codehands028/ocgc`) |
| :--- | :---: | :---: |
| **OpenCode v2 Schema Support** | ❌ Fails (`no such table: session`) | ✅ **Full Support** (`session_v2`, `session_message`, etc.) |
| **OpenCode v1 Schema Support** | ✅ Supported | ✅ **Supported** (100% backwards compatible) |
| **Schema Auto-Detection** | ❌ None (hardcoded v1) | ✅ **Automatic** (dynamic detection of v1 vs v2) |
| **v2 Part Type Storage Analysis** | ❌ Not supported | ✅ **Deep SQLite JSON parsing** (`json_each` array extraction) |
| **v2 Cascading Session Purge** | ❌ Not supported | ✅ **Atomic cascade across 9 tables** with transaction rollback |
| **v2 Reasoning Token Stripping** | ❌ Not supported | ✅ **Full JSON content parsing & token counter reset** |
| **Native Windows Support** | ⚠️ Broken (POSIX paths, pgrep, snapshot permission errors) | ✅ **First-class citizen** (native AppData, tasklist, path normalization) |
| **Windows Read-Only Snapshot Cleanup** | ❌ Fails on git packfiles (`AccessDenied`) | ✅ **Safe `_rmtree_safe`** with `chmod S_IWRITE` attribute clearing |
| **Windows Process Detection** | ❌ Fails (`pgrep` not found) | ✅ **`tasklist` CSV inspection** (`opencode.exe`, `opencode-server.exe`, etc.) |
| **SQLite Read-Only URI Handling** | ⚠️ Fragile string formatting | ✅ **Standard `path.resolve().as_uri()`** across all OSes |
| **Filesystem Orphan Diff Detection** | ⚠️ v1 only | ✅ **v1 & v2 schema-aware orphan detection** |
| **Automated Test Coverage** | ⚠️ Minimal | ✅ **15 comprehensive tests** for v1 & v2 end-to-end workflows |

---

## 📸 Screenshots

### Storage Dashboard (`ocgc status`)
Database size, WAL journal, filesystem diffs/snapshots, and colorful part-type breakdown:

![status](screenshots/status.png)

### Deep Storage Analytics (`ocgc analyze`)
Top 10 largest sessions, root vs subagent space consumption, growth rate (MB/active day), and orphan files:

![analyze](screenshots/analyze.png)

### Safe Dry-Run Purge (`ocgc purge --dry-run`)
Detailed preview of sessions, messages, parts, and diff files to be reclaimed:

![purge](screenshots/purge.png)

---

## 🚀 Quick Start

### Feed this prompt to your AI Agent
If you are using Claude Code, OpenCode, Cursor, or another agent, simply copy:

```
Read https://raw.githubusercontent.com/codehands028/ocgc/refs/heads/main/README.md and help me analyze and garbage collect my OpenCode storage.
```

---

## 📦 Installation

### Recommended (via uv)

Run directly without installing (zero setup):

```bash
uvx --from git+https://github.com/codehands028/ocgc.git ocgc status
```

Install as a permanent global tool:

```bash
uv tool install git+https://github.com/codehands028/ocgc.git
```

### Via pipx

```bash
pipx install git+https://github.com/codehands028/ocgc.git
```

### Via pip

```bash
pip install git+https://github.com/codehands028/ocgc.git
```

---

## 🔍 Core Features & Usage Guide

### 1. Storage Inspection & Analytics

#### High-Level Dashboard
```bash
ocgc status
```
Displays:
- Database path & detected schema version (**OpenCode v1** or **OpenCode v2**)
- SQLite file size, WAL journal size, and combined DB footprint
- Filesystem storage usage: session diffs, snapshot projects, and tool outputs
- Root sessions vs Subagent sessions count
- **Storage by Part Type bar chart**: visual breakdown of space consumed by `reasoning`, `tool`, `text`, `patch`, `compaction`, etc.
- **Session Age Distribution**: histogram of session ages (<24h, 1-7d, 7-14d, 14-30d, >30d)

#### Session Explorer
```bash
# List sessions sorted by size (default: largest first)
ocgc sessions --limit 20

# Sort by age or name
ocgc sessions --sort age --limit 20
ocgc sessions --sort name
```
Outputs a table with Session ID, working directory, session title, size, creation age, type (`root` or `subagent`), and message count.

#### Deep Storage Analysis
```bash
ocgc analyze
```
Outputs:
- Top 10 largest sessions across all workspaces
- Average session storage footprint
- **Estimated Growth Rate**: average storage increase (MB) per active day of usage
- **Root vs Subagent Comparison**: breakdown of messages and bytes consumed by parent sessions vs delegated subagents
- **Orphan Diff Scanner**: identifies session diff files on disk that have no matching session in the database

---

### 2. Surgical Garbage Collection (`ocgc purge`)

`ocgc purge` provides fine-grained, composable filters. Multiple filters combine with **AND** logic.

> 💡 **Safety First**: By default, `ocgc purge` will always display a detailed summary of what will be affected and ask for confirmation before making changes. Use `--dry-run` to preview without touching anything.

#### Previewing Purges
```bash
# Preview deleting sessions older than 14 days
ocgc purge --older-than 14d --dry-run
```

#### Strip Reasoning Tokens (Biggest Space Saver! 💥)
Thinking and reasoning tokens produced by reasoning models (like Claude 3.7 Sonnet Thinking, o1, etc.) can account for **70%–80%** of total storage:

```bash
# Strip reasoning tokens from ALL sessions (keeps conversation messages, tools, and history intact)
ocgc purge --strip-reasoning

# Strip reasoning tokens only from sessions older than 7 days
ocgc purge --strip-reasoning --older-than 7d
```
*Note: In OpenCode v2, `ocgc` cleans up embedded reasoning objects within messages, resets `tokens.reasoning` metadata, and clears `session_v2.tokens_reasoning` counters.*

#### Purging by Age, Type, or Size
```bash
# Delete subagent sessions older than 7 days (leaves root sessions intact)
ocgc purge --subagents --older-than 7d

# Delete sessions larger than 50MB
ocgc purge --larger-than 50M

# Keep only the 50 most recent sessions, purge older ones
ocgc purge --keep-latest 50

# Purge a specific session by ID
ocgc purge --session ses_01955c4d32a078b5a03e1e24748ef534
```

#### Filesystem Storage Cleaning
```bash
# Clean orphan session diff files (diff files left behind after DB records were removed)
ocgc purge --clean-orphans

# Delete all git snapshot repositories (recreated automatically by OpenCode when needed)
ocgc purge --clean-snapshots
```

#### Batch Execution & Non-Interactive Mode
```bash
# Combine multiple cleanup operations with non-interactive confirmation (--force)
ocgc purge --clean-orphans --clean-snapshots --subagents --older-than 14d --force
```

---

### 3. Reclaim Physical Disk Space (`ocgc vacuum`)

SQLite does not automatically shrink its `.db` file when rows are deleted; it retains empty pages for future writes. Run `vacuum` to release free space back to the operating system:

```bash
ocgc vacuum
```
*Shows disk usage before and after, as well as exact megabytes reclaimed.*

---

## 🗄️ Understanding OpenCode Storage Architecture

To effectively manage OpenCode's footprint, `ocgc` analyzes two storage domains:

```
~/.local/share/opencode/                  (or %LOCALAPPDATA%\opencode on Windows)
├── opencode.db                          <- Main SQLite Database (Sessions, Messages, Parts, Events)
├── opencode.db-wal                      <- SQLite Write-Ahead Log
├── storage/
│   └── session_diff/                    <- Session Diffs (*.json, contains full file diffs per session)
├── snapshot/                            <- Git Object Packs per project workspace
└── tool-output/                         <- Ephemeral outputs from executed terminal tools
```

1. **SQLite Database (`opencode.db`)**:
   - **v1 Schema**: `session`, `message`, `part`, `todo`, `session_share`.
   - **v2 Schema**: `session_v2`, `session_message`, `session_inbox`, `session_pending`, `instruction_entry`, `instruction_state`, `todo`, `session_share`, `event`, `event_sequence`.
2. **Session Diffs (`storage/session_diff/`)**:
   - Full JSON diff snapshots of modified files during each session. Purging a session automatically deletes its corresponding `.json` diff file.
3. **Snapshots (`snapshot/`)**:
   - Git packfile trees created by OpenCode to track workspace states before file operations.
4. **Tool Output (`tool-output/`)**:
   - Command output dumps from tool runs.

---

## 🛡️ Safety & Reliability Guarantees

- **Read-Only by Default**: Commands `status`, `sessions`, and `analyze` open SQLite in strict read-only mode (`?mode=ro`) and never modify files.
- **Active Process Detection**: Automatically alerts you if OpenCode is currently running (`pgrep` on Unix, `tasklist` CSV on Windows) to prevent concurrent write collisions or database locking.
- **Atomic Transactions & Rollback**: In OpenCode v2, session deletion across all 9 related tables runs within an atomic transaction. Any error triggers an immediate rollback to preserve database integrity.
- **Safe Directory Purging**: Snapshot directory cleanup on Windows properly handles read-only git pack files (`_rmtree_safe` with `chmod S_IWRITE`) without throwing `PermissionError`.
- **Confirmation Prompts**: Purge and vacuum operations require interactive confirmation unless explicitly bypassed via `--force`.

---

## ⚙️ Environment Variables & Configuration

| Environment Variable | Description | Default |
| :--- | :--- | :--- |
| `OCGC_DB_PATH` | Explicit path to `opencode.db` | Auto-detected |
| `OPENCODE_DATA` | OpenCode data directory path | Auto-detected |
| `OCGC_SKIP_RUNNING_CHECK` | Set to `1` to bypass the running OpenCode process check | `0` |

### Default Database Locations by Platform
- **Windows**: `%LOCALAPPDATA%\opencode\opencode.db` (or `%USERPROFILE%\AppData\Local\opencode\opencode.db`)
- **Linux & macOS**: `$XDG_DATA_HOME/opencode/opencode.db` (fallback to `~/.local/share/opencode/opencode.db`)

Custom database path example:
```bash
export OCGC_DB_PATH=/custom/path/opencode.db
ocgc status
```

---

## 🧪 Testing

The test suite validates both OpenCode v1 and v2 schemas, auto-detection, queries, cascading purges, reasoning stripping, orphan diff detection, and CLI interfaces:

```bash
uv run pytest
```

---

## 🤝 Attribution & Acknowledgements

This project is an independent fork of [whtsky/ocgc](https://github.com/whtsky/ocgc) created by [Wu Haotian](https://github.com/whtsky). We thank the original author for creating the initial foundation and inspiring OpenCode storage management.

Key enhancements in this fork:
- Full OpenCode v2 database schema architecture support
- Enterprise-grade cross-platform compatibility (Windows, macOS, Linux)
- Safe 9-table cascading deletion & transaction rollbacks
- v2 message JSON reasoning stripping and token resets
- Robust Windows git snapshot permission handling

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
