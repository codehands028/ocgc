"""Tests for the interactive terminal selector (ocgc browse)."""

import sqlite3
import time
from typing import Any

import pytest
from rich.console import Console

from ocgc.browser import (
    ActionType,
    BrowserState,
    KeyAction,
    KeyReader,
    render_browser_view,
    run_browser,
)
from ocgc.db import SessionRow


def _make_dummy_session(
    sid: str,
    title: str = "Test Session",
    size_bytes: int = 1024,
    age_offset: int = 3600,
    project_id: str | None = None,
    directory: str = "/tmp/proj",
) -> SessionRow:
    now_ms = int(time.time() * 1000)
    created_ms = now_ms - (age_offset * 1000)
    return SessionRow(
        id=sid,
        parent_id=None,
        directory=directory,
        title=title,
        time_created=created_ms,
        time_updated=created_ms,
        size_bytes=size_bytes,
        message_count=5,
        project_id=project_id,
    )


class TestKeyReader:
    def test_mock_keys_basic(self) -> None:
        reader = KeyReader(mock_keys=["\x1b[A", "j", "d", "r", " ", "a", "\r", "q", "?"])
        assert reader.read_action() == KeyAction.UP
        assert reader.read_action() == KeyAction.DOWN
        assert reader.read_action() == KeyAction.DELETE_TAG
        assert reader.read_action() == KeyAction.STRIP_TAG
        assert reader.read_action() == KeyAction.CLEAR_TAG
        assert reader.read_action() == KeyAction.TOGGLE_ALL
        assert reader.read_action() == KeyAction.ENTER
        assert reader.read_action() == KeyAction.QUIT
        assert reader.read_action() == KeyAction.HELP
        assert reader.read_action() == KeyAction.QUIT  # exhausted mock keys returns QUIT

    def test_escape_sequence_parsing(self) -> None:
        reader = KeyReader()
        assert reader.parse_ansi_sequence("\x1b[A") == KeyAction.UP
        assert reader.parse_ansi_sequence("\x1b[B") == KeyAction.DOWN
        assert reader.parse_ansi_sequence("\x1b[5~") == KeyAction.PAGE_UP
        assert reader.parse_ansi_sequence("\x1b[6~") == KeyAction.PAGE_DOWN
        assert reader.parse_ansi_sequence("\x1b[H") == KeyAction.HOME
        assert reader.parse_ansi_sequence("\x1b[F") == KeyAction.END
        assert reader.parse_ansi_sequence("\x1b") == KeyAction.QUIT


