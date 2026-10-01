"""Click CLI entry point."""

import click


@click.group()
@click.version_option(package_name="ocgc", prog_name="ocgc")
def cli() -> None:
    """ocgc - OpenCode Garbage Collector.

    Analyze and reclaim storage used by OpenCode sessions, diffs, and snapshots.
    """


@cli.command()
def status() -> None:
    """Dashboard: DB size, session count, storage breakdown."""
    from ocgc.analyzer import run_status

    run_status()


@cli.command()
@click.option("--sort", "sort_by", type=click.Choice(["size", "age", "name"]), default="size", help="Sort sessions by")
@click.option("--limit", "-l", type=int, default=None, help="Limit number of sessions shown")
@click.option("--project", "-p", default=None, help="Filter sessions by project name or ID")
@click.option("--directory", "-d", default=None, help="Filter sessions by directory path or pattern")
def sessions(sort_by: str, limit: int | None, project: str | None, directory: str | None) -> None:
    """List sessions with sizes, ages, and types."""
    from ocgc.analyzer import run_sessions

    clean_proj = project.strip() if project and project.strip() else None
    clean_dir = directory.strip() if directory and directory.strip() else None
    run_sessions(sort_by=sort_by, limit=limit, project=clean_proj, directory=clean_dir)


@cli.command()
def analyze() -> None:
    """Deep analysis: biggest sessions, part type breakdown, growth rate."""
    from ocgc.analyzer import run_analyze

    run_analyze()


@cli.command()
@click.option(
    "--older-than", default=None,
    help="Filter sessions or tool output older than duration (e.g., 15m, 1h, 7d, 2w, 3mo)",
)
@click.option("--subagents", is_flag=True, default=False, help="Delete subagent sessions (parent_id IS NOT NULL)")
@click.option("--larger-than", default=None, help="Delete sessions larger than size (e.g., 50M, 1G)")
@click.option("--strip-reasoning", is_flag=True, default=False, help="Remove reasoning parts only (keeps sessions)")
@click.option("--session", "session_ids", multiple=True, help="Delete specific session by ID (repeatable)")
@click.option("--keep-latest", type=int, default=None, help="Keep N most recent sessions, delete the rest")
@click.option(
    "--project", "-p", default=None,
    help="Target specific project name or ID for cleanup (cleans all project sessions if no criteria given)",
)
@click.option(
    "--directory", "-d", default=None,
    help="Target specific workspace directory for cleanup (cleans all directory sessions if no criteria given)",
)
@click.option(
    "--archive-to", default=None,
    help="Archive sessions to Markdown files in specified directory before deleting",
)
@click.option(
    "--clean-snapshots", is_flag=True, default=False,
    help="Delete snapshot directories (all or filtered by --project/--directory)",
)
@click.option(
    "--clean-orphans", is_flag=True, default=False,
    help="Delete orphan session diff files (no matching session)",
)
@click.option(
    "--clean-tool-output", is_flag=True, default=False,
    help="Delete cached tool output files (filters by --older-than if provided)",
)
@click.option("--dry-run", "-n", is_flag=True, default=False, help="Show what would be deleted without doing it")
@click.option("--force", "-f", is_flag=True, default=False, help="Skip confirmation prompt")
def purge(
    older_than: str | None,
    subagents: bool,
    larger_than: str | None,
    strip_reasoning: bool,
    session_ids: tuple[str, ...],
    keep_latest: int | None,
    project: str | None,
    directory: str | None,
    archive_to: str | None,
    clean_snapshots: bool,
    clean_orphans: bool,
    clean_tool_output: bool,
    dry_run: bool,
    force: bool,
) -> None:
    """Delete sessions by age, type, size, project, directory, or ID."""
    if keep_latest is not None and keep_latest < 0:
        raise click.BadParameter("must be a non-negative integer", param_hint="'--keep-latest'")
    from ocgc.purger import run_clean_orphans, run_clean_snapshots, run_clean_tool_output, run_purge

    clean_proj = project.strip() if project and project.strip() else None
    clean_dir = directory.strip() if directory and directory.strip() else None
    clean_archive = archive_to.strip() if archive_to and archive_to.strip() else None

    has_session_filter = bool(
        older_than or subagents or larger_than or session_ids
        or keep_latest is not None
        or ((clean_proj or clean_dir) and not (clean_snapshots or clean_orphans or clean_tool_output))
    )
    if clean_archive and not has_session_filter:
        from ocgc.display import console
        console.print("[red]Error:[/] At least one purge selection flag is required with --archive-to.")
        console.print(
            "Use --older-than, --session, --larger-than, --keep-latest, or --subagents to select sessions to archive and purge."
        )
        raise SystemExit(1)

    if clean_snapshots:
        run_clean_snapshots(dry_run=dry_run, force=force, project=clean_proj, directory=clean_dir)
        has_more = (
            clean_orphans or clean_tool_output or older_than or subagents
            or larger_than or session_ids
            or keep_latest is not None or strip_reasoning
        )
        if not has_more:
            return

    if clean_orphans:
        run_clean_orphans(dry_run=dry_run, force=force)
        has_more = (
            clean_tool_output or older_than or subagents or larger_than
            or session_ids or keep_latest is not None
            or strip_reasoning
        )
        if not has_more:
            return

    if clean_tool_output:
        run_clean_tool_output(older_than=older_than, dry_run=dry_run, force=force)
        has_more = (
            older_than or subagents or larger_than
            or session_ids or keep_latest is not None
            or strip_reasoning
        )
        if not has_more:
            return

    run_purge(
        older_than=older_than,
        subagents=subagents,
        larger_than=larger_than,
        strip_reasoning=strip_reasoning,
        session_ids=session_ids,
        keep_latest=keep_latest,
        dry_run=dry_run,
        force=force,
        project=clean_proj,
        directory=clean_dir,
        archive_to=archive_to,
    )


