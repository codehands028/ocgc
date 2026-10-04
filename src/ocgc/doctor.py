"""Database health check and diagnostic engine for OpenCode."""

import contextlib
import json
import os
import stat
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ocgc import db
from ocgc.display import format_bytes


class CheckStatus(str, Enum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"
    INFO = "info"


@dataclass
class CheckItem:
    category: str
    status: CheckStatus
    title: str
    message: str
    detail: str | None = None
    suggestion: str | None = None


@dataclass
class DoctorReport:
    checks: list[CheckItem] = field(default_factory=list)
    db_path: str = ""
    db_version: int | None = None
    is_healthy: bool = True
    has_critical_error: bool = False
    suggested_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.is_healthy,
            "critical_error": self.has_critical_error,
            "db_path": self.db_path,
            "db_version": self.db_version,
            "checks": [
                {
                    "category": c.category,
                    "status": c.status.value,
                    "title": c.title,
                    "message": c.message,
                    "detail": c.detail,
                    "suggestion": c.suggestion,
                }
                for c in self.checks
            ],
            "suggested_actions": self.suggested_actions,
        }


def _is_writable(path: Path) -> bool:
    """Check if a path is writable, taking mode bits into account (even for root)."""
    try:
        if not path.exists():
            return False
        st = path.stat()
        if sys.platform != "win32" and hasattr(os, "geteuid") and os.geteuid() == 0:
            return bool(st.st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        return os.access(path, os.W_OK)
    except OSError:
        return False


_SNAPSHOT_SCAN_LIMIT = 5000


def _check_snapshot_permissions(
    snap_dir: Path,
    limit: int = _SNAPSHOT_SCAN_LIMIT,
) -> tuple[bool, int, bool]:
    """Check if snapshot directory and its files are writable.

    Returns (all_writable, non_writable_count, hit_limit).
    """
    if not snap_dir.exists():
        return True, 0, False
    non_writable = 0
    if not _is_writable(snap_dir):
        non_writable += 1
    scanned = 1
    hit_limit = False
    for root, dirs, files in os.walk(snap_dir):
        if scanned >= limit:
            hit_limit = True
            break
        for d in dirs:
            scanned += 1
            dp = Path(root) / d
            if not _is_writable(dp):
                non_writable += 1
            if scanned >= limit:
                hit_limit = True
                break
        if hit_limit:
            break
        for f in files:
            scanned += 1
            fp = Path(root) / f
            if not _is_writable(fp):
                non_writable += 1
            if scanned >= limit:
                hit_limit = True
                break
    return non_writable == 0, non_writable, hit_limit


def diagnose(
    db_path: Path | None = None,
    quick: bool = False,
) -> DoctorReport:
    """Run comprehensive health checks on OpenCode database and storage."""
    target_db = db_path if db_path is not None else db.get_db_path()
    checks: list[CheckItem] = []
    suggested_actions: list[str] = []

    # 1. Process Status Check
    is_running = db.check_opencode_running()
    if is_running:
        checks.append(
            CheckItem(
                category="process",
                status=CheckStatus.WARN,
                title="Process status",
                message="OpenCode process is actively running",
                detail="Writing or maintenance operations may hit database locks or file contention.",
                suggestion="Consider stopping OpenCode before performing maintenance or purge operations.",
            )
        )
        suggested_actions.append("Consider stopping OpenCode before performing maintenance operations")
    else:
        checks.append(
            CheckItem(
                category="process",
                status=CheckStatus.OK,
                title="Process status",
                message="OpenCode is not running (no lock contention)",
            )
        )

    # 2. Database File Existence & Permissions
    if not target_db.exists():
        checks.append(
            CheckItem(
                category="permission",
                status=CheckStatus.ERROR,
                title="Database file",
                message=f"Database file not found at {target_db}",
                detail="OpenCode database has not been initialized or path is incorrect.",
                suggestion="Launch OpenCode to initialize the storage directory and database.",
            )
        )
        suggested_actions.append(f"Ensure OpenCode is initialized or verify database path: {target_db}")
        return DoctorReport(
            checks=checks,
            db_path=str(target_db),
            db_version=None,
            is_healthy=False,
            has_critical_error=True,
            suggested_actions=suggested_actions,
        )

    db_readable = os.access(target_db, os.R_OK)
    db_writable = _is_writable(target_db)
    parent_writable = _is_writable(target_db.parent)

    db_size_str = ""
    with contextlib.suppress(OSError):
        db_size_str = f" ({format_bytes(target_db.stat().st_size)})"

    if not db_readable:
        checks.append(
            CheckItem(
                category="permission",
                status=CheckStatus.ERROR,
                title="Database permissions",
                message=f"Database file is not readable: {target_db}",
                suggestion=f"Run 'chmod +r {target_db}' to grant read permission",
            )
        )
        suggested_actions.append(f"Grant read permission: chmod +r {target_db}")
    elif not db_writable or not parent_writable:
        checks.append(
            CheckItem(
                category="permission",
                status=CheckStatus.ERROR,
                title="Database permissions",
                message=f"Database file or parent directory is read-only: {target_db}",
                suggestion=f"Run 'chmod +w {target_db}' and 'chmod +w {target_db.parent}'",
            )
        )
        if not db_writable:
            suggested_actions.append(f"Grant write permission: chmod +w {target_db}")
        if not parent_writable:
            suggested_actions.append(f"Grant write permission to directory: chmod +w {target_db.parent}")
    else:
        checks.append(
            CheckItem(
                category="permission",
                status=CheckStatus.OK,
                title="Database permissions",
                message=f"Database file is readable and writable{db_size_str}",
            )
        )

    # 3. Storage Directory & Snapshot Permissions
    # get_storage_dir() == get_db_path().parent; using target_db.parent unifies both default and custom paths
    storage_dir = target_db.parent
    snap_dir = storage_dir / "snapshot"
    all_writable, non_writable_count, hit_limit = _check_snapshot_permissions(snap_dir)
    detail_suffix = " (checked sample limit)" if hit_limit else ""
    if not all_writable:
        checks.append(
            CheckItem(
                category="permission",
                status=CheckStatus.WARN,
                title="File permissions",
                message=f"Found {non_writable_count} read-only item(s) in snapshots directory",
                detail=f"Read-only git packfiles in snapshots may prevent clean deletion or purge.{detail_suffix}",
                suggestion=f"Run 'chmod -R u+w {snap_dir}' to restore write permissions",
            )
        )
        suggested_actions.append(f"Restore snapshot write permissions: chmod -R u+w {snap_dir}")
    else:
        checks.append(
            CheckItem(
                category="permission",
                status=CheckStatus.OK,
                title="File permissions",
                message=f"Snapshot and storage directories are writable{detail_suffix}",
            )
        )

    # Connect to database for internal inspection
    try:
        conn = db.connect(readonly=True, path=target_db)
    except Exception as e:
        checks.append(
            CheckItem(
                category="connection",
                status=CheckStatus.ERROR,
                title="Database connection",
                message=f"Failed to connect to SQLite database: {e}",
            )
        )
        suggested_actions.append("Check database file integrity or access permissions")
        return DoctorReport(
            checks=checks,
            db_path=str(target_db),
            db_version=None,
            is_healthy=False,
            has_critical_error=True,
            suggested_actions=suggested_actions,
        )

    version: int | None = None
    try:
        # 4. SQLite Integrity Check
        int_ok, int_msgs = db.check_db_integrity(conn, quick=quick)
        check_name = "PRAGMA quick_check" if quick else "PRAGMA integrity_check"
        if int_ok:
            checks.append(
                CheckItem(
                    category="integrity",
                    status=CheckStatus.OK,
                    title="Database integrity",
                    message=f"OK ({check_name} passed)",
                )
            )
        else:
            err_summary = "; ".join(int_msgs[:3])
            if len(int_msgs) > 3:
                err_summary += f" (...and {len(int_msgs) - 3} more errors)"
            err_lower = err_summary.lower()
            if "locked" in err_lower or "busy" in err_lower:
                checks.append(
                    CheckItem(
                        category="integrity",
                        status=CheckStatus.WARN,
                        title="Database integrity",
                        message=f"Integrity check blocked: {err_summary}",
                        detail="Database is busy or locked by another process (likely OpenCode).",
                        suggestion="Stop OpenCode and rerun 'ocgc doctor' to verify integrity without lock contention.",
                    )
                )
                suggested_actions.append("Stop OpenCode and rerun 'ocgc doctor' to verify integrity without locks")
            else:
                checks.append(
                    CheckItem(
                        category="integrity",
                        status=CheckStatus.ERROR,
                        title="Database integrity",
                        message=f"Corruption detected: {err_summary}",
                        detail="Database failed SQLite integrity check. Data loss or query failure may occur.",
                        suggestion="Create a complete backup of opencode.db before running SQLite recovery tools.",
                    )
                )
                suggested_actions.append("Database corruption detected! Backup opencode.db immediately before repair.")

        # 5. Schema Version & Table Presence
        try:
            version = db.detect_version(conn)
            tbl_ok, missing_tables = db.check_table_presence(conn, version)
            if tbl_ok:
                checks.append(
                    CheckItem(
                        category="schema",
                        status=CheckStatus.OK,
                        title="Schema version",
                        message=f"OpenCode v{version} (core tables present)",
                    )
                )
            else:
                missing_str = ", ".join(missing_tables)
                checks.append(
                    CheckItem(
                        category="schema",
                        status=CheckStatus.ERROR,
                        title="Schema version",
                        message=f"OpenCode v{version} schema incomplete: missing table(s) [{missing_str}]",
                        suggestion="Database tables are missing. Check if migrations were interrupted.",
                    )
                )
                suggested_actions.append(f"Repair schema: missing core table(s) {missing_str}")
        except Exception as e:
            checks.append(
                CheckItem(
                    category="schema",
                    status=CheckStatus.ERROR,
                    title="Schema version",
                    message=f"Unrecognized database schema: {e}",
                    suggestion="Ensure opencode.db is a valid OpenCode v1 or v2 database.",
                )
            )
            suggested_actions.append("Ensure database corresponds to an OpenCode v1 or v2 instance.")

        # 6. WAL Log Health & Size
        wal_path = target_db.with_name(target_db.name + "-wal")
        wal_size: int | None = None
        try:
            if wal_path.exists():
                wal_size = wal_path.stat().st_size
        except OSError:
            wal_size = None

        if wal_size is not None and wal_size > 0:
            if wal_size > 100 * 1024 * 1024:  # > 100 MB
                checks.append(
                    CheckItem(
                        category="wal",
                        status=CheckStatus.WARN,
                        title="WAL Log file",
                        message=f"{format_bytes(wal_size)} (Warning: excessive uncommitted log)",
                        detail="Large WAL logs slow down startup queries and consume disk space.",
                        suggestion="Run 'ocgc checkpoint' to flush and shrink WAL log",
                    )
                )
                suggested_actions.append("Run 'ocgc checkpoint' to flush and shrink WAL log")
            elif wal_size > 32 * 1024 * 1024:  # > 32 MB
                checks.append(
                    CheckItem(
                        category="wal",
                        status=CheckStatus.WARN,
                        title="WAL Log file",
                        message=f"{format_bytes(wal_size)} (Elevated log size)",
                        suggestion="Run 'ocgc checkpoint' to flush and shrink WAL log",
                    )
                )
                suggested_actions.append("Run 'ocgc checkpoint' to flush and shrink WAL log")
            else:
                checks.append(
                    CheckItem(
                        category="wal",
                        status=CheckStatus.OK,
                        title="WAL Log file",
                        message=f"{format_bytes(wal_size)} (healthy)",
                    )
                )
        else:
            checks.append(
                CheckItem(
                    category="wal",
                    status=CheckStatus.OK,
                    title="WAL Log file",
                    message="None active (clean or fully checkpointed)",
                )
            )

        # 7. Relational Foreign Key Integrity / Dangling Rows
        if version is not None:
            try:
                dangling = db.check_dangling_records(conn, version=version)
                if dangling:
                    total_dangling = sum(dangling.values())
                    breakdown = ", ".join(f"{cnt} in {k}" for k, cnt in dangling.items())
                    checks.append(
                        CheckItem(
                            category="relational",
                            status=CheckStatus.WARN,
                            title="Relational integrity",
                            message=f"{total_dangling} dangling record(s) found ({breakdown})",
                            detail="Associated session or message records are missing; orphan records occupy space.",
                            suggestion="Run 'ocgc purge' or clean up dangling records to reclaim space.",
                        )
                    )
                    suggested_actions.append(
                        f"Found {total_dangling} dangling row(s) across tables ({breakdown})"
                    )
                else:
                    checks.append(
                        CheckItem(
                            category="relational",
                            status=CheckStatus.OK,
                            title="Relational integrity",
                            message="No dangling orphan records found",
                        )
                    )
            except Exception as e:
                checks.append(
                    CheckItem(
                        category="relational",
                        status=CheckStatus.WARN,
                        title="Relational integrity",
                        message=f"Failed to check foreign relations: {e}",
                    )
                )

        # 8. Filesystem Orphan Diffs
        if version is not None:
            try:
                orphan_diffs = db.get_orphan_session_diffs(conn, version=version, storage_dir=storage_dir)
                if orphan_diffs:
                    orphan_bytes = sum(o.size for o in orphan_diffs)
                    bytes_str = format_bytes(orphan_bytes)
                    checks.append(
                        CheckItem(
                            category="filesystem",
                            status=CheckStatus.WARN,
                            title="Orphan session diffs",
                            message=f"{len(orphan_diffs)} file(s) found ({bytes_str})",
                            detail="Session diff files exist on disk but their corresponding sessions were deleted.",
                            suggestion=f"Run 'ocgc purge --clean-orphans' to reclaim {bytes_str}",
                        )
                    )
                    suggested_actions.append(f"Run 'ocgc purge --clean-orphans' to reclaim {bytes_str}")
                else:
                    checks.append(
                        CheckItem(
                            category="filesystem",
                            status=CheckStatus.OK,
                            title="Orphan session diffs",
                            message="All diff files match existing sessions (0 orphans)",
                        )
                    )
            except Exception as e:
                checks.append(
                    CheckItem(
                        category="filesystem",
                        status=CheckStatus.WARN,
                        title="Orphan session diffs",
                        message=f"Failed to check orphan diff files: {e}",
                    )
                )

    finally:
        conn.close()

    # Deduplicate suggested actions while preserving order
    deduped_actions: list[str] = []
    seen: set[str] = set()
    for act in suggested_actions:
        if act not in seen:
            seen.add(act)
            deduped_actions.append(act)

    is_healthy = all(c.status in (CheckStatus.OK, CheckStatus.INFO) for c in checks)
    has_critical_error = any(c.status == CheckStatus.ERROR for c in checks)

    return DoctorReport(
        checks=checks,
        db_path=str(target_db),
        db_version=version,
        is_healthy=is_healthy,
        has_critical_error=has_critical_error,
        suggested_actions=deduped_actions,
    )


def run_doctor(quick: bool = False, json_output: bool = False) -> DoctorReport:
    """Execute doctor health check, print report, and handle exit conditions."""
    from ocgc.display import print_doctor_report

    report = diagnose(quick=quick)

    if json_output:
        sys.stdout.write(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n")
    else:
        print_doctor_report(report)

    return report
