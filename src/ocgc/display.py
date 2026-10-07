"""Rich formatting for terminal output."""

import time
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ocgc.db import (
    CheckpointResult,
    DBInfo,
    FilesystemStats,
    PartTypeStats,
    ProjectRow,
    SessionRow,
    StripLargeOutputsSummary,
)
from ocgc.units import format_bytes

if TYPE_CHECKING:
    from pathlib import Path

    from ocgc.doctor import DoctorReport
    from ocgc.exporter import ExportResult

console = Console()

# Color palette
C_HEADER = "bold cyan"
C_VALUE = "bold white"
C_DIM = "dim"
C_WARN = "bold yellow"
C_DANGER = "bold red"
C_SUCCESS = "bold green"
C_ROOT = "green"
C_SUB = "yellow"

PART_TYPE_COLORS = {
    "reasoning": "red",
    "tool": "blue",
    "text": "green",
    "step-start": "cyan",
    "step-finish": "magenta",
    "patch": "yellow",
    "file": "white",
    "compaction": "dim white",
}


def format_age(ms_epoch: int) -> str:
    now = time.time() * 1000
    delta_s = (now - ms_epoch) / 1000
    if delta_s < 0:
        return "just now"
    if delta_s < 60:
        return "<1m ago"
    if delta_s < 3600:
        return f"{int(delta_s / 60)}m ago"
    if delta_s < 86400:
        return f"{delta_s / 3600:.1f}h ago"
    days = delta_s / 86400
    if days < 30:
        return f"{int(days)}d ago"
    return f"{int(days / 30)}mo ago"


def warn_opencode_running() -> None:
    console.print(
        Panel(
            "[bold yellow]opencode appears to be running.[/]\n"
            "Writing to the DB while opencode is active may cause issues.\n"
            "Consider stopping opencode first.",
            title="[bold yellow]Warning[/]",
            border_style="yellow",
        )
    )


def warn_if_opencode_running() -> None:
    """Check if opencode is running and print a warning if so."""
    from ocgc.db import check_opencode_running

    if check_opencode_running():
        warn_opencode_running()


