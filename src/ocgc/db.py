"""SQLite query layer for OpenCode's database."""

import contextlib
import csv
import fnmatch
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"

_V2_SESSION_REFERENCE_TABLES: tuple[tuple[str, str], ...] = (
    ("session_message", "session_id"),
    ("session_inbox", "session_id"),
    ("session_pending", "session_id"),
    ("instruction_entry", "session_id"),
    ("instruction_state", "session_id"),
    ("todo", "session_id"),
    ("session_share", "session_id"),
    ("event", "aggregate_id"),
    ("event_sequence", "aggregate_id"),
)


@dataclass
class DBInfo:
    path: Path
    db_size: int
    wal_size: int
    version: int = 1

    @property
    def total_size(self) -> int:
        return self.db_size + self.wal_size


@dataclass
class CheckpointResult:
    mode: str
    busy: int  # 0 = completed, 1 = busy/locked
    log_frames: int
    checkpointed_frames: int
    wal_before: int
    wal_after: int
    db_before: int
    db_after: int
    total_before: int
    total_after: int

    @property
    def saved(self) -> int:
        """Net bytes freed across all database files (DB + WAL + SHM)."""
        return max(0, self.total_before - self.total_after)

    @property
    def wal_saved(self) -> int:
        """Bytes freed specifically from the WAL file."""
        return max(0, self.wal_before - self.wal_after)


@dataclass
class SessionRow:
    id: str
    parent_id: str | None
    directory: str
    title: str | None
    time_created: int  # ms epoch
    time_updated: int  # ms epoch
    size_bytes: int
    message_count: int
    project_id: str | None = None

    @property
    def is_subagent(self) -> bool:
        return self.parent_id is not None


@dataclass
class PartTypeStats:
    type_name: str
    count: int
    size_bytes: int


@dataclass
class FilesystemStats:
    session_diff_size: int
    snapshot_size: int
    tool_output_size: int
    session_diff_count: int
    snapshot_count: int
    tool_output_count: int = 0

    @property
    def total_size(self) -> int:
        return self.session_diff_size + self.snapshot_size + self.tool_output_size


@dataclass
class ToolOutputFile:
    path: Path
    size: int
    mtime_ns: int


@dataclass
class PurgeFilesResult:
    files_deleted: int = 0
    bytes_freed: int = 0


@dataclass
class OrphanDiff:
    session_id: str
    path: Path
    size: int


def _platform_default_db_path() -> Path:
    if sys.platform == "win32":
        localappdata = os.environ.get("LOCALAPPDATA")
        if localappdata:
            return Path(localappdata) / "opencode" / "opencode.db"
        return Path.home() / "AppData" / "Local" / "opencode" / "opencode.db"
    if "XDG_DATA_HOME" in os.environ:
        return Path(os.environ["XDG_DATA_HOME"]) / "opencode" / "opencode.db"
    return DEFAULT_DB_PATH


def get_db_path() -> Path:
    env_path = os.environ.get("OCGC_DB_PATH")
    if env_path:
        return Path(env_path)
    if "OPENCODE_DATA" in os.environ:
        return Path(os.environ["OPENCODE_DATA"]) / "opencode.db"

    platform_path = _platform_default_db_path()
    if platform_path.exists():
        return platform_path
    if DEFAULT_DB_PATH.exists():
        return DEFAULT_DB_PATH
    return platform_path


