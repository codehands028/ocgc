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


def run_status() -> None:
    from ocgc.display import print_status, warn_if_opencode_running

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
        print_status(db_info, root_count, sub_count, part_stats, age_dist, fs_stats)
    finally:
        conn.close()


def run_sessions(
    sort_by: str = "size",
    limit: int | None = None,
    project: str | None = None,
    directory: str | None = None,
) -> None:
    from ocgc.display import print_sessions, warn_if_opencode_running

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


def run_analyze() -> None:
    from ocgc.display import print_analysis, warn_if_opencode_running

    warn_if_opencode_running()

    try:
        conn = db.connect(readonly=True)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None
    try:
        version = _detect_version_or_exit(conn)
        top_sessions = db.get_sessions(conn, sort_by="size", limit=10, version=version)
        if not top_sessions:
            from ocgc.display import console

            console.print("[dim]No sessions found.[/]")
            return
        root_count, sub_count = db.get_session_count(conn, version=version)
        total_sessions = root_count + sub_count
        root_stats, sub_stats = db.get_part_type_stats_by_session_type(conn, version=version)
        total_bytes = sum(s.size_bytes for s in root_stats) + sum(s.size_bytes for s in sub_stats)
        avg_size = total_bytes / total_sessions if total_sessions else 0
        growth_rate = db.get_growth_rate(conn, version=version)
        fs_stats = db.get_filesystem_stats()
        orphans = db.get_orphan_session_diffs(conn, version=version)
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
                "projects": [
                    {
                        "directory": p.directory,
                        "project_id": p.project_id,
                        "session_count": p.session_count,
                        "data_size": p.data_size,
                        "snapshot_size": p.snapshot_size,
                        "total_size": p.total_size,
                        "last_active": p.last_active,
                    }
                    for p in projects
                ],
            }
            sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
            return

        if not projects:
            console.print("[dim]No projects found.[/]")
            return
        print_projects(projects)
    finally:
        conn.close()