def print_status(
    db_info: DBInfo,
    root_count: int,
    sub_count: int,
    part_stats: list[PartTypeStats],
    age_dist: dict[str, int],
    fs_stats: FilesystemStats,
) -> None:
    # --- Header panel ---
    header = Table.grid(padding=(0, 2))
    header.add_column(style=C_DIM, justify="right")
    header.add_column(style=C_VALUE)
    header.add_row("Database", str(db_info.path))
    header.add_row("Schema", f"OpenCode v{db_info.version}")
    header.add_row("DB size", format_bytes(db_info.db_size))
    header.add_row("WAL size", format_bytes(db_info.wal_size))
    header.add_row("Total DB", f"[bold]{format_bytes(db_info.total_size)}[/]")
    header.add_row("", "")
    diff_info = f"{format_bytes(fs_stats.session_diff_size)}  ({fs_stats.session_diff_count} files)"
    header.add_row("Session diffs", diff_info)
    header.add_row("Snapshots", f"{format_bytes(fs_stats.snapshot_size)}  ({fs_stats.snapshot_count} projects)")
    tool_info = f"{format_bytes(fs_stats.tool_output_size)}  ({fs_stats.tool_output_count} files)"
    header.add_row("Tool output", tool_info)
    grand_total = db_info.total_size + fs_stats.total_size
    header.add_row("Total on disk", f"[bold]{format_bytes(grand_total)}[/]")
    header.add_row("", "")
    header.add_row("Sessions", f"[bold]{root_count + sub_count}[/]")
    header.add_row("  Root", f"[{C_ROOT}]{root_count}[/]")
    header.add_row("  Subagent", f"[{C_SUB}]{sub_count}[/]")

    console.print(Panel(header, title="[bold cyan]ocgc status[/]", border_style="cyan"))

    # --- Storage breakdown bar chart ---
    total_bytes = sum(s.size_bytes for s in part_stats)
    if total_bytes == 0:
        console.print("[dim]No part data found.[/]")
        return

    storage_table = Table(
        title="Storage by Part Type",
        show_header=True,
        header_style="bold",
        border_style="dim",
        padding=(0, 1),
    )
    storage_table.add_column("Type", style="bold", min_width=12)
    storage_table.add_column("Size", justify="right", min_width=10)
    storage_table.add_column("Count", justify="right", min_width=8)
    storage_table.add_column("%", justify="right", min_width=6)
    storage_table.add_column("Bar", min_width=30)

    max_bar = 30
    for s in part_stats:
        pct = s.size_bytes / total_bytes * 100
        bar_len = int(pct / 100 * max_bar)
        color = PART_TYPE_COLORS.get(s.type_name, "white")
        bar_text = Text("█" * bar_len + "░" * (max_bar - bar_len))
        bar_text.stylize(color, 0, bar_len)
        bar_text.stylize("dim", bar_len)
        storage_table.add_row(
            f"[{color}]{s.type_name}[/]",
            format_bytes(s.size_bytes),
            f"{s.count:,}",
            f"{pct:.1f}%",
            bar_text,
        )

    storage_table.add_section()
    storage_table.add_row(
        "[bold]Total[/]",
        f"[bold]{format_bytes(total_bytes)}[/]",
        f"[bold]{sum(s.count for s in part_stats):,}[/]",
        "100%",
        "",
    )
    console.print(storage_table)

    # --- Age distribution ---
    age_table = Table(
        title="Session Age Distribution",
        show_header=True,
        header_style="bold",
        border_style="dim",
        padding=(0, 1),
    )
    age_table.add_column("Period", style="bold", min_width=16)
    age_table.add_column("Sessions", justify="right", min_width=8)
    age_table.add_column("Bar", min_width=20)

    max_count = max(age_dist.values()) if age_dist else 1
    bar_width = 20
    for label, count in age_dist.items():
        bar_len = int(count / max_count * bar_width) if max_count > 0 else 0
        bar_text = Text("█" * bar_len + "░" * (bar_width - bar_len))
        bar_text.stylize("cyan", 0, bar_len)
        bar_text.stylize("dim", bar_len)
        age_table.add_row(label, str(count), bar_text)

    console.print(age_table)


def _format_dir_name(directory: str | None) -> str:
    if not directory:
        return ""
    normalized = directory.replace("\\", "/").rstrip("/")
    if not normalized:
        return "/"
    return normalized.rsplit("/", 1)[-1]


def print_sessions(sessions: list[SessionRow]) -> None:
    table = Table(
        title="Sessions",
        show_header=True,
        header_style="bold",
        border_style="dim",
        padding=(0, 1),
    )
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Directory", min_width=12, max_width=20)
    table.add_column("Title", min_width=15, max_width=40, no_wrap=True, overflow="ellipsis")
    table.add_column("Size", justify="right", style="bold")
    table.add_column("Age", justify="right")
    table.add_column("Type", justify="center")
    table.add_column("Msgs", justify="right")

    for s in sessions:
        dir_name = _format_dir_name(s.directory)
        title_str = s.title or "(untitled)"
        title = title_str[:37] + "..." if len(title_str) > 40 else title_str
        type_label = f"[{C_SUB}]sub[/]" if s.is_subagent else f"[{C_ROOT}]root[/]"
        sid = s.id[:12]
        table.add_row(
            sid,
            dir_name,
            title,
            format_bytes(s.size_bytes),
            format_age(s.time_created),
            type_label,
            str(s.message_count),
        )

    console.print(table)


