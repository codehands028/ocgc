"""Analysis logic."""

import json
import sqlite3
import sys
import time

import click

from ocgc import db


def _detect_version_or_exit(conn: sqlite3.Connection) -> int:
    try:
        return db.detect_version(conn)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None


def _emit_json(payload: object) -> None:
    """以机器可读格式将结构化数据写入标准输出。"""
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def run_status(json_output: bool = False) -> None:
    from ocgc.display import print_status, warn_if_opencode_running

    if not json_output:
        warn_if_opencode_running()

    try:
        conn = db.connect(readonly=True)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None
    try:
        version = _detect_version_or_exit(conn)
        db_info = db.get_db_info(conn, version=version)
        root_count, sub_count = db.get_session_count(conn, version=version)
        part_stats = db.get_part_type_stats(conn, version=version)
        now_ms = int(time.time() * 1000)
        age_dist = db.get_age_distribution(conn, now_ms, version=version)
        fs_stats = db.get_filesystem_stats()

        if json_output:
            payload = {
                "version": version,
                "database": db_info.to_dict(),
                "sessions": {
                    "total": root_count + sub_count,
                    "root": root_count,
                    "subagent": sub_count,
                },
                "filesystem": fs_stats.to_dict(),
                "total_on_disk": db_info.total_size + fs_stats.total_size,
                "part_types": [s.to_dict() for s in part_stats],
                "age_distribution": age_dist,
            }
            _emit_json(payload)
            return

        print_status(db_info, root_count, sub_count, part_stats, age_dist, fs_stats)
    finally:
        conn.close()


def run_sessions(
    sort_by: str = "size",
    limit: int | None = None,
    project: str | None = None,
    directory: str | None = None,
    json_output: bool = False,
) -> None:
    from ocgc.display import print_sessions, warn_if_opencode_running

    if not json_output:
        warn_if_opencode_running()

    try:
        conn = db.connect(readonly=True)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None
    try:
        version = _detect_version_or_exit(conn)
        sessions = db.get_sessions(
            conn,
            sort_by=sort_by,
            limit=limit,
            directory=directory,
            project=project,
            version=version,
        )

        if json_output:
            payload = {
                "version": version,
                "count": len(sessions),
                "sessions": [s.to_dict() for s in sessions],
            }
            _emit_json(payload)
            return

        if not sessions:
            from ocgc.display import console

            if project or directory:
                console.print("[dim]No sessions found matching the given criteria.[/]")
            else:
                console.print("[dim]No sessions found.[/]")
            return
        print_sessions(sessions)
    finally:
        conn.close()


def run_analyze(json_output: bool = False) -> None:
    from ocgc.display import print_analysis, warn_if_opencode_running

    if not json_output:
        warn_if_opencode_running()

    try:
        conn = db.connect(readonly=True)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None
    try:
        version = _detect_version_or_exit(conn)
        top_sessions_limit = 10
        orphan_diffs_limit = 20
        top_sessions = db.get_sessions(conn, sort_by="size", limit=top_sessions_limit, version=version)
        if not json_output and not top_sessions:
            from ocgc.display import console

            console.print("[dim]No sessions found.[/]")
            return

        root_count, sub_count = db.get_session_count(conn, version=version)
        total_sessions = root_count + sub_count
        root_stats, sub_stats = db.get_part_type_stats_by_session_type(conn, version=version)
        root_bytes = sum(s.size_bytes for s in root_stats)
        sub_bytes = sum(s.size_bytes for s in sub_stats)
        total_bytes = root_bytes + sub_bytes
        avg_size = total_bytes / total_sessions if total_sessions else 0.0
        growth_rate = db.get_growth_rate(conn, version=version)
        fs_stats = db.get_filesystem_stats()
        orphans = db.get_orphan_session_diffs(conn, version=version)

        if json_output:
            root_parts = sum(s.count for s in root_stats)
            sub_parts = sum(s.count for s in sub_stats)
            payload = {
                "version": version,
                "top_sessions": [s.to_dict() for s in top_sessions],
                "top_sessions_limit": top_sessions_limit,
                "total_sessions": total_sessions,
                "total_part_bytes": total_bytes,
                "avg_session_size": avg_size,
                "growth_rate": growth_rate,
                "storage_by_session_type": {
                    "root": {
                        "parts_count": root_parts,
                        "size_bytes": root_bytes,
                        "breakdown": [s.to_dict() for s in root_stats],
                    },
                    "subagent": {
                        "parts_count": sub_parts,
                        "size_bytes": sub_bytes,
                        "breakdown": [s.to_dict() for s in sub_stats],
                    },
                    "total": {
                        "parts_count": root_parts + sub_parts,
                        "size_bytes": total_bytes,
                    },
                },
                "filesystem": fs_stats.to_dict(),
                "orphan_diffs": {
                    "count": len(orphans),
                    "size_bytes": sum(o.size for o in orphans),
                    "items_limit": orphan_diffs_limit,
                    "truncated": len(orphans) > orphan_diffs_limit,
                    "items": [o.to_dict() for o in orphans[:orphan_diffs_limit]],
                },
            }
            _emit_json(payload)
            return

        print_analysis(
            top_sessions=top_sessions,
            avg_size=avg_size,
            growth_rate=growth_rate,
            root_stats=root_stats,
            sub_stats=sub_stats,
            total_sessions=total_sessions,
            fs_stats=fs_stats,
            orphan_count=len(orphans),
            orphan_bytes=sum(o.size for o in orphans),
        )
    finally:
        conn.close()


def run_projects(
    sort_by: str = "size",
    limit: int | None = None,
    json_output: bool = False,
) -> None:
    from ocgc.display import console, print_projects, warn_if_opencode_running

    if not json_output:
        warn_if_opencode_running()

    try:
        conn = db.connect(readonly=True)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None
    try:
        version = _detect_version_or_exit(conn)
        projects = db.get_project_stats(conn, sort_by=sort_by, limit=limit, version=version)

        if json_output:
            payload = {
                "version": version,
                "projects": [p.to_dict() for p in projects],
            }
            _emit_json(payload)
            return

        if not projects:
            console.print("[dim]No projects found.[/]")
            return
        print_projects(projects)
    finally:
        conn.close()
