"""Interactive terminal session browser and selector (ocgc browse).

Provides keyboard-driven navigation, session tagging (Delete [D], Strip Reasoning [R]),
and atomic execution with preview and confirmation.
"""

from __future__ import annotations

import enum
import select
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text

from ocgc import db
from ocgc.display import console as default_console
from ocgc.display import format_age
from ocgc.units import format_bytes

if TYPE_CHECKING:
    from ocgc.db import SessionRow


class KeyAction(enum.Enum):
    UP = "UP"
    DOWN = "DOWN"
    PAGE_UP = "PAGE_UP"
    PAGE_DOWN = "PAGE_DOWN"
    HOME = "HOME"
    END = "END"
    DELETE_TAG = "DELETE_TAG"
    STRIP_TAG = "STRIP_TAG"
    CLEAR_TAG = "CLEAR_TAG"
    TOGGLE_ALL = "TOGGLE_ALL"
    ENTER = "ENTER"
    QUIT = "QUIT"
    HELP = "HELP"
    UNKNOWN = "UNKNOWN"


class ActionType(enum.Enum):
    NONE = "NONE"
    DELETE = "DELETE"
    STRIP_REASONING = "STRIP_REASONING"


@dataclass
class BrowserStats:
    total_sessions: int
    delete_count: int
    delete_bytes: int
    strip_count: int
    strip_bytes: int


class KeyReader:
    """Cross-platform terminal raw keystroke reader."""

    def __init__(self, mock_keys: Iterable[str] | None = None) -> None:
        self._mock_iter = iter(mock_keys) if mock_keys is not None else None

    def read_action(self) -> KeyAction:
        if self._mock_iter is not None:
            try:
                raw_key = next(self._mock_iter)
                return self.parse_ansi_sequence(raw_key)
            except StopIteration:
                return KeyAction.QUIT

        if sys.platform == "win32":
            return self._read_windows()
        return self._read_posix()

    def parse_ansi_sequence(self, seq: str) -> KeyAction:
        """Parse character or ANSI escape sequence into a KeyAction."""
        if not seq:
            return KeyAction.UNKNOWN

        # Escape sequences
        if seq in ("\x1b[A", "\x1bOA"):
            return KeyAction.UP
        if seq in ("\x1b[B", "\x1bOB"):
            return KeyAction.DOWN
        if seq in ("\x1b[5~",):
            return KeyAction.PAGE_UP
        if seq in ("\x1b[6~",):
            return KeyAction.PAGE_DOWN
        if seq in ("\x1b[H", "\x1b[1~", "\x1bOH"):
            return KeyAction.HOME
        if seq in ("\x1b[F", "\x1b[4~", "\x1bOF"):
            return KeyAction.END
        if seq == "\x1b":
            return KeyAction.QUIT

        # Single characters
        ch = seq
        if ch in ("\r", "\n"):
            return KeyAction.ENTER
        if ch in ("k", "K"):
            return KeyAction.UP
        if ch in ("j", "J"):
            return KeyAction.DOWN
        if ch in ("d", "D"):
            return KeyAction.DELETE_TAG
        if ch in ("r", "R"):
            return KeyAction.STRIP_TAG
        if ch in (" ", "u", "U"):
            return KeyAction.CLEAR_TAG
        if ch in ("a", "A"):
            return KeyAction.TOGGLE_ALL
        if ch in ("q", "Q", "\x03"):
            return KeyAction.QUIT
        if ch in ("?", "h", "H"):
            return KeyAction.HELP
        if ch == "g":
            return KeyAction.HOME
        if ch == "G":
            return KeyAction.END

        return KeyAction.UNKNOWN

    def _read_posix(self) -> KeyAction:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                # Check for escape sequence
                rlist, _, _ = select.select([sys.stdin], [], [], 0.05)
                if rlist:
                    ch2 = sys.stdin.read(1)
                    if ch2 in ("[", "O"):
                        seq = "\x1b" + ch2
                        while True:
                            rlist, _, _ = select.select([sys.stdin], [], [], 0.02)
                            if not rlist:
                                break
                            seq += sys.stdin.read(1)
                            if seq[-1].isalpha() or seq[-1] == "~":
                                break
                        return self.parse_ansi_sequence(seq)
                    return self.parse_ansi_sequence("\x1b" + ch2)
                return KeyAction.QUIT
            return self.parse_ansi_sequence(ch)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def _read_windows(self) -> KeyAction:
        import msvcrt

        getwch = getattr(msvcrt, "getwch", None)
        if getwch is None:
            return KeyAction.UNKNOWN
        ch: str = getwch()
        if ch in ("\x00", "\xe0"):
            # Extended key
            ch2: str = getwch()
            mapping = {
                "H": KeyAction.UP,
                "P": KeyAction.DOWN,
                "I": KeyAction.PAGE_UP,
                "Q": KeyAction.PAGE_DOWN,
                "G": KeyAction.HOME,
                "O": KeyAction.END,
            }
            return mapping.get(ch2, KeyAction.UNKNOWN)
        if ch == "\x1b":
            return KeyAction.QUIT
        return self.parse_ansi_sequence(ch)