def print_projects(projects: list[ProjectRow]) -> None:
    table = Table(
        title="Project Storage Dashboard",
        show_header=True,
        header_style="bold",
        border_style="dim",
        padding=(0, 1),
    )
    table.add_column(
        "Project / Workspace", min_width=12, no_wrap=True, overflow="ellipsis", ratio=3
    )
    table.add_column("Sessions", justify="right", no_wrap=True, ratio=1)
    table.add_column("Data Size", justify="right", style="bold", no_wrap=True, ratio=1)
    table.add_column("Snapshots", justify="right", no_wrap=True, ratio=1)
    table.add_column("Total", justify="right", style="bold", no_wrap=True, ratio=1)
    table.add_column("Last Active", justify="right", no_wrap=True, ratio=1)

    for p in projects:
        directory = escape(p.directory or p.key or "(unknown)")
        last_active_str = format_age(p.last_active) if p.last_active > 0 else "-"
        table.add_row(
            directory,
            f"{p.session_count:,}",
            format_bytes(p.data_size),
            format_bytes(p.snapshot_size),
            format_bytes(p.total_size),
            last_active_str,
        )

    console.print(table)


def print_analysis(
    top_sessions: list[SessionRow],
    avg_size: float,
    growth_rate: float | None,
    root_stats: list[PartTypeStats],
    sub_stats: list[PartTypeStats],
    total_sessions: int,
    fs_stats: FilesystemStats,
    orphan_count: int,
    orphan_bytes: int,
) -> None:
    # --- Top sessions ---
    top_table = Table(
        title="Top 10 Sessions by Size",
        show_header=True,
        header_style="bold",
        border_style="dim",
        padding=(0, 1),
    )
    top_table.add_column("#", style="dim", width=3)
    top_table.add_column("Title", min_width=20, max_width=40)
    top_table.add_column("Directory", max_width=18)
    top_table.add_column("Size", justify="right", style="bold")
    top_table.add_column("Type", justify="center")
    top_table.add_column("Msgs", justify="right")

    for i, s in enumerate(top_sessions, 1):
        dir_name = _format_dir_name(s.directory)
        title_str = s.title or "(untitled)"
        title = title_str[:37] + "..." if len(title_str) > 40 else title_str
        type_label = f"[{C_SUB}]sub[/]" if s.is_subagent else f"[{C_ROOT}]root[/]"
        top_table.add_row(str(i), title, dir_name, format_bytes(s.size_bytes), type_label, str(s.message_count))

    console.print(top_table)

    # --- Summary stats panel ---
    summary = Table.grid(padding=(0, 2))
    summary.add_column(style=C_DIM, justify="right")
    summary.add_column(style=C_VALUE)
    summary.add_row("Total sessions", str(total_sessions))
    total_part_bytes = sum(s.size_bytes for s in root_stats) + sum(s.size_bytes for s in sub_stats)
    summary.add_row("Total part data", format_bytes(total_part_bytes))
    summary.add_row("Avg session size", format_bytes(int(avg_size)))
    if growth_rate is not None:
        rate_color = C_DANGER if growth_rate > 100 else C_WARN if growth_rate > 20 else C_SUCCESS
        summary.add_row("Growth rate", f"[{rate_color}]{growth_rate:.1f} MB/active day[/]")
    summary.add_row("", "")
    diff_info = f"{format_bytes(fs_stats.session_diff_size)}  ({fs_stats.session_diff_count} files)"
    summary.add_row("Session diffs", diff_info)
    summary.add_row("Snapshots", f"{format_bytes(fs_stats.snapshot_size)}  ({fs_stats.snapshot_count} projects)")
    tool_info = f"{format_bytes(fs_stats.tool_output_size)}  ({fs_stats.tool_output_count} files)"
    summary.add_row("Tool output", tool_info)
    if orphan_count > 0:
        summary.add_row("Orphan diffs", f"[{C_WARN}]{orphan_count} files ({format_bytes(orphan_bytes)})[/]")

    console.print(Panel(summary, title="[bold cyan]Summary[/]", border_style="cyan"))

    # --- Root vs Subagent comparison ---
    comp_table = Table(
        title="Root vs Subagent Storage",
        show_header=True,
        header_style="bold",
        border_style="dim",
        padding=(0, 1),
    )
    comp_table.add_column("Category", style="bold")
    comp_table.add_column("Parts", justify="right")
    comp_table.add_column("Size", justify="right")

    root_total = sum(s.size_bytes for s in root_stats)
    sub_total = sum(s.size_bytes for s in sub_stats)
    root_parts = sum(s.count for s in root_stats)
    sub_parts = sum(s.count for s in sub_stats)

    comp_table.add_row(f"[{C_ROOT}]Root sessions[/]", f"{root_parts:,}", format_bytes(root_total))
    comp_table.add_row(f"[{C_SUB}]Subagent sessions[/]", f"{sub_parts:,}", format_bytes(sub_total))
    comp_table.add_section()
    total_size = format_bytes(root_total + sub_total)
    comp_table.add_row("[bold]Total[/]", f"[bold]{root_parts + sub_parts:,}[/]", f"[bold]{total_size}[/]")

    console.print(comp_table)


