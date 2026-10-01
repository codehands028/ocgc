"""Purge and vacuum logic."""

import os
import re
import sqlite3
import time
from pathlib import Path

import click
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from ocgc import db
from ocgc.display import (
    C_DIM,
    C_VALUE,
    console,
    format_bytes,
    print_checkpoint_result,
    print_purge_summary,
    print_reasoning_summary,
    print_vacuum_result,
    warn_if_opencode_running,
    warn_opencode_running,
)


def parse_duration(s: str) -> int:
    """Parse duration string (e.g., 7d, 2w, 30d, 1h) to milliseconds."""
    m = re.match(r"^(\d+)\s*(m|h|d|w|mo)$", s.strip().lower())
    if not m:
        raise click.BadParameter(f"Invalid duration: {s!r}. Use e.g. 7d, 2w, 30d, 1h, 15m, 3mo")
    value = int(m.group(1))
    unit = m.group(2)
    multipliers = {"m": 60_000, "h": 3600_000, "d": 86400_000, "w": 604800_000, "mo": 2592000_000}
    return value * multipliers[unit]


def parse_size(s: str) -> int:
    """Parse size string (e.g., 50M, 1G, 500K) to bytes."""
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(k|m|g|kb|mb|gb)$", s.strip().lower())
    if not m:
        raise click.BadParameter(f"Invalid size: {s!r}. Use e.g. 50M, 1G, 500K")
    value = float(m.group(1))
    unit = m.group(2).rstrip("b")
    multipliers = {"k": 1024, "m": 1048576, "g": 1073741824}
    return int(value * multipliers[unit])


def _detect_version_or_exit(conn: sqlite3.Connection) -> int:
    try:
        return db.detect_version(conn)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None