class TestBrowserState:
    def test_cursor_navigation(self) -> None:
        sessions = [_make_dummy_session(f"ses_{i}") for i in range(5)]
        state = BrowserState(sessions=sessions, page_size=2)

        assert state.cursor == 0
        assert state.page_offset == 0

        # Move down
        state.handle_action(KeyAction.DOWN)
        assert state.cursor == 1
        assert state.page_offset == 0

        # Move down past page boundary
        state.handle_action(KeyAction.DOWN)
        assert state.cursor == 2
        assert state.page_offset == 1

        # Move to end
        state.handle_action(KeyAction.END)
        assert state.cursor == 4
        assert state.page_offset == 3

        # Move down at end stays at end
        state.handle_action(KeyAction.DOWN)
        assert state.cursor == 4

        # Move to home
        state.handle_action(KeyAction.HOME)
        assert state.cursor == 0
        assert state.page_offset == 0

        # Move up at top stays at top
        state.handle_action(KeyAction.UP)
        assert state.cursor == 0

    def test_tagging_actions(self) -> None:
        sessions = [_make_dummy_session("ses_1"), _make_dummy_session("ses_2")]
        state = BrowserState(sessions=sessions, page_size=10)

        # Mark ses_1 as DELETE
        state.handle_action(KeyAction.DELETE_TAG)
        assert state.actions.get("ses_1") == ActionType.DELETE

        # Press d again toggles to NONE
        state.handle_action(KeyAction.DELETE_TAG)
        assert state.actions.get("ses_1") == ActionType.NONE

        # Mark ses_1 as STRIP
        state.handle_action(KeyAction.STRIP_TAG)
        assert state.actions.get("ses_1") == ActionType.STRIP_REASONING

        # Mark ses_1 as DELETE while currently STRIP -> becomes DELETE
        state.handle_action(KeyAction.DELETE_TAG)
        assert state.actions.get("ses_1") == ActionType.DELETE

        # Clear tag
        state.handle_action(KeyAction.CLEAR_TAG)
        assert state.actions.get("ses_1") == ActionType.NONE

    def test_toggle_all(self) -> None:
        sessions = [_make_dummy_session("ses_1"), _make_dummy_session("ses_2")]
        state = BrowserState(sessions=sessions, page_size=10)

        # Initially all NONE -> toggle all marks all as DELETE
        state.handle_action(KeyAction.TOGGLE_ALL)
        assert state.actions["ses_1"] == ActionType.DELETE
        assert state.actions["ses_2"] == ActionType.DELETE

        # Toggle all again clears all
        state.handle_action(KeyAction.TOGGLE_ALL)
        assert state.actions.get("ses_1") is ActionType.NONE
        assert state.actions.get("ses_2") is ActionType.NONE

    def test_stats_computation(self) -> None:
        s1 = _make_dummy_session("ses_1", size_bytes=1000)
        s2 = _make_dummy_session("ses_2", size_bytes=2000)
        s3 = _make_dummy_session("ses_3", size_bytes=3000)
        state = BrowserState(sessions=[s1, s2, s3], page_size=10)

        state.actions["ses_1"] = ActionType.DELETE
        state.actions["ses_2"] = ActionType.STRIP_REASONING

        stats = state.get_stats()
        assert stats.total_sessions == 3
        assert stats.delete_count == 1
        assert stats.delete_bytes == 1000
        assert stats.strip_count == 1
        assert stats.strip_bytes == 2000


class TestBrowserRendering:
    def test_render_view(self) -> None:
        sessions = [
            _make_dummy_session("ses_1", title="First Session", size_bytes=1024),
            _make_dummy_session("ses_2", title="Second Session", size_bytes=2048),
        ]
        state = BrowserState(sessions=sessions, page_size=5)
        state.actions["ses_1"] = ActionType.DELETE

        console = Console(width=100, record=True)
        view = render_browser_view(state, console_width=100)
        console.print(view)
        rendered = console.export_text()

        assert "ocgc browse" in rendered
        assert "First Session" in rendered
        assert "Second Session" in rendered
        assert "[D]" in rendered