def print_purge_summary(
    summary: dict[str, int],
    dry_run: bool = False,
    diff_files: int = 0,
    diff_bytes: int = 0,
    project: str | None = None,
    directory: str | None = None,
    archive_to: str | None = None,
) -> None:
    label = "[bold yellow]Dry Run — Nothing will be deleted[/]" if dry_run else "[bold red]Purge Summary[/]"
    border = "yellow" if dry_run else "red"

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=C_DIM, justify="right")
    grid.add_column(style=C_VALUE)
    grid.add_row("Sessions", str(summary["session_count"]))
    grid.add_row("Messages", f"{summary['message_count']:,}")
    grid.add_row("Parts", f"{summary['part_count']:,}")
    grid.add_row("Data size", format_bytes(summary["total_bytes"]))
    if diff_files > 0:
        grid.add_row("Session diffs", f"{diff_files} file(s) ({format_bytes(diff_bytes)})")
    if archive_to:
        grid.add_row("Archive to", escape(archive_to))
    if project:
        grid.add_row("Project filter", escape(project))
    if directory:
        grid.add_row("Directory filter", escape(directory))

    console.print(Panel(grid, title=label, border_style=border))


def print_export_result(result: "ExportResult", output_path: "Path") -> None:
    from pathlib import Path

    exported = result.sessions_exported
    written = result.bytes_written
    errors = result.errors

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=C_DIM, justify="right")
    grid.add_column(style=C_VALUE)
    grid.add_row("Sessions exported", str(exported))
    grid.add_row("Total data written", format_bytes(written))
    grid.add_row("Destination", escape(str(Path(str(output_path)).resolve())))
    if errors:
        grid.add_row("Errors", f"[{C_DANGER}]{len(errors)} failed[/]")

    console.print(Panel(grid, title="[bold cyan]Export Complete[/]", border_style="cyan"))

    if errors:
        err_table = Table(
            title="Export Failures",
            show_header=True,
            header_style="bold red",
            border_style="dim",
            padding=(0, 1),
        )
        err_table.add_column("Session ID", style=C_VALUE)
        err_table.add_column("Error", style=C_DANGER)
        for sid, err in errors:
            err_table.add_row(escape(str(sid)), escape(str(err)))
        console.print(err_table)


def print_reasoning_summary(
    summary: dict[str, int],
    dry_run: bool = False,
    project: str | None = None,
    directory: str | None = None,
    archive_to: str | None = None,
) -> None:
    label = "[bold yellow]Dry Run — Reasoning parts to strip[/]" if dry_run else "[bold red]Strip Reasoning[/]"
    border = "yellow" if dry_run else "red"

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=C_DIM, justify="right")
    grid.add_column(style=C_VALUE)
    grid.add_row("Reasoning parts", f"{summary['part_count']:,}")
    grid.add_row("Data size", format_bytes(summary["total_bytes"]))
    if archive_to:
        grid.add_row("Archive to", escape(archive_to))
    if project:
        grid.add_row("Project filter", escape(project))
    if directory:
        grid.add_row("Directory filter", escape(directory))

    console.print(Panel(grid, title=label, border_style=border))