@cli.command("export")
@click.option("--session", "-s", "session_ids", multiple=True, help="Export specific session by ID (repeatable)")
@click.option("--project", "-p", default=None, help="Filter sessions by project name or ID")
@click.option("--directory", "-d", default=None, help="Filter sessions by directory path or pattern")
@click.option("--older-than", default=None, help="Filter sessions older than duration (e.g., 7d, 30d)")
@click.option("--all", "all_sessions", is_flag=True, default=False, help="Export all sessions in database")
@click.option("--output", "-o", default="exports", show_default=True, help="Output directory or file path")
@click.option(
    "--include-reasoning/--no-reasoning",
    default=True,
    show_default=True,
    help="Include reasoning/thought process in export",
)
@click.option("--overwrite", is_flag=True, default=False, help="Overwrite existing files instead of incrementing suffix")
def export_cmd(
    session_ids: tuple[str, ...],
    project: str | None,
    directory: str | None,
    older_than: str | None,
    all_sessions: bool,
    output: str,
    include_reasoning: bool,
    overwrite: bool,
) -> None:
    """Export OpenCode sessions as readable GitHub-flavored Markdown files."""
    import os
    import time
    from pathlib import Path

    from ocgc import db
    from ocgc.display import console, print_export_result, warn_if_opencode_running
    from ocgc.exporter import ExportResult, export_session_to_file, export_sessions
    from ocgc.purger import parse_duration

    warn_if_opencode_running()

    clean_proj = project.strip() if project and project.strip() else None
    clean_dir = directory.strip() if directory and directory.strip() else None
    older_than_ms = parse_duration(older_than) if older_than else None
    now_ms = int(time.time() * 1000)
    deduped_sids = sorted({s.strip() for s in session_ids if s.strip()})

    has_filter = bool(
        deduped_sids or clean_proj or clean_dir or older_than_ms is not None or all_sessions
    )
    if not has_filter:
        console.print("[red]Error:[/] Please specify sessions to export.")
        console.print("Use --session <id>, --project <name>, --directory <path>, --older-than <dur>, or --all")
        raise SystemExit(1)

    try:
        conn = db.connect(readonly=True)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None

    try:
        try:
            version = db.detect_version(conn)
        except RuntimeError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1) from None

        target_ids: list[str] = []
        if deduped_sids and not (clean_proj or clean_dir or older_than_ms is not None or all_sessions):
            target_ids = deduped_sids
        else:
            target_ids = db.get_session_ids_for_purge(
                conn,
                older_than_ms=older_than_ms,
                session_ids=deduped_sids if deduped_sids else None,
                directory=clean_dir,
                project=clean_proj,
                now_ms=now_ms,
                version=version,
            )

        if not target_ids:
            console.print("[dim]No sessions found matching export criteria.[/]")
            return

        out_path = Path(os.path.expanduser(output.strip()))
        is_single_file_target = not out_path.is_dir() and bool(out_path.suffix)

        if is_single_file_target and len(target_ids) != 1:
            console.print(
                f"[red]Error:[/] Cannot export {len(target_ids)} sessions into a single file "
                f"('{out_path.name}'). Use a directory path instead."
            )
            raise SystemExit(1)

        # If single session and out_path looks like a specific file
        if len(target_ids) == 1 and is_single_file_target:
            try:
                transcript = db.get_session_transcript(conn, target_ids[0], version=version)
            except Exception as e:
                console.print(f"[red]Error reading session '{target_ids[0]}':[/] {e}")
                raise SystemExit(1) from None

            if not transcript:
                console.print(f"[red]Error:[/] Session '{target_ids[0]}' not found.")
                raise SystemExit(1)
            try:
                saved = export_session_to_file(
                    transcript,
                    output_path=out_path,
                    include_reasoning=include_reasoning,
                    overwrite=overwrite,
                )
                res = ExportResult(
                    sessions_exported=1,
                    bytes_written=saved.stat().st_size,
                )
                print_export_result(res, saved)
                return
            except (OSError, ValueError) as e:
                console.print(f"[red]Error exporting session '{target_ids[0]}':[/] {e}")
                raise SystemExit(1) from None

        try:
            with console.status(f"[bold cyan]Exporting {len(target_ids)} session(s) to {out_path}...[/]"):
                result = export_sessions(
                    session_ids=target_ids,
                    output_dir=out_path,
                    include_reasoning=include_reasoning,
                    overwrite=overwrite,
                    conn=conn,
                )
        except (OSError, ValueError) as e:
            console.print(f"[red]Error during batch export:[/] {e}")
            raise SystemExit(1) from None

        print_export_result(result, out_path)
        if result.errors:
            raise SystemExit(1)
    finally:
        conn.close()