@dataclass
class BrowserState:
    sessions: list[SessionRow]
    cursor: int = 0
    page_offset: int = 0
    page_size: int = 10
    actions: dict[str, ActionType] = field(default_factory=dict)
    show_help: bool = False
    is_submitted: bool = False
    is_cancelled: bool = False
    project_filter: str | None = None
    directory_filter: str | None = None
    sort_by: str = "size"

    def __post_init__(self) -> None:
        if self.page_size < 1:
            self.page_size = 10
        self._adjust_page()

    @property
    def current_session(self) -> SessionRow | None:
        if not self.sessions or self.cursor < 0 or self.cursor >= len(self.sessions):
            return None
        return self.sessions[self.cursor]

    def _adjust_page(self) -> None:
        if not self.sessions:
            self.cursor = 0
            self.page_offset = 0
            return
        self.cursor = max(0, min(self.cursor, len(self.sessions) - 1))
        if self.cursor < self.page_offset:
            self.page_offset = self.cursor
        elif self.cursor >= self.page_offset + self.page_size:
            self.page_offset = self.cursor - self.page_size + 1

    def handle_action(self, action: KeyAction) -> bool:
        """Handle user action, return True if loop should continue, False to exit."""
        if action == KeyAction.QUIT:
            self.is_cancelled = True
            return False
        if action == KeyAction.ENTER:
            self.is_submitted = True
            return False
        if action == KeyAction.HELP:
            self.show_help = not self.show_help
            return True

        if not self.sessions:
            return True

        if action == KeyAction.UP:
            if self.cursor > 0:
                self.cursor -= 1
                self._adjust_page()
        elif action == KeyAction.DOWN:
            if self.cursor < len(self.sessions) - 1:
                self.cursor += 1
                self._adjust_page()
        elif action == KeyAction.PAGE_UP:
            self.cursor = max(0, self.cursor - self.page_size)
            self._adjust_page()
        elif action == KeyAction.PAGE_DOWN:
            self.cursor = min(len(self.sessions) - 1, self.cursor + self.page_size)
            self._adjust_page()
        elif action == KeyAction.HOME:
            self.cursor = 0
            self._adjust_page()
        elif action == KeyAction.END:
            self.cursor = len(self.sessions) - 1
            self._adjust_page()
        elif action == KeyAction.DELETE_TAG:
            curr = self.current_session
            if curr:
                if self.actions.get(curr.id) == ActionType.DELETE:
                    self.actions[curr.id] = ActionType.NONE
                else:
                    self.actions[curr.id] = ActionType.DELETE
        elif action == KeyAction.STRIP_TAG:
            curr = self.current_session
            if curr:
                if self.actions.get(curr.id) == ActionType.STRIP_REASONING:
                    self.actions[curr.id] = ActionType.NONE
                else:
                    self.actions[curr.id] = ActionType.STRIP_REASONING
        elif action == KeyAction.CLEAR_TAG:
            curr = self.current_session
            if curr:
                self.actions[curr.id] = ActionType.NONE
        elif action == KeyAction.TOGGLE_ALL:
            # If any active actions exist, clear all. Otherwise, mark all as DELETE.
            has_active = any(act in (ActionType.DELETE, ActionType.STRIP_REASONING) for act in self.actions.values())
            if has_active:
                for s in self.sessions:
                    self.actions[s.id] = ActionType.NONE
            else:
                for s in self.sessions:
                    self.actions[s.id] = ActionType.DELETE

        return True

    def get_stats(self) -> BrowserStats:
        total = len(self.sessions)
        del_count = 0
        del_bytes = 0
        strip_count = 0
        strip_bytes = 0

        for s in self.sessions:
            act = self.actions.get(s.id, ActionType.NONE)
            if act == ActionType.DELETE:
                del_count += 1
                del_bytes += s.size_bytes
            elif act == ActionType.STRIP_REASONING:
                strip_count += 1
                strip_bytes += s.size_bytes

        return BrowserStats(
            total_sessions=total,
            delete_count=del_count,
            delete_bytes=del_bytes,
            strip_count=strip_count,
            strip_bytes=strip_bytes,
        )