def check_opencode_running() -> bool:
    if os.environ.get("OCGC_SKIP_RUNNING_CHECK"):
        return False
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq opencode*", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return False
            candidates = ("opencode.exe", "opencode-server.exe", "opencode-cli.exe")
            return any(row and row[0].strip().lower() in candidates for row in csv.reader(result.stdout.splitlines()))
        else:
            result = subprocess.run(
                ["pgrep", "-x", "opencode"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, csv.Error):
        return False


def connect(readonly: bool = True, path: Path | None = None) -> sqlite3.Connection:
    target_path = path if path is not None else get_db_path()
    if not target_path.exists():
        raise FileNotFoundError(f"OpenCode database not found at {target_path}")
    if readonly:
        uri = f"{target_path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(str(target_path))
    conn.row_factory = sqlite3.Row
    if not readonly:
        conn.execute("PRAGMA journal_mode=WAL")
    return conn


def detect_version(conn: sqlite3.Connection) -> int:
    """Detect OpenCode database schema version (1 or 2)."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('session', 'session_v2')"
    )
    tables = {row[0] for row in cursor.fetchall()}
    if "session_v2" in tables:
        return 2
    if "session" in tables:
        return 1
    raise RuntimeError(
        f"Unable to detect OpenCode schema at {get_db_path()}: "
        "neither 'session_v2' nor 'session' table found."
    )


def get_db_info(
    conn: sqlite3.Connection | None = None,
    version: int | None = None,
) -> DBInfo:
    path = get_db_path()
    wal_path = Path(str(path) + "-wal")
    if version is None:
        if conn is not None:
            try:
                version = detect_version(conn)
            except (sqlite3.OperationalError, sqlite3.DatabaseError, RuntimeError):
                version = 1
        elif path.exists():
            try:
                c = connect(readonly=True)
                try:
                    version = detect_version(c)
                finally:
                    c.close()
            except (sqlite3.OperationalError, sqlite3.DatabaseError, RuntimeError):
                version = 1
        else:
            version = 1
    return DBInfo(
        path=path,
        db_size=path.stat().st_size if path.exists() else 0,
        wal_size=wal_path.stat().st_size if wal_path.exists() else 0,
        version=version,
    )


def get_session_count(conn: sqlite3.Connection, version: int | None = None) -> tuple[int, int]:
    """Return (root_count, subagent_count)."""
    if version is None:
        version = detect_version(conn)
    table = "session_v2" if version == 2 else "session"
    row = conn.execute(f"""
        SELECT
            SUM(CASE WHEN parent_id IS NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN parent_id IS NOT NULL THEN 1 ELSE 0 END)
        FROM {table}
    """).fetchone()
    return (row[0] or 0, row[1] or 0)


def get_part_type_stats(conn: sqlite3.Connection, version: int | None = None) -> list[PartTypeStats]:
    if version is None:
        version = detect_version(conn)

    if version == 2:
        rows = conn.execute("""
            WITH parts AS (
                SELECT
                    json_extract(c.value, '$.type') AS t,
                    LENGTH(c.value) AS sz
                FROM session_message m,
                     json_each(m.data, '$.content') c
                WHERE json_valid(m.data)
                  AND json_type(m.data, '$.content') = 'array'

                UNION ALL

                SELECT
                    CASE WHEN m.type = 'user' THEN 'text' ELSE m.type END AS t,
                    COALESCE(LENGTH(json_extract(m.data, '$.content')), LENGTH(m.data)) AS sz
                FROM session_message m
                WHERE NOT json_valid(m.data)
                   OR json_type(m.data, '$.content') != 'array'
                   OR json_type(m.data, '$.content') IS NULL
            )
            SELECT
                COALESCE(t, 'unknown') AS t,
                COUNT(*) AS cnt,
                SUM(sz) AS sz
            FROM parts
            GROUP BY t
            ORDER BY sz DESC
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT
                json_extract(data, '$.type') AS t,
                COUNT(*) AS cnt,
                SUM(LENGTH(data)) AS sz
            FROM part
            GROUP BY t
            ORDER BY sz DESC
        """).fetchall()

    return [PartTypeStats(r["t"] or "unknown", r["cnt"], r["sz"] or 0) for r in rows]


def get_age_distribution(conn: sqlite3.Connection, now_ms: int, version: int | None = None) -> dict[str, int]:
    """Return session counts bucketed by age."""
    if version is None:
        version = detect_version(conn)
    table = "session_v2" if version == 2 else "session"
    buckets = {
        "last 24h": 24 * 3600 * 1000,
        "1-7 days": 7 * 24 * 3600 * 1000,
        "7-14 days": 14 * 24 * 3600 * 1000,
        "14-30 days": 30 * 24 * 3600 * 1000,
    }
    result: dict[str, int] = {}
    prev_cutoff = now_ms
    for label, age_ms in buckets.items():
        cutoff = now_ms - age_ms
        count = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE time_created < ? AND time_created >= ?",
            (prev_cutoff, cutoff),
        ).fetchone()[0]
        result[label] = count
        prev_cutoff = cutoff

    older = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE time_created < ?",
        (prev_cutoff,),
    ).fetchone()[0]
    result["older than 30d"] = older
    return result


def _escape_like(s: str) -> str:
    """Escape special characters for SQL LIKE patterns using backslash escape."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _glob_to_like(pattern: str) -> str:
    """Convert a simple glob pattern (* and ?) to a SQL LIKE pattern with escaping."""
    res: list[str] = []
    for ch in pattern:
        if ch == "*":
            res.append("%")
        elif ch == "?":
            res.append("_")
        elif ch in ("%", "_", "\\"):
            res.append(f"\\{ch}")
        else:
            res.append(ch)
    return "".join(res)


def _build_filter_clause(
    directory: str | None = None,
    project: str | None = None,
    version: int = 1,
) -> tuple[list[str], list[str | int]]:
    """Build SQL condition fragments and params for directory and project filters."""
    conditions: list[str] = []
    params: list[str | int] = []

    norm_dir_col = "replace(s.directory, '\\', '/')"

    if directory is not None and directory.strip():
        expanded = os.path.expanduser(directory).strip()
        has_wildcard = "*" in expanded or "?" in expanded

        if has_wildcard:
            norm_raw = expanded.replace("\\", "/")
            like_pat = _glob_to_like(norm_raw)
            if norm_raw.startswith(("/", "*")) or (len(norm_raw) >= 2 and norm_raw[1] == ":"):
                conditions.append(f"{norm_dir_col} LIKE ? ESCAPE '\\'")
                params.append(like_pat)
            else:
                conditions.append(f"({norm_dir_col} LIKE ? ESCAPE '\\' OR {norm_dir_col} LIKE ? ESCAPE '\\')")
                params.extend([like_pat, f"%/{like_pat}"])
        else:
            abs_dir: str | None = None
            if expanded in (".", "./", ".\\") or expanded.startswith(("./", "../", ".\\", "..\\")):
                abs_dir = os.path.abspath(expanded).replace("\\", "/").rstrip("/")
            elif expanded.startswith("/") or (len(expanded) >= 2 and expanded[1] == ":"):
                abs_dir = expanded.replace("\\", "/").rstrip("/")

            if abs_dir is not None:
                like_pat = f"{_escape_like(abs_dir)}/%"
                conditions.append(f"({norm_dir_col} = ? COLLATE NOCASE OR {norm_dir_col} LIKE ? ESCAPE '\\')")
                params.extend([abs_dir, like_pat])
            else:
                bare = expanded.replace("\\", "/").strip("/")
                like_bare = _escape_like(bare)
                conditions.append(
                    f"({norm_dir_col} = ? COLLATE NOCASE "
                    f"OR {norm_dir_col} LIKE ? ESCAPE '\\' "
                    f"OR {norm_dir_col} LIKE ? ESCAPE '\\')"
                )
                params.extend([bare, f"%/{like_bare}", f"%/{like_bare}/%"])

    if project is not None and project.strip():
        proj_str = project.strip()
        has_wildcard = "*" in proj_str or "?" in proj_str

        if version == 2:
            if has_wildcard:
                proj_norm = proj_str.replace("\\", "/").strip("/")
                like_pat = _glob_to_like(proj_norm)
                conditions.append(
                    f"(s.project_id LIKE ? ESCAPE '\\' "
                    f"OR {norm_dir_col} LIKE ? ESCAPE '\\' "
                    f"OR {norm_dir_col} LIKE ? ESCAPE '\\')"
                )
                params.extend([like_pat, like_pat, f"%/{like_pat}"])
            else:
                bare = proj_str.replace("\\", "/").strip("/")
                like_bare = _escape_like(bare)
                conditions.append(
                    f"(s.project_id = ? COLLATE NOCASE "
                    f"OR {norm_dir_col} = ? COLLATE NOCASE "
                    f"OR {norm_dir_col} LIKE ? ESCAPE '\\' "
                    f"OR {norm_dir_col} LIKE ? ESCAPE '\\')"
                )
                params.extend([proj_str, bare, f"%/{like_bare}", f"%/{like_bare}/%"])
        else:
            if has_wildcard:
                proj_norm = proj_str.replace("\\", "/").strip("/")
                like_pat = _glob_to_like(proj_norm)
                conditions.append(f"({norm_dir_col} LIKE ? ESCAPE '\\' OR {norm_dir_col} LIKE ? ESCAPE '\\')")
                params.extend([like_pat, f"%/{like_pat}"])
            else:
                bare = proj_str.replace("\\", "/").strip("/")
                like_bare = _escape_like(bare)
                conditions.append(
                    f"({norm_dir_col} = ? COLLATE NOCASE "
                    f"OR {norm_dir_col} LIKE ? ESCAPE '\\' "
                    f"OR {norm_dir_col} LIKE ? ESCAPE '\\')"
                )
                params.extend([bare, f"%/{like_bare}", f"%/{like_bare}/%"])

    return conditions, params


def get_sessions(
    conn: sqlite3.Connection,
    sort_by: str = "size",
    limit: int | None = None,
    directory: str | None = None,
    project: str | None = None,
    version: int | None = None,
) -> list[SessionRow]:
    if version is None:
        version = detect_version(conn)

    order_clause = {
        "size": "size_bytes DESC",
        "age": "s.time_created ASC",
        "name": "s.title ASC",
    }.get(sort_by, "size_bytes DESC")

    filter_conds, filter_params = _build_filter_clause(directory=directory, project=project, version=version)
    where_clause = "WHERE " + " AND ".join(filter_conds) if filter_conds else ""

    limit_clause = "LIMIT ?" if limit else ""
    params: list[str | int] = list(filter_params)
    if limit:
        params.append(limit)

    if version == 2:
        query = f"""
            SELECT
                s.id,
                s.parent_id,
                s.directory,
                s.title,
                s.time_created,
                s.time_updated,
                COALESCE(sm.size_bytes, 0) AS size_bytes,
                COALESCE(sm.msg_count, 0) AS message_count,
                s.project_id
            FROM session_v2 s
            LEFT JOIN (
                SELECT session_id, SUM(LENGTH(data)) AS size_bytes, COUNT(*) AS msg_count
                FROM session_message
                GROUP BY session_id
            ) sm ON sm.session_id = s.id
            {where_clause}
            ORDER BY {order_clause}
            {limit_clause}
        """
    else:
        query = f"""
            SELECT
                s.id,
                s.parent_id,
                s.directory,
                s.title,
                s.time_created,
                s.time_updated,
                COALESCE(ps.size_bytes, 0) AS size_bytes,
                COALESCE(mc.msg_count, 0) AS message_count
            FROM session s
            LEFT JOIN (
                SELECT session_id, SUM(LENGTH(data)) AS size_bytes
                FROM part
                GROUP BY session_id
            ) ps ON ps.session_id = s.id
            LEFT JOIN (
                SELECT session_id, COUNT(*) AS msg_count
                FROM message
                GROUP BY session_id
            ) mc ON mc.session_id = s.id
            {where_clause}
            ORDER BY {order_clause}
            {limit_clause}
        """

    rows = conn.execute(query, params).fetchall()

    return [
        SessionRow(
            id=r["id"],
            parent_id=r["parent_id"],
            directory=r["directory"],
            title=r["title"],
            time_created=r["time_created"],
            time_updated=r["time_updated"],
            size_bytes=r["size_bytes"],
            message_count=r["message_count"],
            project_id=r["project_id"] if version == 2 else None,
        )
        for r in rows
    ]


def get_part_type_stats_by_session_type(
    conn: sqlite3.Connection,
    version: int | None = None,
) -> tuple[list[PartTypeStats], list[PartTypeStats]]:
    """Return (root_stats, subagent_stats)."""
    if version is None:
        version = detect_version(conn)

    def _query_v1(is_subagent: bool) -> list[PartTypeStats]:
        condition = "s.parent_id IS NOT NULL" if is_subagent else "s.parent_id IS NULL"
        rows = conn.execute(f"""
            SELECT
                json_extract(p.data, '$.type') AS t,
                COUNT(*) AS cnt,
                SUM(LENGTH(p.data)) AS sz
            FROM part p
            JOIN session s ON s.id = p.session_id
            WHERE {condition}
            GROUP BY t
            ORDER BY sz DESC
        """).fetchall()
        return [PartTypeStats(r["t"] or "unknown", r["cnt"], r["sz"] or 0) for r in rows]

    def _query_v2(is_subagent: bool) -> list[PartTypeStats]:
        condition = "s.parent_id IS NOT NULL" if is_subagent else "s.parent_id IS NULL"
        rows = conn.execute(f"""
            WITH parts AS (
                SELECT
                    json_extract(c.value, '$.type') AS t,
                    LENGTH(c.value) AS sz,
                    m.session_id
                FROM session_message m,
                     json_each(m.data, '$.content') c
                WHERE json_valid(m.data)
                  AND json_type(m.data, '$.content') = 'array'

                UNION ALL

                SELECT
                    CASE WHEN m.type = 'user' THEN 'text' ELSE m.type END AS t,
                    COALESCE(LENGTH(json_extract(m.data, '$.content')), LENGTH(m.data)) AS sz,
                    m.session_id
                FROM session_message m
                WHERE NOT json_valid(m.data)
                   OR json_type(m.data, '$.content') != 'array'
                   OR json_type(m.data, '$.content') IS NULL
            )
            SELECT
                COALESCE(p.t, 'unknown') AS t,
                COUNT(*) AS cnt,
                SUM(p.sz) AS sz
            FROM parts p
            JOIN session_v2 s ON s.id = p.session_id
            WHERE {condition}
            GROUP BY p.t
            ORDER BY sz DESC
        """).fetchall()
        return [PartTypeStats(r["t"] or "unknown", r["cnt"], r["sz"] or 0) for r in rows]

    if version == 2:
        return _query_v2(False), _query_v2(True)
    return _query_v1(False), _query_v1(True)


def get_growth_rate(conn: sqlite3.Connection, version: int | None = None) -> float | None:
    """Estimate MB per active day of usage."""
    if version is None:
        version = detect_version(conn)

    if version == 2:
        row = conn.execute("""
            SELECT
                COUNT(DISTINCT date(s.time_created / 1000, 'unixepoch')) AS active_days,
                SUM(LENGTH(m.data)) AS total_bytes
            FROM session_message m
            JOIN session_v2 s ON s.id = m.session_id
        """).fetchone()
    else:
        row = conn.execute("""
            SELECT
                COUNT(DISTINCT date(s.time_created / 1000, 'unixepoch')) AS active_days,
                SUM(LENGTH(p.data)) AS total_bytes
            FROM part p
            JOIN session s ON s.id = p.session_id
        """).fetchone()

    if not row or not row["active_days"]:
        return None
    active_days: int = row["active_days"]
    total_bytes = int(row["total_bytes"] or 0)
    return (total_bytes / 1048576) / active_days


def get_session_ids_for_purge(
    conn: sqlite3.Connection,
    older_than_ms: int | None = None,
    subagents_only: bool = False,
    larger_than_bytes: int | None = None,
    session_ids: list[str] | None = None,
    keep_latest: int | None = None,
    directory: str | None = None,
    project: str | None = None,
    now_ms: int | None = None,
    version: int | None = None,
) -> list[str]:
    """Return session IDs matching purge criteria. Filters combine with AND."""
    if version is None:
        version = detect_version(conn)

    table = "session_v2" if version == 2 else "session"
    conditions = []
    params: list[str | int] = []

    if session_ids:
        placeholders = ",".join("?" for _ in session_ids)
        conditions.append(f"s.id IN ({placeholders})")
        params.extend(session_ids)

    if subagents_only:
        conditions.append("s.parent_id IS NOT NULL")

    if older_than_ms is not None and now_ms is not None:
        cutoff = now_ms - older_than_ms
        conditions.append("s.time_created < ?")
        params.append(cutoff)

    if directory is not None or project is not None:
        dir_proj_conds, dir_proj_params = _build_filter_clause(
            directory=directory, project=project, version=version
        )
        conditions.extend(dir_proj_conds)
        params.extend(dir_proj_params)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    if larger_than_bytes is not None:
        if version == 2:
            subquery = "SELECT session_id, SUM(LENGTH(data)) AS size_bytes FROM session_message GROUP BY session_id"
        else:
            subquery = "SELECT session_id, SUM(LENGTH(data)) AS size_bytes FROM part GROUP BY session_id"

        query = f"""
            SELECT s.id FROM {table} s
            LEFT JOIN (
                {subquery}
            ) ps ON ps.session_id = s.id
            {where}
            {"AND" if conditions else "WHERE"} COALESCE(ps.size_bytes, 0) >= ?
        """
        params.append(larger_than_bytes)
    else:
        query = f"SELECT s.id FROM {table} s {where}"

    ids = {r[0] for r in conn.execute(query, params)}

    if keep_latest is not None:
        if not conditions and larger_than_bytes is None and not session_ids:
            # keep_latest alone: delete everything except the latest N
            latest_ids = {
                r[0]
                for r in conn.execute(
                    f"SELECT id FROM {table} ORDER BY time_created DESC LIMIT ?",
                    (keep_latest,),
                )
            }
            all_ids = {r[0] for r in conn.execute(f"SELECT id FROM {table}")}
            ids = all_ids - latest_ids
        else:
            # With other filters: compute latest N from the already-filtered set
            if ids:
                placeholders = ",".join("?" for _ in ids)
                id_list = list(ids)
                latest_ids = {
                    r[0]
                    for r in conn.execute(
                        f"SELECT id FROM {table} WHERE id IN ({placeholders}) ORDER BY time_created DESC LIMIT ?",
                        [*id_list, keep_latest],
                    )
                }
                ids -= latest_ids

    return sorted(ids)


def get_purge_summary(
    conn: sqlite3.Connection,
    session_ids: list[str],
    version: int | None = None,
) -> dict[str, int]:
    """Return summary stats for sessions about to be purged."""
    if not session_ids:
        return {"session_count": 0, "part_count": 0, "message_count": 0, "total_bytes": 0}
    if version is None:
        version = detect_version(conn)

    placeholders = ",".join("?" for _ in session_ids)

    if version == 2:
        msg_count = conn.execute(
            f"SELECT COUNT(*) FROM session_message WHERE session_id IN ({placeholders})",
            session_ids,
        ).fetchone()[0]

        total_bytes = conn.execute(
            f"SELECT COALESCE(SUM(LENGTH(data)), 0) FROM session_message WHERE session_id IN ({placeholders})",
            session_ids,
        ).fetchone()[0]

        array_count = conn.execute(
            f"""SELECT COUNT(*) FROM session_message m,
                 json_each(m.data, '$.content') c
            WHERE m.session_id IN ({placeholders})
              AND json_valid(m.data)
              AND json_type(m.data, '$.content') = 'array'""",
            session_ids,
        ).fetchone()[0]

        fallback_count = conn.execute(
            f"""SELECT COUNT(*) FROM session_message m
            WHERE m.session_id IN ({placeholders})
              AND (NOT json_valid(m.data)
                   OR json_type(m.data, '$.content') != 'array'
                   OR json_type(m.data, '$.content') IS NULL)""",
            session_ids,
        ).fetchone()[0]

        return {
            "session_count": len(session_ids),
            "part_count": (array_count or 0) + (fallback_count or 0),
            "message_count": msg_count or 0,
            "total_bytes": total_bytes,
        }
    else:
        part_row = conn.execute(
            f"SELECT COUNT(*), SUM(LENGTH(data)) FROM part WHERE session_id IN ({placeholders})",
            session_ids,
        ).fetchone()
        msg_count = conn.execute(
            f"SELECT COUNT(*) FROM message WHERE session_id IN ({placeholders})",
            session_ids,
        ).fetchone()[0]
        return {
            "session_count": len(session_ids),
            "part_count": part_row[0] or 0,
            "message_count": msg_count or 0,
            "total_bytes": part_row[1] or 0,
        }


def get_reasoning_summary(
    conn: sqlite3.Connection,
    session_ids: list[str] | None,
    version: int | None = None,
) -> dict[str, int]:
    """Return summary stats for reasoning parts in given sessions (or all if None)."""
    if version is None:
        version = detect_version(conn)

    if version == 2:
        if session_ids is not None:
            if not session_ids:
                return {"part_count": 0, "total_bytes": 0}
            placeholders = ",".join("?" for _ in session_ids)
            row = conn.execute(
                f"""SELECT COUNT(*), COALESCE(SUM(LENGTH(c.value)), 0)
                    FROM session_message m,
                         json_each(m.data, '$.content') c
                    WHERE json_valid(m.data)
                      AND json_type(m.data, '$.content') = 'array'
                      AND json_extract(c.value, '$.type') = 'reasoning'
                      AND m.session_id IN ({placeholders})""",
                session_ids,
            ).fetchone()
            whole_row = conn.execute(
                f"""SELECT COUNT(*), COALESCE(SUM(LENGTH(data)), 0)
                    FROM session_message m
                    WHERE m.type = 'reasoning'
                      AND (NOT json_valid(m.data)
                           OR json_type(m.data, '$.content') IS NULL
                           OR json_type(m.data, '$.content') != 'array')
                      AND m.session_id IN ({placeholders})""",
                session_ids,
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT COUNT(*), COALESCE(SUM(LENGTH(c.value)), 0)
                   FROM session_message m,
                        json_each(m.data, '$.content') c
                   WHERE json_valid(m.data)
                     AND json_type(m.data, '$.content') = 'array'
                     AND json_extract(c.value, '$.type') = 'reasoning'"""
            ).fetchone()
            whole_row = conn.execute(
                """SELECT COUNT(*), COALESCE(SUM(LENGTH(data)), 0)
                   FROM session_message m
                   WHERE m.type = 'reasoning'
                     AND (NOT json_valid(m.data)
                          OR json_type(m.data, '$.content') IS NULL
                          OR json_type(m.data, '$.content') != 'array')"""
            ).fetchone()
        return {
            "part_count": (row[0] or 0) + (whole_row[0] or 0),
            "total_bytes": (row[1] or 0) + (whole_row[1] or 0),
        }
    else:
        if session_ids is not None:
            if not session_ids:
                return {"part_count": 0, "total_bytes": 0}
            placeholders = ",".join("?" for _ in session_ids)
            row = conn.execute(
                f"""SELECT COUNT(*), SUM(LENGTH(data)) FROM part
                    WHERE json_extract(data, '$.type') = 'reasoning'
                    AND session_id IN ({placeholders})""",
                session_ids,
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT COUNT(*), SUM(LENGTH(data)) FROM part
                   WHERE json_extract(data, '$.type') = 'reasoning'"""
            ).fetchone()
        return {"part_count": row[0] or 0, "total_bytes": row[1] or 0}


def purge_sessions(
    conn: sqlite3.Connection,
    session_ids: list[str],
    version: int | None = None,
) -> PurgeFilesResult:
    """Delete sessions and cascade (parts, messages, todos, shares). Also removes session_diff files."""
    if not session_ids:
        return PurgeFilesResult()
    if version is None:
        version = detect_version(conn)

    placeholders = ",".join("?" for _ in session_ids)

    if version == 2:
        try:
            for table, join_col in _V2_SESSION_REFERENCE_TABLES:
                try:
                    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                except sqlite3.OperationalError:
                    continue
                if join_col not in cols:
                    continue
                extra_clause = ""
                if "aggregate_type" in cols:
                    extra_clause = " AND aggregate_type = 'session'"
                conn.execute(
                    f"DELETE FROM {table} WHERE {join_col} IN ({placeholders}){extra_clause}",
                    session_ids,
                )

            conn.execute(f"DELETE FROM session_v2 WHERE id IN ({placeholders})", session_ids)
            conn.commit()
        except Exception:
            with contextlib.suppress(Exception):
                conn.rollback()
            raise
    else:
        try:
            conn.execute(f"DELETE FROM part WHERE session_id IN ({placeholders})", session_ids)
            conn.execute(f"DELETE FROM message WHERE session_id IN ({placeholders})", session_ids)
            # Tables that may or may not exist depending on OpenCode version
            for table in ("todo", "session_share"):
                try:
                    conn.execute(
                        f"DELETE FROM {table} WHERE session_id IN ({placeholders})",
                        session_ids,
                    )
                except sqlite3.OperationalError as e:
                    if "no such table" not in str(e).lower():
                        raise
            conn.execute(f"DELETE FROM session WHERE id IN ({placeholders})", session_ids)
            conn.commit()
        except Exception:
            with contextlib.suppress(Exception):
                conn.rollback()
            raise

    # Best-effort cleanup of session_diff files
    return purge_session_diffs(session_ids)


def strip_reasoning(
    conn: sqlite3.Connection,
    session_ids: list[str] | None = None,
    version: int | None = None,
) -> int:
    """Delete reasoning parts from given sessions (or all). Return count deleted."""
    if version is None:
        version = detect_version(conn)

    if version == 2:
        query = (
            "SELECT id, session_id, data FROM session_message "
            "WHERE json_valid(data) "
            "  AND json_type(data, '$.content') = 'array' "
            "  AND EXISTS ("
            "    SELECT 1 FROM json_each(data, '$.content') c "
            "    WHERE json_extract(c.value, '$.type') = 'reasoning'"
            ")"
        )
        params: list[str] = []
        if session_ids is not None:
            if not session_ids:
                return 0
            placeholders = ",".join("?" for _ in session_ids)
            query += f" AND session_id IN ({placeholders})"
            params = list(session_ids)

        deleted_count = 0
        affected_session_ids: set[str] = set()
        updates: list[tuple[str, str]] = []

        for row in conn.execute(query, params):
            msg_id = row["id"]
            sess_id = row["session_id"]
            try:
                data = json.loads(row["data"])
            except (json.JSONDecodeError, TypeError):
                continue

            if not isinstance(data, dict):
                continue

            content = data.get("content")
            if not isinstance(content, list):
                continue

            new_content = [it for it in content if not (isinstance(it, dict) and it.get("type") == "reasoning")]
            removed = len(content) - len(new_content)
            if removed == 0:
                continue

            deleted_count += removed
            affected_session_ids.add(sess_id)
            data["content"] = new_content
            if "tokens" in data and isinstance(data["tokens"], dict) and "reasoning" in data["tokens"]:
                data["tokens"]["reasoning"] = 0
            new_data_str = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            updates.append((new_data_str, msg_id))

        try:
            if updates:
                conn.executemany("UPDATE session_message SET data = ? WHERE id = ?", updates)

            # Also delete whole messages where type = 'reasoning' and content is not an array
            whole_query = (
                "DELETE FROM session_message "
                "WHERE type = 'reasoning' "
                "  AND (NOT json_valid(data) "
                "       OR json_type(data, '$.content') IS NULL "
                "       OR json_type(data, '$.content') != 'array')"
            )
            if session_ids is not None:
                whole_query += f" AND session_id IN ({placeholders})"
                whole_cur = conn.execute(whole_query, params)
            else:
                whole_cur = conn.execute(whole_query)
            deleted_count += whole_cur.rowcount

            if deleted_count > 0 and affected_session_ids:
                cols = {row[1] for row in conn.execute("PRAGMA table_info(session_v2)")}
                ph = ",".join("?" for _ in affected_session_ids)
                if "tokens_reasoning" in cols:
                    conn.execute(
                        f"UPDATE session_v2 SET tokens_reasoning = 0 WHERE id IN ({ph})",
                        list(affected_session_ids),
                    )
            conn.commit()
        except Exception:
            with contextlib.suppress(Exception):
                conn.rollback()
            raise

        return deleted_count
    else:
        try:
            if session_ids is not None:
                if not session_ids:
                    return 0
                placeholders = ",".join("?" for _ in session_ids)
                cur = conn.execute(
                    f"""DELETE FROM part
                        WHERE json_extract(data, '$.type') = 'reasoning'
                        AND session_id IN ({placeholders})""",
                    session_ids,
                )
            else:
                cur = conn.execute("DELETE FROM part WHERE json_extract(data, '$.type') = 'reasoning'")
            conn.commit()
            return cur.rowcount
        except Exception:
            with contextlib.suppress(Exception):
                conn.rollback()
            raise


def _total_db_size(path: Path) -> int:
    """Return combined size of db + WAL + SHM files."""
    total = path.stat().st_size if path.exists() else 0
    for suffix in ("-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            total += p.stat().st_size
    return total


def get_storage_dir() -> Path:
    """Return the opencode storage base dir (parent of the DB file)."""
    return get_db_path().parent


def _dir_stats(path: Path) -> tuple[int, int]:
    """Return (total_size, file_count) for all regular files in a directory tree."""
    if not path.is_dir():
        return 0, 0
    size = 0
    count = 0
    for f in path.rglob("*"):
        try:
            st = f.stat()
            if stat.S_ISREG(st.st_mode):
                size += st.st_size
                count += 1
        except OSError:
            continue
    return size, count


def _dir_size(path: Path) -> int:
    """Return total size of all files in a directory tree."""
    return _dir_stats(path)[0]


def get_filesystem_stats() -> FilesystemStats:
    """Return sizes of session_diff/, snapshot/, and tool-output/ directories."""
    base = get_storage_dir()
    diff_dir = base / "storage" / "session_diff"
    snap_dir = base / "snapshot"
    tool_dir = base / "tool-output"

    diff_count = len(list(diff_dir.glob("*.json"))) if diff_dir.is_dir() else 0
    snap_count = len([d for d in snap_dir.iterdir() if d.is_dir()]) if snap_dir.is_dir() else 0
    tool_size, tool_count = _dir_stats(tool_dir)

    return FilesystemStats(
        session_diff_size=_dir_size(diff_dir),
        snapshot_size=_dir_size(snap_dir),
        tool_output_size=tool_size,
        session_diff_count=diff_count,
        snapshot_count=snap_count,
        tool_output_count=tool_count,
    )


def purge_session_diffs(session_ids: list[str]) -> PurgeFilesResult:
    """Delete session_diff JSON files for given session IDs. Best-effort."""
    diff_dir = get_storage_dir() / "storage" / "session_diff"
    result = PurgeFilesResult()
    if not diff_dir.is_dir():
        return result
    for sid in session_ids:
        path = diff_dir / f"{sid}.json"
        try:
            size = path.stat().st_size
            path.unlink()
            result.files_deleted += 1
            result.bytes_freed += size
        except (FileNotFoundError, OSError):
            pass
    return result


def get_orphan_session_diffs(conn: sqlite3.Connection, version: int | None = None) -> list[OrphanDiff]:
    """Find session_diff files that have no matching session in DB."""
    diff_dir = get_storage_dir() / "storage" / "session_diff"
    if not diff_dir.is_dir():
        return []

    if version is None:
        version = detect_version(conn)
    table = "session_v2" if version == 2 else "session"

    db_ids = {r[0] for r in conn.execute(f"SELECT id FROM {table}")}
    orphans = []
    for path in diff_dir.glob("*.json"):
        sid = path.stem
        if sid not in db_ids:
            orphans.append(OrphanDiff(session_id=sid, path=path, size=path.stat().st_size))
    return sorted(orphans, key=lambda o: o.size, reverse=True)


def purge_orphan_diffs(orphans: list[OrphanDiff]) -> PurgeFilesResult:
    """Delete orphan session_diff files. Best-effort."""
    result = PurgeFilesResult()
    for o in orphans:
        try:
            o.path.unlink()
            result.files_deleted += 1
            result.bytes_freed += o.size
        except (FileNotFoundError, OSError):
            pass
    return result


def get_snapshot_projects(
    project: str | None = None,
    directory: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[tuple[str, int]]:
    """Return (dirname, size_bytes) for each snapshot project directory, optionally filtered."""
    snap_dir = get_storage_dir() / "snapshot"
    if not snap_dir.is_dir():
        return []

    proj_clean = project.strip() if project and project.strip() else None
    dir_clean = directory.strip() if directory and directory.strip() else None
    has_filter = proj_clean is not None or dir_clean is not None

    matched_db_proj_ids: set[str] = set()

    if has_filter:
        close_conn = False
        db_conn = conn
        if db_conn is None:
            with contextlib.suppress(FileNotFoundError, sqlite3.Error):
                db_conn = connect(readonly=True)
                close_conn = True

        if db_conn is not None:
            try:
                version = detect_version(db_conn)
                if version == 2:
                    conds, params = _build_filter_clause(directory=dir_clean, project=proj_clean, version=2)
                    where = "WHERE " + " AND ".join(conds) if conds else ""
                    rows = db_conn.execute(
                        f"SELECT DISTINCT s.project_id FROM session_v2 s {where}", params
                    ).fetchall()
                    for r in rows:
                        if r[0]:
                            matched_db_proj_ids.add(str(r[0]).lower())
            except (sqlite3.Error, RuntimeError):
                if close_conn:
                    with contextlib.suppress(Exception):
                        db_conn.close()
                raise
            finally:
                if close_conn:
                    with contextlib.suppress(Exception):
                        db_conn.close()

    def _matches_project(name: str) -> bool:
        if not proj_clean:
            return True
        if name in matched_db_proj_ids:
            return True
        if "*" in proj_clean or "?" in proj_clean:
            esc_pattern = proj_clean.lower().replace("[", "[[]")
            return fnmatch.fnmatch(name, esc_pattern)
        return name == proj_clean.lower()

    def _matches_directory(name: str) -> bool:
        if not dir_clean:
            return True
        if name in matched_db_proj_ids:
            return True
        clean_dir = os.path.expanduser(dir_clean).replace("\\", "/").rstrip("/")
        if "*" in clean_dir or "?" in clean_dir:
            pattern = clean_dir.rsplit("/", 1)[-1].lower()
            if not pattern.strip("*?"):
                return False
            esc_pattern = pattern.replace("[", "[[]")
            return fnmatch.fnmatch(name, esc_pattern)
        dir_basename = clean_dir.rsplit("/", 1)[-1].lower() if clean_dir else ""
        return bool(dir_basename and name == dir_basename)

    projects = []
    for d in sorted(snap_dir.iterdir()):
        if not d.is_dir():
            continue
        if has_filter:
            name_lower = d.name.lower()
            if not (_matches_project(name_lower) and _matches_directory(name_lower)):
                continue
        projects.append((d.name, _dir_size(d)))
    return projects


def _force_writable(path: str | Path) -> None:
    with contextlib.suppress(OSError):
        p_str = str(path)
        if sys.platform == "win32":
            os.chmod(p_str, stat.S_IWRITE)
        else:
            try:
                current_mode = os.stat(p_str).st_mode
                os.chmod(p_str, current_mode | stat.S_IWUSR)
            except OSError:
                os.chmod(p_str, stat.S_IWUSR | stat.S_IRUSR)


def _rmtree_safe(path: Path) -> None:
    def _on_error_cb(func: object, p: str, exc_info: object) -> None:
        _force_writable(p)
        if callable(func):
            with contextlib.suppress(OSError):
                func(p)

    def _on_exc_cb(func: object, p: str, exc: object) -> None:
        _force_writable(p)
        if callable(func):
            with contextlib.suppress(OSError):
                func(p)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_on_exc_cb)
    else:
        shutil.rmtree(path, onerror=_on_error_cb)


def purge_snapshots(
    project: str | None = None,
    directory: str | None = None,
    conn: sqlite3.Connection | None = None,
    names: list[str] | None = None,
) -> PurgeFilesResult:
    """Delete snapshot directories. If names given, delete those; else filter by project/directory."""
    snap_dir = get_storage_dir() / "snapshot"
    result = PurgeFilesResult()
    if not snap_dir.is_dir():
        return result

    if names is not None:
        target_names = names
    else:
        snap_projects = get_snapshot_projects(project=project, directory=directory, conn=conn)
        target_names = [name for name, _ in snap_projects]

    for name in target_names:
        target = snap_dir / name
        if target.is_dir():
            result.bytes_freed += _dir_size(target)
            _rmtree_safe(target)
            result.files_deleted += 1

    return result


def get_tool_output_files(
    older_than_ms: int | None = None,
    now_ms: int | None = None,
) -> list[ToolOutputFile]:
    """Find files in tool-output/ directory, optionally older than older_than_ms."""
    tool_dir = get_storage_dir() / "tool-output"
    if not tool_dir.is_dir():
        return []

    cutoff: int | None = None
    if older_than_ms is not None:
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        cutoff = now_ms - older_than_ms

    files: list[ToolOutputFile] = []
    for f in tool_dir.rglob("*"):
        try:
            st = f.stat()
            if not stat.S_ISREG(st.st_mode):
                continue
            if cutoff is not None and (st.st_mtime_ns // 1_000_000) >= cutoff:
                continue
            files.append(ToolOutputFile(path=f, size=st.st_size, mtime_ns=st.st_mtime_ns))
        except OSError:
            continue
    return sorted(files, key=lambda x: str(x.path))


def purge_tool_outputs(files: list[ToolOutputFile]) -> PurgeFilesResult:
    """Delete tool output files. Best-effort."""
    result = PurgeFilesResult()
    for f in files:
        try:
            st = f.path.stat()
        except OSError:
            continue

        # If file was modified or changed size after scan, skip deletion to preserve newly written data
        if f.mtime_ns > 0 and (st.st_mtime_ns > f.mtime_ns or st.st_size != f.size):
            continue

        try:
            f.path.unlink()
            result.files_deleted += 1
            result.bytes_freed += st.st_size
        except PermissionError:
            parent = f.path.parent
            orig_mode: int | None = None
            if sys.platform != "win32":
                with contextlib.suppress(OSError):
                    orig_mode = parent.stat().st_mode
                _force_writable(parent)
            else:
                _force_writable(f.path)
            try:
                f.path.unlink()
                result.files_deleted += 1
                result.bytes_freed += st.st_size
            except (FileNotFoundError, OSError):
                pass
            finally:
                if orig_mode is not None:
                    with contextlib.suppress(OSError):
                        os.chmod(str(parent), stat.S_IMODE(orig_mode))
        except (FileNotFoundError, OSError):
            pass

    tool_dir = get_storage_dir() / "tool-output"
    if tool_dir.is_dir():
        for d in sorted(tool_dir.rglob("*"), reverse=True):
            try:
                if d.is_symlink() or not d.is_dir():
                    continue
                d.rmdir()
            except PermissionError:
                parent_dir = d.parent
                orig_dir_mode: int | None = None
                if sys.platform != "win32":
                    with contextlib.suppress(OSError):
                        orig_dir_mode = parent_dir.stat().st_mode
                    _force_writable(parent_dir)
                else:
                    _force_writable(d)
                try:
                    d.rmdir()
                except OSError:
                    pass
                finally:
                    if orig_dir_mode is not None:
                        with contextlib.suppress(OSError):
                            os.chmod(str(parent_dir), stat.S_IMODE(orig_dir_mode))
            except OSError:
                continue

    return result


def checkpoint_db(mode: str = "TRUNCATE", path: Path | None = None) -> CheckpointResult:
    """Run WAL checkpoint on the OpenCode SQLite database.

    Synchronously merges WAL pages back into the main database file and
    optionally truncates the WAL file to 0 bytes.

    Args:
        mode: Checkpoint mode ('PASSIVE', 'FULL', 'RESTART', or 'TRUNCATE').
              Defaults to 'TRUNCATE'.
        path: Optional explicit path to the database file. If None, resolves
              via get_db_path().

    Returns:
        CheckpointResult with before/after byte sizes and checkpoint frames.

    Raises:
        FileNotFoundError: If the database file does not exist.
        ValueError: If mode is not one of PASSIVE, FULL, RESTART, TRUNCATE.
        sqlite3.OperationalError: If SQLite encounters a locking or I/O error.
    """
    target_path = path if path is not None else get_db_path()
    if not target_path.exists():
        raise FileNotFoundError(f"OpenCode database not found at {target_path}")

    norm_mode = mode.upper().strip()
    valid_modes = {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}
    if norm_mode not in valid_modes:
        raise ValueError(f"Invalid checkpoint mode: {mode!r}. Must be one of {', '.join(sorted(valid_modes))}")

    wal_path = Path(str(target_path) + "-wal")
    wal_before = wal_path.stat().st_size if wal_path.exists() else 0
    db_before = target_path.stat().st_size
    total_before = _total_db_size(target_path)

    conn = connect(readonly=False, path=target_path)
    try:
        cursor = conn.execute(f"PRAGMA wal_checkpoint({norm_mode})")
        row = cursor.fetchone()
        busy = int(row[0]) if row and row[0] is not None else 0
        log_frames = int(row[1]) if row and row[1] is not None else 0
        checkpointed_frames = int(row[2]) if row and row[2] is not None else 0
    finally:
        conn.close()

    wal_after = wal_path.stat().st_size if wal_path.exists() else 0
    db_after = target_path.stat().st_size
    total_after = _total_db_size(target_path)

    return CheckpointResult(
        mode=norm_mode,
        busy=busy,
        log_frames=max(0, log_frames),
        checkpointed_frames=max(0, checkpointed_frames),
        wal_before=wal_before,
        wal_after=wal_after,
        db_before=db_before,
        db_after=db_after,
        total_before=total_before,
        total_after=total_after,
    )


def vacuum_db(path: Path | None = None) -> tuple[int, int]:
    """Run VACUUM. Returns (before_total, after_total) including WAL+SHM."""
    target_path = path if path is not None else get_db_path()
    if not target_path.exists():
        raise FileNotFoundError(f"OpenCode database not found at {target_path}")
    before = _total_db_size(target_path)
    conn = connect(readonly=False, path=target_path)
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()
    after = _total_db_size(target_path)
    return before, after