def run_purge(
    older_than: str | None,
    subagents: bool,
    larger_than: str | None,
    strip_reasoning: bool,
    session_ids: tuple[str, ...],
    keep_latest: int | None,
    dry_run: bool,
    force: bool,
    project: str | None = None,
    directory: str | None = None,
    archive_to: str | None = None,
) -> None:
    clean_archive = os.path.expanduser(archive_to.strip()) if archive_to and archive_to.strip() else None

    opencode_running = db.check_opencode_running()
    if opencode_running:
        warn_opencode_running()
        if clean_archive and not dry_run and not force:
            console.print(
                "[red]Error:[/] OpenCode is currently running. Purging with --archive-to while OpenCode is active "
                "creates a risk of concurrent message loss. Please close OpenCode or pass --force to proceed."
            )
            raise SystemExit(1)
        if not dry_run and not force and not click.confirm("opencode is running. Continue anyway?"):
            return

    clean_proj = project.strip() if project and project.strip() else None
    clean_dir = directory.strip() if directory and directory.strip() else None

    has_filter = (
        older_than
        or subagents
        or larger_than
        or session_ids
        or keep_latest is not None
        or clean_proj is not None
        or clean_dir is not None
    )
    if not has_filter and (not strip_reasoning or clean_archive):
        if clean_archive:
            console.print("[red]Error:[/] At least one purge selection flag is required with --archive-to.")
            console.print(
                "Use --older-than, --session, --larger-than, --keep-latest, or --subagents to select sessions to archive and purge."
            )
        else:
            console.print("[red]Error:[/] At least one purge flag is required.")
            console.print(
                "Use --older-than, --subagents, --larger-than, --session, "
                "--keep-latest, --project, --directory, or --strip-reasoning"
            )
        raise SystemExit(1)

    older_than_ms = parse_duration(older_than) if older_than else None
    larger_than_bytes = parse_size(larger_than) if larger_than else None
    now_ms = int(time.time() * 1000)

    if strip_reasoning and not has_filter:
        # Strip reasoning from ALL sessions
        try:
            conn = db.connect(readonly=True)
        except FileNotFoundError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1) from None
        try:
            version = _detect_version_or_exit(conn)
            summary = db.get_reasoning_summary(conn, session_ids=None, version=version)
        finally:
            conn.close()

        if summary["part_count"] == 0:
            console.print("[dim]No reasoning parts found.[/]")
            return

        print_reasoning_summary(summary, dry_run=dry_run)

        if dry_run:
            return

        if not force and not click.confirm("Strip all reasoning parts?"):
            return

        conn = db.connect(readonly=False)
        try:
            count = db.strip_reasoning(conn, session_ids=None, version=version)
            console.print(f"[green]Deleted {count:,} reasoning parts.[/]")
        finally:
            conn.close()
        return

    # Get matching session IDs
    try:
        conn = db.connect(readonly=True)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None
    try:
        version = _detect_version_or_exit(conn)
        matched_ids = db.get_session_ids_for_purge(
            conn,
            older_than_ms=older_than_ms,
            subagents_only=subagents,
            larger_than_bytes=larger_than_bytes,
            session_ids=list(session_ids) if session_ids else None,
            keep_latest=keep_latest,
            directory=clean_dir,
            project=clean_proj,
            now_ms=now_ms,
            version=version,
        )

        if not matched_ids:
            console.print("[dim]No sessions match the given criteria.[/]")
            return

        if strip_reasoning:
            summary = db.get_reasoning_summary(conn, matched_ids, version=version)
            if summary["part_count"] == 0:
                console.print("[dim]No reasoning parts found in matching sessions.[/]")
                return
            print_reasoning_summary(
                summary,
                dry_run=dry_run,
                project=clean_proj,
                directory=clean_dir,
                archive_to=clean_archive,
            )
        else:
            summary = db.get_purge_summary(conn, matched_ids, version=version)
            # Count session diff files that would be cleaned
            diff_dir = db.get_storage_dir() / "storage" / "session_diff"
            diff_files = 0
            diff_bytes = 0
            if diff_dir.is_dir():
                for sid in matched_ids:
                    p = diff_dir / f"{sid}.json"
                    if p.exists():
                        diff_files += 1
                        diff_bytes += p.stat().st_size
            print_purge_summary(
                summary,
                dry_run=dry_run,
                diff_files=diff_files,
                diff_bytes=diff_bytes,
                project=clean_proj,
                directory=clean_dir,
                archive_to=clean_archive,
            )
    finally:
        conn.close()

    if dry_run:
        return

    if not force:
        has_criteria = (
            older_than
            or subagents
            or larger_than
            or session_ids
            or keep_latest is not None
        )
        action = "Strip reasoning from" if strip_reasoning else "Delete"
        if clean_archive:
            prompt = f"Archive to {clean_archive} and {action.lower()} {len(matched_ids)} session(s)?"
        elif not strip_reasoning and not has_criteria and (clean_proj or clean_dir):
            scope = clean_proj or clean_dir
            prompt = f"Delete ALL {len(matched_ids)} session(s) in {scope}?"
        else:
            prompt = f"{action} {len(matched_ids)} session(s)?"
        if not click.confirm(prompt):
            return

    try:
        conn = db.connect(readonly=False)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None
    try:
        if clean_archive:
            archive_dir = Path(clean_archive)
            from ocgc.exporter import export_sessions

            with console.status(f"[bold cyan]Archiving {len(matched_ids)} session(s) to Markdown...[/]"):
                try:
                    archive_res = export_sessions(
                        session_ids=matched_ids,
                        output_dir=archive_dir,
                        include_reasoning=True,
                        overwrite=False,
                        conn=conn,
                    )
                except Exception as e:
                    console.print(f"[red]Archiving failed:[/] {e}")
                    console.print("[red]Aborting operation to protect against data loss. No sessions were modified.[/]")
                    raise SystemExit(1) from None

            if archive_res.errors:
                console.print(f"[red]Error during archiving:[/] Failed to archive {len(archive_res.errors)} session(s):")
                for sid, err in archive_res.errors:
                    console.print(f"  [red]• {escape(str(sid))}: {escape(str(err))}[/]")
                console.print("[red]Aborting operation to protect against data loss. No sessions were modified.[/]")
                raise SystemExit(1)

            from ocgc.exporter import archive_session_diffs

            diff_copied, diff_failed = archive_session_diffs(
                session_ids=matched_ids,
                archive_dir=archive_dir,
            )

            if diff_failed:
                console.print(
                    f"[red]Error during archiving:[/] Failed to back up {len(diff_failed)} session diff file(s):"
                )
                for item in diff_failed:
                    console.print(f"  [red]• {escape(str(item))}[/]")
                console.print("[red]Aborting operation to protect against data loss. No sessions were modified.[/]")
                raise SystemExit(1)

            msg = f"[green]Archived {archive_res.sessions_exported} session(s) ({format_bytes(archive_res.bytes_written)})"
            if diff_copied > 0:
                msg += f" and {diff_copied} session diff file(s)"
            msg += f" to {escape(str(archive_dir))}.[/]"
            console.print(msg)

        if strip_reasoning:
            count = db.strip_reasoning(conn, matched_ids, version=version)
            console.print(f"[green]Deleted {count:,} reasoning parts from {len(matched_ids)} sessions.[/]")
        else:
            files_result = db.purge_sessions(conn, matched_ids, version=version)
            freed = format_bytes(summary["total_bytes"])
            msg = f"[green]Deleted {summary['session_count']:,} sessions, freed ~{freed}."
            if files_result.files_deleted:
                freed_bytes = format_bytes(files_result.bytes_freed)
                msg += f" Removed {files_result.files_deleted} session diff file(s) ({freed_bytes})."
            msg += "[/]"
            console.print(msg)
    finally:
        conn.close()

    console.print("[dim]Run 'ocgc checkpoint' to shrink WAL or 'ocgc vacuum' to reclaim DB pages.[/]")