def print_strip_large_outputs_summary(
    summary: StripLargeOutputsSummary,
    dry_run: bool = False,
    project: str | None = None,
    directory: str | None = None,
    archive_to: str | None = None,
) -> None:
    label = (
        "[bold yellow]Dry Run — Large outputs/media to truncate[/]"
        if dry_run
        else "[bold red]Strip Large Outputs / Media[/]"
    )
    border = "yellow" if dry_run else "red"

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=C_DIM, justify="right")
    grid.add_column(style=C_VALUE)
    grid.add_row("Sessions", f"{summary.session_count:,}")
    grid.add_row("Large parts", f"{summary.part_count:,}")
    grid.add_row("Threshold", format_bytes(summary.threshold_bytes))
    grid.add_row("Original size", format_bytes(summary.original_bytes))
    reduction_label = "Estimated freed" if dry_run else "Reclaimed size"
    grid.add_row(reduction_label, f"[{C_SUCCESS}]{format_bytes(summary.reclaimed_bytes)}[/]")
    if archive_to:
        grid.add_row("Archive to", escape(archive_to))
    if project:
        grid.add_row("Project filter", escape(project))
    if directory:
        grid.add_row("Directory filter", escape(directory))

    console.print(Panel(grid, title=label, border_style=border))


def print_vacuum_result(before: int, after: int) -> None:
    saved = before - after
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=C_DIM, justify="right")
    grid.add_column(style=C_VALUE)
    grid.add_row("Before", format_bytes(before))
    grid.add_row("After", format_bytes(after))
    grid.add_row("Saved", f"[{C_SUCCESS}]{format_bytes(saved)}[/]" if saved > 0 else format_bytes(saved))

    console.print(Panel(grid, title="[bold cyan]Vacuum Complete[/]", border_style="cyan"))
    if saved > 0:
        console.print(
            f"\n[dim]✨ Reclaimed [bold]{format_bytes(saved)}[/bold] of disk space! "
            "If ocgc helped you, consider starring on GitHub: "
            "[link=https://github.com/codehands028/ocgc]https://github.com/codehands028/ocgc[/link] ⭐️[/dim]"
        )


def print_checkpoint_result(result: CheckpointResult) -> None:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=C_DIM, justify="right")
    grid.add_column(style=C_VALUE)
    grid.add_row("Mode", result.mode)
    grid.add_row("Frames", f"{result.checkpointed_frames} checkpointed / {result.log_frames} total")
    grid.add_row("WAL before", format_bytes(result.wal_before))
    grid.add_row("WAL after", format_bytes(result.wal_after))
    db_size_str = (
        f"{format_bytes(result.db_before)} -> {format_bytes(result.db_after)}"
        if result.db_before != result.db_after
        else format_bytes(result.db_after)
    )
    grid.add_row("DB size", db_size_str)
    grid.add_row("Total before", format_bytes(result.total_before))
    grid.add_row("Total after", format_bytes(result.total_after))

    saved = result.saved
    if saved > 0:
        grid.add_row("Saved", f"[{C_SUCCESS}]{format_bytes(saved)}[/]")
    elif result.wal_saved > 0:
        grid.add_row("WAL reclaimed", f"[{C_SUCCESS}]{format_bytes(result.wal_saved)}[/]")
    else:
        grid.add_row("Saved", "0 B")

    status_str = f"[{C_SUCCESS}]Completed[/]" if result.busy == 0 else "[yellow]Busy (locks held)[/]"
    grid.add_row("Status", status_str)

    if result.busy == 0:
        panel_title = "[bold cyan]WAL Checkpoint Complete[/]"
        border_color = "cyan"
    else:
        panel_title = "[bold yellow]WAL Checkpoint Incomplete[/]"
        border_color = "yellow"
    console.print(Panel(grid, title=panel_title, border_style=border_color))

    if result.busy != 0:
        if result.mode == "TRUNCATE":
            console.print(
                "\n[yellow]Warning:[/] Checkpoint could not fully truncate WAL because the database was busy "
                "(active readers or uncommitted transactions). Close OpenCode and run 'ocgc checkpoint' again."
            )
        else:
            console.print(
                f"\n[yellow]Warning:[/] {result.mode} checkpoint could not complete because the database was busy "
                "(active readers or uncommitted transactions). Close OpenCode and run 'ocgc checkpoint' again."
            )
    elif saved > 0:
        console.print(
            f"\n[dim]✨ Reclaimed [bold]{format_bytes(saved)}[/bold] of disk space! "
            "If ocgc helped you, consider starring on GitHub: "
            "[link=https://github.com/codehands028/ocgc]https://github.com/codehands028/ocgc[/link] ⭐️[/dim]"
        )
    elif result.wal_saved > 0:
        action = "Flushed and truncated" if result.mode == "TRUNCATE" else "Flushed"
        console.print(
            f"\n[dim]✨ {action} [bold]{format_bytes(result.wal_saved)}[/bold] "
            "of WAL log into main database.[/dim]"
        )
    elif result.checkpointed_frames > 0:
        console.print(
            f"\n[dim]✨ Checkpointed [bold]{result.checkpointed_frames}[/bold] WAL frame(s) into the main database. "
            f"Mode [bold]{result.mode}[/bold] does not truncate the WAL file, so its disk size remains unchanged.[/dim]"
        )
    elif result.wal_after > 0:
        console.print(
            f"\n[dim]No new frames to checkpoint; WAL still occupies {format_bytes(result.wal_after)} "
            "on disk (pre-allocated/active).[/dim]"
        )
    else:
        console.print("\n[dim]WAL was already empty (0 B). No pages needed checkpointing.[/dim]")