@cli.command()
@click.option(
    "--mode",
    "-m",
    type=click.Choice(["truncate", "restart", "full", "passive"], case_sensitive=False),
    default="truncate",
    show_default=True,
    help="Checkpoint mode (truncate resets WAL to 0 bytes)",
)
@click.option("--force", "-f", is_flag=True, default=False, help="Skip confirmation prompt if opencode is running")
def checkpoint(mode: str, force: bool) -> None:
    """Flush opencode.db-wal pages into the main database (TRUNCATE also resets WAL to 0 bytes)."""
    from ocgc.purger import run_checkpoint

    run_checkpoint(mode=mode, force=force)


@cli.command()
@click.option("--force", "-f", is_flag=True, default=False, help="Skip confirmation prompt")
def vacuum(force: bool) -> None:
    """Run VACUUM to reclaim disk space after purge."""
    from ocgc.purger import run_vacuum

    run_vacuum(force=force)


@cli.command("install-skill")
@click.option("--dest", "-d", default=None, help="Custom target directory for the skill")
@click.option(
    "--workspace", "-w", is_flag=True, default=False,
    help="Install into current workspace directory (.opencode/skills/ocgc)",
)
def install_skill_cmd(dest: str | None, workspace: bool) -> None:
    """Install ocgc as a native OpenCode Skill."""
    if dest is not None and workspace:
        raise click.UsageError("--dest and --workspace cannot be used together")
    from ocgc.skill import run_install_skill

    run_install_skill(dest=dest, workspace=workspace)


