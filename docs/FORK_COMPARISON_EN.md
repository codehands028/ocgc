# Differences from Upstream

This document records how this repository differs from the upstream project
[whtsky/ocgc](https://github.com/whtsky/ocgc).

This project began as a fork of `whtsky/ocgc`. Upstream stopped being maintained after
2026-04-15, supported only the OpenCode v1 schema, and had limitations on non-Unix platforms.
When OpenCode moved to **v2**, the database schema was redesigned (`session_v2`,
`session_message`, embedded JSON content arrays, multiple reference tables), which upstream
does not handle.

The main README focuses on what the tool does and how to use it. The fork comparison lives here
so it does not interrupt a first-time reader. See the [Chinese version](FORK_COMPARISON.md) for
the equivalent document.

---

## 📊 Capability comparison

| Capability | Upstream (`whtsky/ocgc`) | This repository (`codehands028/ocgc`) |
| :--- | :---: | :---: |
| **OpenCode v2 schema support** | ❌ Fails (`no such table: session`) | ✅ **Full support** (`session_v2`, `session_message`, etc.) |
| **OpenCode v1 schema support** | ✅ Supported | ✅ **Supported** (backwards compatible) |
| **Schema auto-detection** | ❌ None (hardcoded v1) | ✅ **Automatic** (dynamic v1 vs v2 detection) |
| **v2 part type storage analysis** | ❌ Not supported | ✅ **Deep SQLite JSON parsing** (`json_each` array extraction) |
| **v2 cascading session purge** | ❌ Not supported | ✅ **Atomic cascade across 9 tables** with transaction rollback |
| **v2 reasoning token stripping** | ❌ Not supported | ✅ **Full JSON content parsing & token counter reset** |
| **Native Windows support** | ⚠️ Broken (POSIX paths, `pgrep`, snapshot permission errors) | ✅ **First-class** (native AppData, `tasklist`, path normalization) |
| **Windows read-only snapshot cleanup** | ❌ Fails on git packfiles (`AccessDenied`) | ✅ **Safe `_rmtree_safe`** clearing `chmod S_IWRITE` |
| **Windows process detection** | ❌ Fails (`pgrep` not found) | ✅ **`tasklist` CSV inspection** (`opencode.exe`, `opencode-server.exe`, etc.) |
| **SQLite read-only URI handling** | ⚠️ Fragile string formatting | ✅ **Standard `path.resolve().as_uri()`** across all OSes |
| **Filesystem orphan diff detection** | ⚠️ v1 only | ✅ **v1 & v2 schema-aware orphan detection** |
| **Tool output cache cleanup** | ❌ None | ✅ **Native** (`--clean-tool-output`, with age filter & safety checks) |
| **Targeted project & directory scope** | ❌ None | ✅ **Native** (`--project`, `--directory` across `sessions` & `purge`) |
| **Project-level storage dashboard** | ❌ None | ✅ **Native** (`ocgc projects` aggregating sessions, data & snapshots) |
| **Lightweight WAL checkpoint** | ❌ None | ✅ **Millisecond reset** (`ocgc checkpoint`, TRUNCATE mode) |
| **Large content / media truncation** | ❌ None | ✅ **Native** (`--strip-large-outputs` with `--threshold`) |
| **Session Markdown export & archive** | ❌ None | ✅ **Full GFM export** (`ocgc export`, `purge --archive-to`) |
| **Database health check & diagnostics** | ❌ None | ✅ **`ocgc doctor`** (integrity, WAL bloat, dangling rows, permissions) |
| **Structured JSON output** | ❌ None | ✅ **Native** (`status` / `sessions` / `analyze` / `projects` / `doctor`) |
| **Interactive terminal selector** | ❌ None | ✅ **Native** (`ocgc browse`, TUI keyboard tagging & preview) |
| **OpenCode native skill integration** | ❌ None | ✅ **Built-in** (`ocgc install-skill`) |
| **Automated test coverage** | ⚠️ Minimal | ✅ **126 tests** covering v1 and v2 end-to-end flows |

---

## 🤝 Acknowledgements and collaboration

Originally created by [Wu Haotian (whtsky)](https://github.com/whtsky) as
[whtsky/ocgc](https://github.com/whtsky/ocgc). Thanks for laying the groundwork for OpenCode
storage management.

Upstream has not been updated since 2026-04-15, and several feature requests and pull requests
remain open there. The work in this repository was not intended as a replacement — the lack of
v2 schema support simply means the upstream version no longer runs against current OpenCode
releases.

If these changes are useful upstream, contributions and discussion are welcome. Relevant
upstream threads:

- [Upstream issue #3 — event-table awareness (6 comments)](https://github.com/whtsky/ocgc/issues/3)
- [Upstream issue #5 — mismatch between DB size and ocgc summary](https://github.com/whtsky/ocgc/issues/5)

---

## 📄 License

MIT License. See [LICENSE](../LICENSE) for details.