def print_doctor_report(report: "DoctorReport") -> None:
    """Render structured doctor health check report to the terminal using Rich."""
    from ocgc.doctor import CheckStatus

    grid = Table.grid(padding=(0, 1))
    grid.add_column()

    for item in report.checks:
        if item.status == CheckStatus.OK:
            icon = f"[{C_SUCCESS}][✓][/]"
            line = f"{icon} [bold]{item.title}:[/] [{C_SUCCESS}]{escape(item.message)}[/]"
        elif item.status == CheckStatus.WARN:
            icon = f"[{C_WARN}][!][/]"
            line = f"{icon} [bold yellow]{item.title}:[/] [{C_WARN}]{escape(item.message)}[/]"
        elif item.status == CheckStatus.ERROR:
            icon = f"[{C_DANGER}][✗][/]"
            line = f"{icon} [bold red]{item.title}:[/] [{C_DANGER}]{escape(item.message)}[/]"
        else:
            icon = f"[{C_HEADER}][i][/]"
            line = f"{icon} [bold]{item.title}:[/] {escape(item.message)}"

        grid.add_row(line)
        if item.detail:
            grid.add_row(f"    [dim]{escape(item.detail)}[/dim]")

    if report.suggested_actions:
        grid.add_row("")
        grid.add_row("[bold cyan]Suggested actions:[/]")
        for act in report.suggested_actions:
            grid.add_row(f"  [cyan]•[/] {escape(act)}")

    if report.has_critical_error:
        panel_title = "[bold red]ocgc doctor - Storage Health Check Failed[/]"
        border_color = "red"
    elif not report.is_healthy:
        panel_title = "[bold yellow]ocgc doctor - OpenCode Storage Health Check (Warnings)[/]"
        border_color = "yellow"
    else:
        panel_title = "[bold cyan]ocgc doctor - OpenCode Storage Health Check[/]"
        border_color = "cyan"

    console.print(Panel(grid, title=panel_title, border_style=border_color))

    if report.has_critical_error:
        console.print(
            "\n[bold red]Critical issues detected![/] Review errors above before running further operations."
        )
    elif not report.is_healthy:
        console.print(
            "\n[yellow]Health check finished with warnings.[/] Consider running the suggested actions above."
        )
    else:
        console.print(
            "\n[bold green]Storage health check passed![/] No anomalies or orphan data detected."
        )