def run_checkpoint(mode: str = "truncate", force: bool = False) -> None:
    """Run WAL checkpoint to flush and truncate opencode.db-wal."""
    if db.check_opencode_running():
        warn_opencode_running()
        if not force and not click.confirm(
            "opencode is currently running. Checkpoint might not truncate if locks are held. Continue anyway?"
        ):
            return

    path = db.get_db_path()
    if not path.exists():
        click.echo(f"Error: Database not found at {path}", err=True)
        raise SystemExit(1)

    norm_mode = mode.upper().strip()
    with console.status(f"[bold cyan]Running WAL checkpoint ({norm_mode})...[/]"):
        try:
            result = db.checkpoint_db(mode=norm_mode)
        except sqlite3.OperationalError as e:
            err_msg = str(e).lower()
            if "locked" in err_msg or "busy" in err_msg:
                console.print("[red]Error:[/] Database is locked. Is opencode still running? Close it and try again.")
            elif "readonly" in err_msg or "permission" in err_msg:
                console.print(f"[red]Error:[/] Database permission error: {e}")
            else:
                console.print(f"[red]Error:[/] Checkpoint failed: {e}")
            raise SystemExit(1) from None
        except (FileNotFoundError, sqlite3.Error, OSError) as e:
            console.print(f"[red]Error:[/] Checkpoint failed: {e}")
            raise SystemExit(1) from None

    print_checkpoint_result(result)
    if result.busy != 0:
        raise SystemExit(1)


def run_vacuum(force: bool = False) -> None:
    warn_if_opencode_running()

    db_info = db.get_db_info()
    if db_info.db_size == 0:
        path = db.get_db_path()
        if not path.exists():
            click.echo(f"Error: Database not found at {path}", err=True)
            raise SystemExit(1)
    console.print(f"[dim]Current DB size: {db_info.db_size / 1048576:.1f} MB[/]")
    console.print("[yellow]Warning:[/] VACUUM temporarily doubles disk usage.")
    console.print("[dim]Note: VACUUM will fail if opencode is running (DB locked) or if disk space is insufficient.[/]")

    if not force and not click.confirm("Proceed with VACUUM?"):
        return

    with console.status("[bold cyan]Running VACUUM...[/]"):
        try:
            before, after = db.vacuum_db()
        except sqlite3.OperationalError as e:
            err_msg = str(e).lower()
            if "locked" in err_msg or "busy" in err_msg:
                console.print("[red]Error:[/] Database is locked. Is opencode still running? Close it and try again.")
            elif "full" in err_msg or "no space" in err_msg or "disk" in err_msg:
                console.print("[red]Error:[/] Insufficient disk space. VACUUM needs roughly the DB size in free space.")
            else:
                console.print(f"[red]Error:[/] VACUUM failed: {e}")
            raise SystemExit(1) from None

    print_vacuum_result(before, after)