def render_browser_view(state: BrowserState, console_width: int = 100) -> RenderableType:
    """Render the browser UI: Header, Table of Sessions, and Footer."""
    stats = state.get_stats()

    # Header title & filter info
    filters = []
    if state.project_filter:
        filters.append(f"project: [bold]{state.project_filter}[/]")
    if state.directory_filter:
        filters.append(f"directory: [bold]{state.directory_filter}[/]")
    filters.append(f"sort: [bold]{state.sort_by}[/]")
    filter_str = " | ".join(filters)

    header_text = Text()
    header_text.append("ocgc browse - Interactive Session Selector", style="bold cyan")
    header_text.append(f" ({filter_str})\n", style="dim")
    header_text.append(f"Total: {stats.total_sessions} sessions | ", style="white")
    del_str = f"Marked for Delete [D]: {stats.delete_count} ({format_bytes(stats.delete_bytes)}) | "
    header_text.append(del_str, style="bold red")
    strip_str = f"Marked to Strip [R]: {stats.strip_count} ({format_bytes(stats.strip_bytes)})"
    header_text.append(strip_str, style="bold yellow")

    table = Table(expand=True, box=None, padding=(0, 1), show_header=True)
    table.add_column("Act", justify="center", width=5)
    table.add_column("▶", justify="center", width=2)
    table.add_column("ID", style="cyan", no_wrap=True, width=16)
    table.add_column("Title", style="white", ratio=3)
    table.add_column("Project / Directory", style="dim", ratio=2)
    table.add_column("Size", justify="right", style="bold white", width=10)
    table.add_column("Msgs", justify="right", style="dim", width=6)
    table.add_column("Age", justify="right", style="dim", width=8)

    visible_sessions = state.sessions[state.page_offset : state.page_offset + state.page_size]
    for idx, s in enumerate(visible_sessions):
        abs_idx = state.page_offset + idx
        is_current = abs_idx == state.cursor
        act = state.actions.get(s.id, ActionType.NONE)

        if act == ActionType.DELETE:
            act_text = Text("[D]", style="bold red")
        elif act == ActionType.STRIP_REASONING:
            act_text = Text("[R]", style="bold yellow")
        else:
            act_text = Text(" · ", style="dim")

        cursor_text = Text("▶", style="bold green") if is_current else Text(" ")

        # Short ID display
        short_id = s.id[:14] + ".." if len(s.id) > 16 else s.id
        title = s.title if s.title else "(untitled)"
        proj = s.project_id or s.directory or ""

        row_style = "reverse" if is_current else None
        table.add_row(
            act_text,
            cursor_text,
            short_id,
            title,
            proj,
            format_bytes(s.size_bytes),
            str(s.message_count),
            format_age(s.time_created),
            style=row_style,
        )

    # Footer navigation & help
    total_pages = max(1, (len(state.sessions) + state.page_size - 1) // state.page_size)
    curr_page = (state.cursor // state.page_size) + 1 if state.sessions else 1

    footer_text = Text()
    footer_text.append(f"Page {curr_page}/{total_pages} | ", style="dim")
    footer_text.append("[↑/↓/j/k] Move  ", style="bold white")
    footer_text.append("[PgUp/PgDn] Page  ", style="bold white")
    footer_text.append("[d] Delete  ", style="bold red")
    footer_text.append("[r] Strip  ", style="bold yellow")
    footer_text.append("[Space/u] Unmark  ", style="white")
    footer_text.append("[a] Toggle All  ", style="white")
    footer_text.append("[Enter] Confirm  ", style="bold green")
    footer_text.append("[?] Help  ", style="cyan")
    footer_text.append("[q] Quit", style="dim")

    elements: list[RenderableType] = [
        Panel(header_text, border_style="cyan", padding=(0, 1)),
        table,
        Panel(footer_text, border_style="dim", padding=(0, 1)),
    ]

    if state.show_help:
        help_table = Table(box=None, padding=(0, 2), show_header=False)
        help_table.add_column("Key", style="bold cyan", width=16)
        help_table.add_column("Description", style="white")
        help_table.add_row("↑ / k", "Move cursor up")
        help_table.add_row("↓ / j", "Move cursor down")
        help_table.add_row("PageUp / PageDown", "Scroll one page up/down")
        help_table.add_row("Home / g, End / G", "Jump to first / last session")
        help_table.add_row("d", "Toggle DELETE flag [D] on highlighted session")
        help_table.add_row("r", "Toggle STRIP_REASONING flag [R] on highlighted session")
        help_table.add_row("Space / u", "Clear all flags from highlighted session")
        help_table.add_row("a", "Toggle all sessions (mark all as [D] / clear all)")
        help_table.add_row("Enter", "Submit selected sessions for confirmation and execution")
        help_table.add_row("q / Esc / Ctrl+C", "Quit without making any changes")
        help_table.add_row("?", "Toggle this help panel")
        elements.append(Panel(help_table, title="Keybindings Help", border_style="yellow"))

    return Group(*elements)


def run_browser(
    sort_by: str = "size",
    limit: int | None = None,
    project: str | None = None,
    directory: str | None = None,
    page_size: int = 10,
    key_reader: KeyReader | None = None,
    confirm_callback: Callable[[str], bool] | None = None,
    console: Console | None = None,
    db_path: Path | None = None,
) -> int:
    """Run the interactive session browser."""
    c = console or default_console

    # TTY verification: if real terminal and stdin is not a tty, fail fast
    if key_reader is None and not sys.stdin.isatty():
        c.print("[red]Error:[/] Interactive browse requires a TTY terminal.")
        return 1

    reader = key_reader or KeyReader()

    try:
        conn = db.connect(readonly=True, path=db_path)
    except FileNotFoundError as e:
        c.print(f"[red]Error:[/] {e}")
        return 1

    try:
        version = db.detect_version(conn)
        sessions = db.get_sessions(
            conn,
            sort_by=sort_by,
            limit=limit,
            directory=directory,
            project=project,
            version=version,
        )
    finally:
        conn.close()

    if not sessions:
        c.print("[dim]No sessions found matching criteria.[/]")
        return 0

    state = BrowserState(
        sessions=sessions,
        page_size=page_size,
        project_filter=project,
        directory_filter=directory,
        sort_by=sort_by,
    )

    # If running with mock keys (e.g. testing)
    is_mock = reader._mock_iter is not None

    if is_mock:
        while True:
            action = reader.read_action()
            if not state.handle_action(action):
                break
    else:
        with Live(
            render_browser_view(state, console_width=c.width),
            console=c,
            screen=True,
            auto_refresh=False,
        ) as live:
            while True:
                live.update(render_browser_view(state, console_width=c.width), refresh=True)
                try:
                    action = reader.read_action()
                except (KeyboardInterrupt, EOFError):
                    state.is_cancelled = True
                    break
                if not state.handle_action(action):
                    break

    if state.is_cancelled or not state.is_submitted:
        c.print("[dim]Browser exited without changes.[/]")
        return 0

    # User submitted actions
    delete_ids = [s.id for s in state.sessions if state.actions.get(s.id) == ActionType.DELETE]
    strip_ids = [s.id for s in state.sessions if state.actions.get(s.id) == ActionType.STRIP_REASONING]

    if not delete_ids and not strip_ids:
        c.print("[yellow]No sessions marked for deletion or stripping. Exited without changes.[/]")
        return 0

    # Display confirmation preview
    stats = state.get_stats()
    c.print()
    preview_table = Table(title="[bold]Confirm Actions Preview[/]", expand=False)
    preview_table.add_column("Action", style="bold")
    preview_table.add_column("Sessions", justify="right")
    preview_table.add_column("Data Reclaimed", justify="right")

    if delete_ids:
        preview_table.add_row(
            "[bold red]Delete [D][/]",
            str(stats.delete_count),
            format_bytes(stats.delete_bytes),
        )
    if strip_ids:
        preview_table.add_row(
            "[bold yellow]Strip Reasoning [R][/]",
            str(stats.strip_count),
            format_bytes(stats.strip_bytes),
        )
    c.print(preview_table)
    c.print()

    if db.check_opencode_running():
        c.print(
            Panel(
                "[bold yellow]Warning: OpenCode appears to be running.[/]\n"
                "Modifying the database while OpenCode is active may cause concurrency conflicts.",
                border_style="yellow",
            )
        )

    # Confirm prompt
    confirmed = False
    if confirm_callback is not None:
        confirmed = confirm_callback("Proceed with the selected actions?")
    else:
        confirmed = Confirm.ask("Proceed with the selected actions?", default=False)

    if not confirmed:
        c.print("[dim]Operation cancelled by user.[/]")
        return 0

    # Execute mutations
    try:
        write_conn = db.connect(readonly=False, path=db_path)
    except FileNotFoundError as e:
        c.print(f"[red]Error:[/] {e}")
        return 1

    try:
        write_version = db.detect_version(write_conn)
        purged_diffs = 0
        if delete_ids:
            with c.status("[bold red]Deleting marked sessions...[/]"):
                res = db.purge_sessions(write_conn, delete_ids, version=write_version)
                purged_diffs = res.files_deleted

        stripped_parts = 0
        if strip_ids:
            with c.status("[bold yellow]Stripping reasoning from marked sessions...[/]"):
                stripped_parts = db.strip_reasoning(write_conn, strip_ids, version=write_version)

        c.print(
            Panel(
                f"[bold green]Successfully executed actions:[reset]\n"
                f" • Deleted [bold]{len(delete_ids)}[/] session(s) ({purged_diffs} diff files removed)\n"
                f" • Stripped reasoning from [bold]{len(strip_ids)}[/] session(s) ({stripped_parts} parts removed)\n\n"
                f"[dim]Tip: Run 'ocgc checkpoint' or 'ocgc vacuum' to reclaim free SQLite pages.[/]",
                title="[bold green]Success[/]",
                border_style="green",
            )
        )
    finally:
        write_conn.close()

    return 0