class TestRunBrowserIntegration:
    def test_non_tty_error(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        # Simulate non-TTY stdin
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        console = Console(record=True)
        result = run_browser(console=console)
        assert result == 1
        assert "requires a TTY" in console.export_text()

    def test_empty_sessions(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        from ocgc import db

        db_file = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_file)
        # Create empty v2 tables
        conn.execute(
            "CREATE TABLE session_v2 ("
            "id TEXT PRIMARY KEY, title TEXT, directory TEXT, "
            "time_created INT, time_updated INT, project_id TEXT, parent_id TEXT)"
        )
        conn.execute("CREATE TABLE session_message (id TEXT PRIMARY KEY, session_id TEXT, data TEXT)")
        conn.commit()
        conn.close()

        monkeypatch.setattr(db, "get_db_path", lambda: db_file)
        reader = KeyReader(mock_keys=["q"])
        console = Console(record=True)
        code = run_browser(key_reader=reader, console=console)
        assert code == 0
        out = console.export_text()
        assert "No sessions found" in out

    def test_browse_execute_delete_and_strip(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        from ocgc import db

        db_file = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_file)
        # Create minimal v2 database schema
        conn.execute(
            """
            CREATE TABLE session_v2 (
                id TEXT PRIMARY KEY,
                parent_id TEXT,
                directory TEXT,
                title TEXT,
                time_created INT,
                time_updated INT,
                project_id TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE session_message (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                type TEXT NOT NULL,
                data TEXT NOT NULL
            )
            """
        )
        now_ms = int(time.time() * 1000)
        conn.execute(
            "INSERT INTO session_v2 VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("ses_del", None, "/tmp/p1", "Session To Delete", now_ms, now_ms, "p1"),
        )
        conn.execute(
            "INSERT INTO session_v2 VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("ses_strip", None, "/tmp/p2", "Session To Strip", now_ms, now_ms, "p2"),
        )
        # ses_del has larger data so it is sorted first under default sort_by='size'
        conn.execute(
            "INSERT INTO session_message VALUES ('m1', 'ses_del', 'message', 'larger session data to be deleted')"
        )
        # ses_strip has reasoning
        conn.execute(
            "INSERT INTO session_message VALUES ('m2', 'ses_strip', 'message', ?)",
            ('{"content": [{"type": "reasoning", "data": "deep thoughts"}, {"type": "text", "data": "hello"}]}',),
        )
        conn.commit()
        conn.close()

        monkeypatch.setattr(db, "get_db_path", lambda: db_file)
        monkeypatch.setattr(db, "check_opencode_running", lambda: False)

        # Mock keys: mark ses_del with 'd', move down 'j', mark ses_strip with 'r', enter '\r'
        keys = ["d", "j", "r", "\r"]
        reader = KeyReader(mock_keys=keys)
        console = Console(record=True)

        code = run_browser(
            sort_by="name",
            key_reader=reader,
            console=console,
            confirm_callback=lambda _prompt: True,
        )
        assert code == 0

        # Verify DB changes
        verify_conn = sqlite3.connect(db_file)
        sids = [row[0] for row in verify_conn.execute("SELECT id FROM session_v2").fetchall()]
        assert "ses_del" not in sids
        assert "ses_strip" in sids
        verify_conn.close()

    def test_browse_user_cancelled_prompt(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        from ocgc import db

        db_file = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_file)
        conn.execute(
            "CREATE TABLE session_v2 ("
            "id TEXT PRIMARY KEY, parent_id TEXT, directory TEXT, title TEXT, "
            "time_created INT, time_updated INT, project_id TEXT)"
        )
        conn.execute(
            "CREATE TABLE session_message ("
            "id TEXT PRIMARY KEY, session_id TEXT NOT NULL, type TEXT NOT NULL, data TEXT NOT NULL)"
        )
        now_ms = int(time.time() * 1000)
        conn.execute(
            "INSERT INTO session_v2 VALUES ('ses_1', NULL, '/tmp/p1', 'Session 1', ?, ?, 'p1')",
            (now_ms, now_ms),
        )
        conn.execute("INSERT INTO session_message VALUES ('m1', 'ses_1', 'message', 'data')")
        conn.commit()
        conn.close()

        monkeypatch.setattr(db, "get_db_path", lambda: db_file)
        monkeypatch.setattr(db, "check_opencode_running", lambda: False)

        reader = KeyReader(mock_keys=["d", "\r"])
        console = Console(record=True)
        # User rejects confirmation prompt
        code = run_browser(key_reader=reader, console=console, confirm_callback=lambda _prompt: False)
        assert code == 0
        assert "Operation cancelled by user" in console.export_text()

        # Verify not deleted
        verify_conn = sqlite3.connect(db_file)
        sids = [row[0] for row in verify_conn.execute("SELECT id FROM session_v2").fetchall()]
        assert "ses_1" in sids
        verify_conn.close()

    def test_browse_no_selection_submit(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        from ocgc import db

        db_file = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_file)
        conn.execute(
            "CREATE TABLE session_v2 ("
            "id TEXT PRIMARY KEY, parent_id TEXT, directory TEXT, title TEXT, "
            "time_created INT, time_updated INT, project_id TEXT)"
        )
        conn.execute(
            "CREATE TABLE session_message ("
            "id TEXT PRIMARY KEY, session_id TEXT NOT NULL, type TEXT NOT NULL, data TEXT NOT NULL)"
        )
        now_ms = int(time.time() * 1000)
        conn.execute(
            "INSERT INTO session_v2 VALUES ('ses_1', NULL, '/tmp/p1', 'Session 1', ?, ?, 'p1')",
            (now_ms, now_ms),
        )
        conn.execute("INSERT INTO session_message VALUES ('m1', 'ses_1', 'message', 'data')")
        conn.commit()
        conn.close()

        monkeypatch.setattr(db, "get_db_path", lambda: db_file)
        reader = KeyReader(mock_keys=["\r"])  # Submit without marking anything
        console = Console(record=True)
        code = run_browser(key_reader=reader, console=console)
        assert code == 0
        assert "No sessions marked" in console.export_text()

    def test_browse_quit_key(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        from ocgc import db

        db_file = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_file)
        conn.execute(
            "CREATE TABLE session_v2 ("
            "id TEXT PRIMARY KEY, parent_id TEXT, directory TEXT, title TEXT, "
            "time_created INT, time_updated INT, project_id TEXT)"
        )
        conn.execute(
            "CREATE TABLE session_message ("
            "id TEXT PRIMARY KEY, session_id TEXT NOT NULL, type TEXT NOT NULL, data TEXT NOT NULL)"
        )
        now_ms = int(time.time() * 1000)
        conn.execute(
            "INSERT INTO session_v2 VALUES ('ses_1', NULL, '/tmp/p1', 'Session 1', ?, ?, 'p1')",
            (now_ms, now_ms),
        )
        conn.execute("INSERT INTO session_message VALUES ('m1', 'ses_1', 'message', 'data')")
        conn.commit()
        conn.close()

        monkeypatch.setattr(db, "get_db_path", lambda: db_file)
        reader = KeyReader(mock_keys=["q"])
        console = Console(record=True)
        code = run_browser(key_reader=reader, console=console)
        assert code == 0
        assert "Browser exited without changes" in console.export_text()

    def test_browse_v1_database(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        from ocgc import db

        db_file = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_file)
        # Create minimal v1 database schema
        conn.execute(
            """
            CREATE TABLE session (
                id TEXT PRIMARY KEY,
                parent_id TEXT,
                directory TEXT,
                title TEXT,
                time_created INT,
                time_updated INT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE message (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                time_created INT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE part (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                type TEXT NOT NULL,
                data TEXT NOT NULL
            )
            """
        )
        now_ms = int(time.time() * 1000)
        conn.execute("INSERT INTO session VALUES ('s1', NULL, '/dir1', 'V1 Session', ?, ?)", (now_ms, now_ms))
        conn.execute("INSERT INTO message VALUES ('m1', 's1', ?)", (now_ms,))
        conn.execute("INSERT INTO part VALUES ('p1', 's1', 'm1', 'text', 'hello')")
        conn.commit()
        conn.close()

        monkeypatch.setattr(db, "get_db_path", lambda: db_file)
        monkeypatch.setattr(db, "check_opencode_running", lambda: False)

        reader = KeyReader(mock_keys=["d", "\r"])
        console = Console(record=True)
        code = run_browser(key_reader=reader, console=console, confirm_callback=lambda _prompt: True)
        assert code == 0

        verify_conn = sqlite3.connect(db_file)
        sids = [row[0] for row in verify_conn.execute("SELECT id FROM session").fetchall()]
        assert "s1" not in sids
        verify_conn.close()


class TestCliBrowseCommand:
    def test_browse_help(self) -> None:
        from click.testing import CliRunner

        from ocgc.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["browse", "--help"])
        assert result.exit_code == 0
        assert "Interactive TUI session selector" in result.output
        assert "--sort" in result.output
        assert "--limit" in result.output
        assert "--page-size" in result.output