def run_clean_snapshots(
    dry_run: bool,
    force: bool,
    project: str | None = None,
    directory: str | None = None,
) -> None:
    clean_proj = project.strip() if project and project.strip() else None
    clean_dir = directory.strip() if directory and directory.strip() else None
    projects = db.get_snapshot_projects(project=clean_proj, directory=clean_dir)
    if not projects:
        filter_desc: list[str] = []
        if clean_proj:
            filter_desc.append(f"project '{escape(clean_proj)}'")
        if clean_dir:
            filter_desc.append(f"directory '{escape(clean_dir)}'")
        desc = f" for {' and '.join(filter_desc)}" if filter_desc else ""
        console.print(f"[dim]No snapshot directories found{desc}.[/]")
        return

    total_bytes = sum(size for _, size in projects)

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=C_DIM, justify="right")
    grid.add_column(style=C_VALUE)
    grid.add_row("Snapshot dirs", str(len(projects)))
    grid.add_row("Total size", format_bytes(total_bytes))
    if clean_proj:
        grid.add_row("Project filter", escape(clean_proj))
    if clean_dir:
        grid.add_row("Directory filter", escape(clean_dir))

    label = "[bold yellow]Dry Run — Snapshots to delete[/]" if dry_run else "[bold red]Clean Snapshots[/]"
    border = "yellow" if dry_run else "red"
    console.print(Panel(grid, title=label, border_style=border))

    if dry_run:
        return

    if not force:
        target_desc = (
            f"matching snapshot directories ({len(projects)})"
            if (clean_proj or clean_dir)
            else "all snapshot directories"
        )
        console.print(f"[yellow]Warning:[/] This deletes git snapshot data for {target_desc}.")
        console.print("[dim]Snapshots will be recreated by opencode as needed.[/]")
        prompt = f"Delete {len(projects)} snapshot director{'y' if len(projects) == 1 else 'ies'}?"
        if not click.confirm(prompt):
            return

    result = db.purge_snapshots(names=[name for name, _ in projects])
    freed = format_bytes(result.bytes_freed)
    console.print(f"[green]Deleted {result.files_deleted} snapshot dir(s), freed {freed}.[/]")


def run_clean_orphans(dry_run: bool, force: bool) -> None:
    try:
        conn = db.connect(readonly=True)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None
    try:
        version = _detect_version_or_exit(conn)
        orphans = db.get_orphan_session_diffs(conn, version=version)
    finally:
        conn.close()

    if not orphans:
        console.print("[dim]No orphan session diff files found.[/]")
        return

    total_bytes = sum(o.size for o in orphans)

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=C_DIM, justify="right")
    grid.add_column(style=C_VALUE)
    grid.add_row("Orphan files", str(len(orphans)))
    grid.add_row("Total size", format_bytes(total_bytes))

    label = "[bold yellow]Dry Run — Orphan diffs to delete[/]" if dry_run else "[bold red]Clean Orphans[/]"
    border = "yellow" if dry_run else "red"
    console.print(Panel(grid, title=label, border_style=border))

    if dry_run:
        return

    if not force and not click.confirm(f"Delete {len(orphans)} orphan session diff file(s)?"):
        return

    result = db.purge_orphan_diffs(orphans)
    console.print(f"[green]Deleted {result.files_deleted} orphan file(s), freed {format_bytes(result.bytes_freed)}.[/]")


def run_clean_tool_output(older_than: str | None, dry_run: bool, force: bool) -> None:
    if db.check_opencode_running():
        warn_opencode_running()
        if not dry_run and not force and not click.confirm(
            "opencode is running and may be writing tool output. Continue anyway?"
        ):
            return

    older_than_ms = parse_duration(older_than) if older_than else None
    now_ms = int(time.time() * 1000)
    files = db.get_tool_output_files(older_than_ms=older_than_ms, now_ms=now_ms)
    if not files:
        if older_than:
            console.print(f"[dim]No tool output files found older than {older_than}.[/]")
        else:
            console.print("[dim]No tool output files found.[/]")
        return

    total_bytes = sum(f.size for f in files)

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=C_DIM, justify="right")
    grid.add_column(style=C_VALUE)
    grid.add_row("Tool output files", str(len(files)))
    grid.add_row("Total size", format_bytes(total_bytes))
    if older_than:
        grid.add_row("Filter", f"older than {older_than}")

    label = "[bold yellow]Dry Run — Tool output files to delete[/]" if dry_run else "[bold red]Clean Tool Output[/]"
    border = "yellow" if dry_run else "red"
    console.print(Panel(grid, title=label, border_style=border))

    if dry_run:
        return

    prompt = f"Delete {len(files)} tool output file(s)?"
    if not force and not click.confirm(prompt):
        return

    result = db.purge_tool_outputs(files)
    freed = format_bytes(result.bytes_freed)
    console.print(f"[green]Deleted {result.files_deleted} tool output file(s), freed {freed}.[/]")
