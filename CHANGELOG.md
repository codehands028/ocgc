# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Windows CI: two tests assumed POSIX semantics and failed on every Windows
  runner. This was never caught before because Actions had been disabled on this
  fork since it was created, so the platform matrix had never actually run.
  `test_doctor_snapshot_dir_itself_readonly` is now skipped on Windows
  (`os.chmod` cannot clear write access on a Windows directory), and
  `test_purge_strip_reasoning_with_archive_dry_run` no longer depends on Rich
  panel width by pinning `COLUMNS`. No product code changed.

### Internal

- Added `workflow_dispatch` to CI so the platform matrix can be re-run from the
  Actions tab without pushing a commit.

## [0.4.2] - 2026-10-07

Maintenance release focused on project health and documentation accuracy.
No user-facing command behaviour changed.

### Fixed

- Resolved 5 `mypy --strict` errors that were failing the lint job, so CI is green
  for the first time on this branch.
- `format_bytes` is no longer re-exported through `ocgc.display`. It now lives in
  a dedicated leaf module, `ocgc.units`, and is imported directly by `display`,
  `doctor`, and `purger`. `ocgc.db.format_bytes` remains importable.
- README badges: test count corrected from a stale hardcoded count to the actual
  111, and the badge no longer deep-links to a single test file. Added a real CI
  badge.

### Added

- GitHub issue templates (bug report, feature request) with a routing config that
  redirects v1-only and OpenCode-core questions to the right repository.
- `CONTRIBUTING.md` documenting the local checks, the database-layer rules, and
  the expectation to verify path/permission changes on more than one platform.
- `docs/FORK_COMPARISON.md` (Chinese) and `docs/FORK_COMPARISON_EN.md` (English),
  moved out of the main README so the first screen stays focused on usage.

### Changed

- README: the fork-vs-upstream comparison matrix moved to `docs/`, replacing an
  8-row defensive table at the top of the page. Both languages updated.
- Removed unverifiable storage-percentage claims ("reasoning accounts for
  70%–80% of storage") in favour of pointing at the `Storage by Part Type`
  breakdown, which lets readers measure their own footprint.
- Documented the read-only command set precisely: `status`, `sessions`,
  `analyze`, `projects`, `doctor`, and `export` open SQLite via `?mode=ro`; only
  `purge`, `checkpoint`, and `vacuum` ever write. The previous lists omitted
  `projects`, `doctor`, and `export`.
- `CONTRIBUTING.md` no longer implies CI enforces the local checks, since
  GitHub Actions is currently disabled on this repository.

### Internal

- Added `test_non_tool_content_parts_always_have_text`, a regression guard
  asserting that `SessionContentPart.text` is `None` only for `tool` parts.
  Verified it fails against an injected parsing defect.
- Test suite: 111 passing (was 110).

[Unreleased]: https://github.com/codehands028/ocgc/compare/v0.4.2...HEAD
[0.4.2]: https://github.com/codehands028/ocgc/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/codehands028/ocgc/compare/v0.4.0...v0.4.1