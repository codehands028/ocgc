"""Comprehensive tests verifying compatibility with both OpenCode v1 and v2 schemas."""

import json
import os
import sqlite3
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from ocgc import db
from ocgc.cli import cli


def create_v1_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE session (
            id TEXT PRIMARY KEY,
            parent_id TEXT,
            directory TEXT NOT NULL,
            title TEXT,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL
        );
        CREATE TABLE message (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            data TEXT NOT NULL
        );
        CREATE TABLE part (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            data TEXT NOT NULL
        );
        CREATE TABLE todo (
            session_id TEXT NOT NULL,
            content TEXT NOT NULL
        );
        CREATE TABLE session_share (
            session_id TEXT PRIMARY KEY,
            url TEXT NOT NULL
        );
    """)

    now = int(time.time() * 1000)
    day = 86400 * 1000

    # Insert root session
    conn.execute(
        "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
        ("ses_v1_root", None, "/path/to/project", "V1 Root Session", now - 2 * day, now - 2 * day),
    )
    # Insert subagent session
    conn.execute(
        "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
        ("ses_v1_sub", "ses_v1_root", "/path/to/project", "V1 Subagent Session", now - day, now - day),
    )

    # Insert messages & parts for root
    conn.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
        ("msg_1", "ses_v1_root", now - 2 * day, now - 2 * day, "{}"),
    )
    conn.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
        ("part_1", "msg_1", "ses_v1_root", now - 2 * day, now - 2 * day, json.dumps({"type": "text", "text": "hello"})),
    )
    conn.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
        (
            "part_2",
            "msg_1",
            "ses_v1_root",
            now - 2 * day,
            now - 2 * day,
            json.dumps({"type": "reasoning", "text": "thinking..."}),
        ),
    )
    conn.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
        ("part_3", "msg_1", "ses_v1_root", now - 2 * day, now - 2 * day, json.dumps({"type": "tool", "call": "read"})),
    )

    # Insert messages & parts for subagent
    conn.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
        ("msg_2", "ses_v1_sub", now - day, now - day, "{}"),
    )
    conn.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
        (
            "part_4",
            "msg_2",
            "ses_v1_sub",
            now - day,
            now - day,
            json.dumps({"type": "reasoning", "text": "sub thinking"}),
        ),
    )

    conn.commit()
    return conn


def create_v2_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE session_v2 (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            workspace_id TEXT,
            parent_id TEXT,
            fork_session_id TEXT,
            fork_boundary TEXT,
            slug TEXT NOT NULL,
            directory TEXT NOT NULL,
            path TEXT,
            title TEXT,
            version TEXT NOT NULL,
            share_url TEXT,
            summary_additions INTEGER,
            summary_deletions INTEGER,
            summary_files INTEGER,
            summary_diffs TEXT,
            metadata TEXT,
            cost REAL DEFAULT 0 NOT NULL,
            tokens_input INTEGER DEFAULT 0 NOT NULL,
            tokens_output INTEGER DEFAULT 0 NOT NULL,
            tokens_reasoning INTEGER DEFAULT 0 NOT NULL,
            tokens_cache_read INTEGER DEFAULT 0 NOT NULL,
            tokens_cache_write INTEGER DEFAULT 0 NOT NULL,
            revert TEXT,
            permission TEXT,
            agent TEXT,
            model TEXT,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            time_idle INTEGER,
            time_viewed INTEGER,
            idle_outcome TEXT,
            time_compacting INTEGER,
            time_archived INTEGER,
            time_suspended INTEGER,
            resume_attempts INTEGER DEFAULT 0 NOT NULL
        );
        CREATE TABLE session_message (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            type TEXT NOT NULL,
            seq INTEGER NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            data TEXT NOT NULL
        );
        CREATE TABLE session_inbox (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            type TEXT NOT NULL,
            payload TEXT NOT NULL,
            delivery TEXT NOT NULL,
            enqueued_seq INTEGER NOT NULL,
            time_created INTEGER NOT NULL
        );
        CREATE TABLE session_pending (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            type TEXT NOT NULL,
            data TEXT NOT NULL,
            delivery TEXT,
            admitted_seq INTEGER NOT NULL,
            time_created INTEGER NOT NULL
        );
        CREATE TABLE instruction_entry (
            session_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            removed INTEGER DEFAULT 0 NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            PRIMARY KEY(session_id, key)
        );
        CREATE TABLE instruction_state (
            session_id TEXT PRIMARY KEY,
            epoch_start INTEGER NOT NULL,
            through_seq INTEGER NOT NULL,
            initial_values TEXT NOT NULL,
            current_values TEXT NOT NULL
        );
        CREATE TABLE event_sequence (
            aggregate_id TEXT PRIMARY KEY,
            seq INTEGER NOT NULL,
            owner_id TEXT
        );
        CREATE TABLE event (
            id TEXT PRIMARY KEY,
            aggregate_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            created INTEGER DEFAULT 0 NOT NULL,
            type TEXT NOT NULL,
            data TEXT NOT NULL
        );
    """)

    now = int(time.time() * 1000)
    day = 86400 * 1000

    # Root session
    conn.execute(
        """
        INSERT INTO session_v2 (
            id, project_id, parent_id, slug, directory, title, version,
            time_created, time_updated, tokens_reasoning
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            "ses_v2_root",
            "proj_1",
            None,
            "root-slug",
            "/path/to/project",
            "V2 Root Session",
            "v2",
            now - 2 * day,
            now - 2 * day,
            150,
        ),
    )

    # Subagent session
    conn.execute(
        """
        INSERT INTO session_v2 (
            id, project_id, parent_id, slug, directory, title, version,
            time_created, time_updated, tokens_reasoning
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            "ses_v2_sub",
            "proj_1",
            "ses_v2_root",
            "sub-slug",
            "/path/to/project",
            "V2 Subagent Session",
            "v2",
            now - day,
            now - day,
            50,
        ),
    )

    # Messages in v2: user message
    user_data = json.dumps({"time": {"created": now - 2 * day}, "text": "User question"})
    conn.execute(
        "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("msg_v2_1", "ses_v2_root", "user", 1, now - 2 * day, now - 2 * day, user_data),
    )

    # Assistant message with reasoning and tool
    asst_data_1 = json.dumps({
        "time": {"created": now - 2 * day},
        "content": [
            {"type": "reasoning", "text": "Deep thinking here"},
            {"type": "tool", "id": "tool_1", "name": "bash", "state": {"status": "completed"}},
        ],
        "tokens": {"input": 100, "output": 50, "reasoning": 150},
    })
    conn.execute(
        "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("msg_v2_2", "ses_v2_root", "assistant", 2, now - 2 * day, now - 2 * day, asst_data_1),
    )

    # Assistant message in subagent with reasoning only
    asst_data_sub = json.dumps({
        "time": {"created": now - day},
        "content": [
            {"type": "reasoning", "text": "Subagent thinking"},
        ],
        "tokens": {"input": 50, "output": 20, "reasoning": 50},
    })
    conn.execute(
        "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("msg_v2_3", "ses_v2_sub", "assistant", 1, now - day, now - day, asst_data_sub),
    )

    # Event sequence & events
    conn.execute("INSERT INTO event_sequence VALUES (?, ?, ?)", ("ses_v2_root", 10, None))
    conn.execute("INSERT INTO event_sequence VALUES (?, ?, ?)", ("ses_v2_sub", 5, None))
    conn.execute("INSERT INTO event VALUES (?, ?, ?, ?, ?, ?)", ("evt_1", "ses_v2_sub", 1, now - day, "test", "{}"))

    # Assistant message with non-array content (e.g. error/plain string)
    conn.execute(
        "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "msg_v2_4",
            "ses_v2_root",
            "assistant",
            3,
            now - 2 * day,
            now - 2 * day,
            json.dumps({"content": "string error"}),
        ),
    )

    conn.commit()
    return conn


def test_detect_version(tmp_path: Path) -> None:
    import pytest

    db1 = tmp_path / "v1.db"
    conn1 = create_v1_db(db1)
    assert db.detect_version(conn1) == 1
    conn1.close()

    db2 = tmp_path / "v2.db"
    conn2 = create_v2_db(db2)
    assert db.detect_version(conn2) == 2
    conn2.close()

    db_empty = tmp_path / "empty.db"
    conn_empty = sqlite3.connect(str(db_empty))
    with pytest.raises(RuntimeError, match="neither 'session_v2' nor 'session' table found"):
        db.detect_version(conn_empty)
    conn_empty.close()


def test_session_count_v1_and_v2(tmp_path: Path) -> None:
    db1 = tmp_path / "v1.db"
    conn1 = create_v1_db(db1)
    root, sub = db.get_session_count(conn1)
    assert (root, sub) == (1, 1)
    conn1.close()

    db2 = tmp_path / "v2.db"
    conn2 = create_v2_db(db2)
    root, sub = db.get_session_count(conn2)
    assert (root, sub) == (1, 1)
    conn2.close()


def test_part_type_stats_v1_and_v2(tmp_path: Path) -> None:
    db1 = tmp_path / "v1.db"
    conn1 = create_v1_db(db1)
    stats1 = {s.type_name: s.count for s in db.get_part_type_stats(conn1)}
    assert stats1["text"] == 1
    assert stats1["reasoning"] == 2
    assert stats1["tool"] == 1
    conn1.close()

    db2 = tmp_path / "v2.db"
    conn2 = create_v2_db(db2)
    stats2 = {s.type_name: s.count for s in db.get_part_type_stats(conn2)}
    assert stats2["text"] == 1  # user message counted as text
    assert stats2["reasoning"] == 2
    assert stats2["tool"] == 1
    assert stats2["assistant"] == 1  # non-array content message counted under its type safely
    conn2.close()


def test_get_sessions_v1_and_v2(tmp_path: Path) -> None:
    db1 = tmp_path / "v1.db"
    conn1 = create_v1_db(db1)
    sessions1 = db.get_sessions(conn1, sort_by="size")
    assert len(sessions1) == 2
    assert sessions1[0].id == "ses_v1_root"
    assert sessions1[0].message_count == 1
    assert sessions1[0].size_bytes > 0
    assert not sessions1[0].is_subagent
    assert sessions1[1].is_subagent
    conn1.close()

    db2 = tmp_path / "v2.db"
    conn2 = create_v2_db(db2)
    sessions2 = db.get_sessions(conn2, sort_by="size")
    assert len(sessions2) == 2
    assert sessions2[0].id == "ses_v2_root"
    assert sessions2[0].message_count == 3
    assert sessions2[0].size_bytes > 0
    assert not sessions2[0].is_subagent
    assert sessions2[1].is_subagent
    conn2.close()


def test_part_type_stats_by_session_type(tmp_path: Path) -> None:
    for is_v2, creator, _root_id in [(False, create_v1_db, "ses_v1_root"), (True, create_v2_db, "ses_v2_root")]:
        db_path = tmp_path / f"test_{is_v2}.db"
        conn = creator(db_path)
        root_stats, sub_stats = db.get_part_type_stats_by_session_type(conn)
        root_types = {s.type_name for s in root_stats}
        sub_types = {s.type_name for s in sub_stats}
        assert "tool" in root_types
        assert "reasoning" in root_types
        assert "reasoning" in sub_types
        conn.close()


def test_growth_rate(tmp_path: Path) -> None:
    db1 = tmp_path / "v1.db"
    conn1 = create_v1_db(db1)
    rate1 = db.get_growth_rate(conn1)
    assert rate1 is not None and rate1 > 0
    conn1.close()

    db2 = tmp_path / "v2.db"
    conn2 = create_v2_db(db2)
    rate2 = db.get_growth_rate(conn2)
    assert rate2 is not None and rate2 > 0
    conn2.close()


def test_get_session_ids_for_purge(tmp_path: Path) -> None:
    now_ms = int(time.time() * 1000)

    for is_v2, creator, root_id, sub_id in [
        (False, create_v1_db, "ses_v1_root", "ses_v1_sub"),
        (True, create_v2_db, "ses_v2_root", "ses_v2_sub"),
    ]:
        db_path = tmp_path / f"purge_{is_v2}.db"
        conn = creator(db_path)

        # subagents only
        sub_ids = db.get_session_ids_for_purge(conn, subagents_only=True)
        assert sub_ids == [sub_id]

        # keep latest 1
        keep_ids = db.get_session_ids_for_purge(conn, keep_latest=1)
        assert keep_ids == [root_id]  # root is older, sub is newer

        # older than 1.5 days
        older_ids = db.get_session_ids_for_purge(conn, older_than_ms=int(1.5 * 86400 * 1000), now_ms=now_ms)
        assert older_ids == [root_id]

        conn.close()


def test_strip_reasoning_v1(tmp_path: Path) -> None:
    db_path = tmp_path / "strip_v1.db"
    conn = create_v1_db(db_path)

    summary = db.get_reasoning_summary(conn, session_ids=None)
    assert summary["part_count"] == 2
    assert summary["total_bytes"] > 0

    deleted = db.strip_reasoning(conn, session_ids=None)
    assert deleted == 2

    summary_after = db.get_reasoning_summary(conn, session_ids=None)
    assert summary_after["part_count"] == 0

    # Ensure other parts remain
    stats = {s.type_name: s.count for s in db.get_part_type_stats(conn)}
    assert "reasoning" not in stats
    assert stats["text"] == 1
    assert stats["tool"] == 1
    conn.close()


def test_strip_reasoning_v2(tmp_path: Path) -> None:
    db_path = tmp_path / "strip_v2.db"
    conn = create_v2_db(db_path)

    summary = db.get_reasoning_summary(conn, session_ids=None)
    assert summary["part_count"] == 2
    assert summary["total_bytes"] > 0

    # Strip for root session only
    deleted = db.strip_reasoning(conn, session_ids=["ses_v2_root"])
    assert deleted == 1

    summary_root = db.get_reasoning_summary(conn, session_ids=["ses_v2_root"])
    assert summary_root["part_count"] == 0

    # Subagent should still have its reasoning
    summary_sub = db.get_reasoning_summary(conn, session_ids=["ses_v2_sub"])
    assert summary_sub["part_count"] == 1

    # Verify root message JSON preserved tool content
    msg = conn.execute("SELECT data FROM session_message WHERE id = 'msg_v2_2'").fetchone()
    data = json.loads(msg["data"])
    assert len(data["content"]) == 1
    assert data["content"][0]["type"] == "tool"
    assert data["tokens"]["reasoning"] == 0

    # Verify session_v2 tokens_reasoning zeroed for root, but subagent unchanged
    sess_root = conn.execute("SELECT tokens_reasoning FROM session_v2 WHERE id = 'ses_v2_root'").fetchone()
    assert sess_root["tokens_reasoning"] == 0
    sess_sub = conn.execute("SELECT tokens_reasoning FROM session_v2 WHERE id = 'ses_v2_sub'").fetchone()
    assert sess_sub["tokens_reasoning"] == 50

    # Strip remaining
    deleted_sub = db.strip_reasoning(conn, session_ids=None)
    assert deleted_sub == 1
    assert db.get_reasoning_summary(conn, session_ids=None)["part_count"] == 0

    conn.close()


def test_strip_whole_reasoning_message_v2(tmp_path: Path) -> None:
    db_path = tmp_path / "strip_whole.db"
    conn = create_v2_db(db_path)
    now = int(time.time() * 1000)

    # Insert a whole message whose type is reasoning and content is plain string
    conn.execute(
        "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("msg_v2_whole", "ses_v2_root", "reasoning", 4, now, now, json.dumps({"content": "standalone reasoning text"})),
    )
    conn.commit()

    summary = db.get_reasoning_summary(conn, session_ids=["ses_v2_root"])
    # 1 from array + 1 from whole message
    assert summary["part_count"] == 2

    deleted = db.strip_reasoning(conn, session_ids=["ses_v2_root"])
    assert deleted == 2

    # Verify msg_v2_whole was deleted completely
    row = conn.execute("SELECT id FROM session_message WHERE id = 'msg_v2_whole'").fetchone()
    assert row is None

    conn.close()


def test_purge_summary_v1_and_v2(tmp_path: Path) -> None:
    db1 = tmp_path / "summary_v1.db"
    conn1 = create_v1_db(db1)
    summary1 = db.get_purge_summary(conn1, ["ses_v1_root"])
    session1 = db.get_sessions(conn1, sort_by="size")[0]
    assert summary1["session_count"] == 1
    assert summary1["message_count"] == 1
    assert summary1["part_count"] == 3
    assert summary1["total_bytes"] == session1.size_bytes
    conn1.close()

    db2 = tmp_path / "summary_v2.db"
    conn2 = create_v2_db(db2)
    summary2 = db.get_purge_summary(conn2, ["ses_v2_root"])
    session2 = db.get_sessions(conn2, sort_by="size")[0]
    assert summary2["session_count"] == 1
    assert summary2["message_count"] == 3
    assert summary2["part_count"] == 4  # user text + reasoning + tool + assistant string error
    assert summary2["total_bytes"] == session2.size_bytes  # exact consistency between sessions and purge preview!
    conn2.close()


def test_purge_sessions_v1_and_v2(tmp_path: Path) -> None:
    db1 = tmp_path / "purge_v1.db"
    conn1 = create_v1_db(db1)
    db.purge_sessions(conn1, ["ses_v1_sub"])
    assert db.get_session_count(conn1) == (1, 0)
    assert conn1.execute("SELECT COUNT(*) FROM message WHERE session_id = 'ses_v1_sub'").fetchone()[0] == 0
    assert conn1.execute("SELECT COUNT(*) FROM part WHERE session_id = 'ses_v1_sub'").fetchone()[0] == 0
    conn1.close()

    db2 = tmp_path / "purge_v2.db"
    conn2 = create_v2_db(db2)
    db.purge_sessions(conn2, ["ses_v2_sub"])
    assert db.get_session_count(conn2) == (1, 0)
    assert conn2.execute("SELECT COUNT(*) FROM session_message WHERE session_id = 'ses_v2_sub'").fetchone()[0] == 0
    assert conn2.execute("SELECT COUNT(*) FROM event WHERE aggregate_id = 'ses_v2_sub'").fetchone()[0] == 0
    assert conn2.execute("SELECT COUNT(*) FROM event_sequence WHERE aggregate_id = 'ses_v2_sub'").fetchone()[0] == 0
    conn2.close()


def test_cli_status_and_analyze(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    # Test v1
    db1 = tmp_path / "v1.db"
    create_v1_db(db1).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db1))

    res = runner.invoke(cli, ["status"])
    assert res.exit_code == 0
    assert "OpenCode v1" in res.output
    assert "V1 Root Session" not in res.output  # status doesn't print titles

    res = runner.invoke(cli, ["sessions"])
    assert res.exit_code == 0
    assert "V1 Root Session" in res.output

    res = runner.invoke(cli, ["analyze"])
    assert res.exit_code == 0
    assert "Top 10 Sessions by Size" in res.output

    # Test v2
    db2 = tmp_path / "v2.db"
    create_v2_db(db2).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db2))

    res = runner.invoke(cli, ["status"])
    assert res.exit_code == 0
    assert "OpenCode v2" in res.output

    res = runner.invoke(cli, ["sessions"])
    assert res.exit_code == 0
    assert "V2 Root Session" in res.output

    res = runner.invoke(cli, ["analyze"])
    assert res.exit_code == 0
    assert "V2 Root Session" in res.output


def test_cli_purge_v2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    db2 = tmp_path / "v2.db"
    create_v2_db(db2).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db2))

    # Dry run
    res = runner.invoke(cli, ["purge", "--strip-reasoning", "--dry-run"])
    assert res.exit_code == 0
    assert "Reasoning parts to strip" in res.output

    # Force strip reasoning
    res = runner.invoke(cli, ["purge", "--strip-reasoning", "--force"])
    assert res.exit_code == 0
    assert "Deleted 2 reasoning parts" in res.output

    # Force purge subagents
    res = runner.invoke(cli, ["purge", "--subagents", "--force"])
    assert res.exit_code == 0
    assert "Deleted 1 sessions" in res.output


def test_cross_platform_compatibility(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import stat
    import subprocess
    import sys

    # 1. Test connect with Path.as_uri() in readonly and readwrite mode
    db_file = tmp_path / "conn_test.db"
    create_v1_db(db_file).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))

    conn_ro = db.connect(readonly=True)
    assert conn_ro.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 2
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn_ro.execute("DELETE FROM session")
    conn_ro.close()

    conn_rw = db.connect(readonly=False)
    conn_rw.execute("DELETE FROM session WHERE id = 'ses_v1_sub'")
    conn_rw.commit()
    assert conn_rw.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 1
    conn_rw.close()

    # 2. Test check_opencode_running on win32
    monkeypatch.delenv("OCGC_SKIP_RUNNING_CHECK", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")

    def mock_run_win_running(cmd: object, **kwargs: object) -> object:
        class Dummy:
            stdout = '"opencode.exe","1234","Console","1","50,000 K"'
            returncode = 0

        return Dummy()

    monkeypatch.setattr(subprocess, "run", mock_run_win_running)
    assert db.check_opencode_running() is True

    def mock_run_win_not_running(cmd: object, **kwargs: object) -> object:
        class Dummy:
            stdout = "INFO: No tasks are running which match the specified criteria."
            returncode = 0

        return Dummy()

    monkeypatch.setattr(subprocess, "run", mock_run_win_not_running)
    assert db.check_opencode_running() is False

    # 3. Test purge_snapshots with read-only files (e.g. Windows Git pack files)
    snap_base = tmp_path / "opencode_storage"
    monkeypatch.setattr(db, "get_storage_dir", lambda: snap_base)
    project_snap = snap_base / "snapshot" / "proj_abc"
    project_snap.mkdir(parents=True)
    ro_file = project_snap / "pack-123.pack"
    ro_file.write_bytes(b"git pack content")
    os.chmod(ro_file, stat.S_IREAD)

    res = db.purge_snapshots("proj_abc")
    assert res.files_deleted == 1
    assert not project_snap.exists()

    # 4. Test Windows directory extraction in print_sessions
    from ocgc.db import SessionRow
    from ocgc.display import print_sessions

    win_session = SessionRow(
        id="ses_win",
        parent_id=None,
        directory="C:\\Users\\alice\\Projects\\my-web-app",
        title="Windows Session",
        time_created=int(time.time() * 1000),
        time_updated=int(time.time() * 1000),
        size_bytes=1024,
        message_count=5,
    )
    print_sessions([win_session])

    # 5. Test get_db_path resolution with OPENCODE_DATA, LOCALAPPDATA
    monkeypatch.delenv("OCGC_DB_PATH", raising=False)
    custom_dir = tmp_path / "custom_data"
    monkeypatch.setenv("OPENCODE_DATA", str(custom_dir))
    assert db.get_db_path() == custom_dir / "opencode.db"
    monkeypatch.delenv("OPENCODE_DATA")

    # Windows LOCALAPPDATA fallback
    monkeypatch.setattr(sys, "platform", "win32")
    win_appdata = tmp_path / "AppData" / "Local"
    win_db = win_appdata / "opencode" / "opencode.db"
    win_db.parent.mkdir(parents=True)
    win_db.touch()
    monkeypatch.setenv("LOCALAPPDATA", str(win_appdata))
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", tmp_path / "nonexistent" / "opencode.db")
    assert db.get_db_path() == win_db

    # 6. Windows default path when not existing points to LOCALAPPDATA, not ~/.local
    monkeypatch.delenv("OCGC_DB_PATH", raising=False)
    monkeypatch.delenv("OPENCODE_DATA", raising=False)
    nonexistent_appdata = tmp_path / "NonexistentAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(nonexistent_appdata))
    assert db.get_db_path() == nonexistent_appdata / "opencode" / "opencode.db"

    # 7. Test _format_dir_name handles various roots and windows paths
    from ocgc.display import _format_dir_name

    assert _format_dir_name("") == ""
    assert _format_dir_name(None) == ""
    assert _format_dir_name("/") == "/"
    assert _format_dir_name("C:\\") == "C:"
    assert _format_dir_name("C:\\Users\\alice\\my-project") == "my-project"
    assert _format_dir_name("/home/alice/my-project/") == "my-project"


def test_install_skill_and_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from click.testing import CliRunner

    from ocgc.skill import get_skill_content, install_skill

    # Test programmatic install to custom directory
    dest = tmp_path / "custom_skills"
    installed_paths = install_skill(dest=dest)
    assert len(installed_paths) == 1
    installed_path = installed_paths[0]
    assert installed_path.exists()
    assert installed_path.name == "SKILL.md"
    assert installed_path.parent.name == "ocgc"
    content = get_skill_content()
    assert installed_path.read_text(encoding="utf-8") == content
    assert "name: ocgc" in content
    assert "description:" in content

    # Test CLI install-skill command with custom dest (both directory and directory ending in ocgc)
    runner = CliRunner()
    cli_dest = tmp_path / "cli_skills"
    res = runner.invoke(cli, ["install-skill", "--dest", str(cli_dest)])
    assert res.exit_code == 0
    assert "Successfully installed OpenCode skill" in res.output
    assert (cli_dest / "ocgc" / "SKILL.md").exists()

    cli_dest_ocgc = tmp_path / "named_skills" / "ocgc"
    res_ocgc = runner.invoke(cli, ["install-skill", "--dest", str(cli_dest_ocgc)])
    assert res_ocgc.exit_code == 0
    assert (cli_dest_ocgc / "SKILL.md").exists()
    assert not (cli_dest_ocgc / "ocgc").exists()

    # Test CLI install-skill mutual exclusion of --dest and --workspace
    res_conflict = runner.invoke(cli, ["install-skill", "--dest", str(cli_dest), "--workspace"])
    assert res_conflict.exit_code != 0
    assert "cannot be used together" in res_conflict.output

    # Test CLI install-skill with tilde in --dest
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    res_tilde = runner.invoke(cli, ["install-skill", "--dest", "~/tilde_skills"])
    assert res_tilde.exit_code == 0
    assert (tmp_path / "home" / "tilde_skills" / "ocgc" / "SKILL.md").exists()

    # Test CLI install-skill default global to mock home
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "fake_home")
    res_global = runner.invoke(cli, ["install-skill"])
    assert res_global.exit_code == 0
    assert (tmp_path / "fake_home" / ".agents" / "skills" / "ocgc" / "SKILL.md").exists()

    # Test CLI install-skill with --workspace
    monkeypatch.chdir(tmp_path)
    res_ws = runner.invoke(cli, ["install-skill", "--workspace"])
    assert res_ws.exit_code == 0
    assert (tmp_path / ".opencode" / "skills" / "ocgc" / "SKILL.md").exists()


def test_clean_tool_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage_base = tmp_path / "opencode_storage"
    monkeypatch.setattr(db, "get_storage_dir", lambda: storage_base)

    tool_dir = storage_base / "tool-output"
    sub_dir = tool_dir / "subdir"
    sub_dir.mkdir(parents=True)

    now = time.time()
    day_s = 86400

    f_old1 = tool_dir / "out_old1.log"
    f_old1.write_text("old output 1")
    os.utime(f_old1, (now - 10 * day_s, now - 10 * day_s))

    f_old2 = sub_dir / "out_old2.log"
    f_old2.write_text("old output 2 in subdir")
    os.utime(f_old2, (now - 8 * day_s, now - 8 * day_s))

    f_new = tool_dir / "out_new.log"
    f_new.write_text("recent output")
    os.utime(f_new, (now - 1 * day_s, now - 1 * day_s))

    # Check filesystem stats
    fs = db.get_filesystem_stats()
    assert fs.tool_output_count == 3
    assert fs.tool_output_size == len("old output 1") + len("old output 2 in subdir") + len("recent output")

    # Get all tool outputs
    all_files = db.get_tool_output_files()
    assert len(all_files) == 3

    # Filter older than 5 days
    old_files = db.get_tool_output_files(older_than_ms=5 * 86400 * 1000)
    assert len(old_files) == 2
    assert {f.path.name for f in old_files} == {"out_old1.log", "out_old2.log"}

    # Purge filtered tool outputs
    res = db.purge_tool_outputs(old_files)
    assert res.files_deleted == 2
    assert not f_old1.exists()
    assert not f_old2.exists()
    assert not sub_dir.exists()  # empty subdir should be cleaned up
    assert f_new.exists()

    # Remaining files
    rem_files = db.get_tool_output_files()
    assert len(rem_files) == 1
    assert rem_files[0].path == f_new

    # Purge remaining
    res2 = db.purge_tool_outputs(rem_files)
    assert res2.files_deleted == 1
    assert not f_new.exists()

    # Test TOCTOU: file modified after scan is preserved
    f_concurrent = tool_dir / "concurrent.log"
    f_concurrent.write_text("initial")
    os.utime(f_concurrent, (now - 10 * day_s, now - 10 * day_s))
    scan_files = db.get_tool_output_files()
    assert len(scan_files) == 1
    # Simulate concurrent write by opencode after scan
    time.sleep(0.01)
    f_concurrent.write_text("new content written by tool")
    purge_res = db.purge_tool_outputs(scan_files)
    assert purge_res.files_deleted == 0
    assert f_concurrent.exists()


def test_cli_purge_tool_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    storage_base = tmp_path / "opencode_storage"
    storage_base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(db, "get_storage_dir", lambda: storage_base)

    db_path = storage_base / "opencode.db"
    create_v2_db(db_path).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db_path))

    tool_dir = storage_base / "tool-output"
    tool_dir.mkdir(parents=True)

    now = time.time()
    day_s = 86400

    f1 = tool_dir / "tool_1"
    f1.write_bytes(b"x" * 1024)
    os.utime(f1, (now - 10 * day_s, now - 10 * day_s))

    f2 = tool_dir / "tool_2"
    f2.write_bytes(b"y" * 2048)
    os.utime(f2, (now - 1 * day_s, now - 1 * day_s))

    # Dry run
    res = runner.invoke(cli, ["purge", "--clean-tool-output", "--dry-run"])
    assert res.exit_code == 0
    assert "Tool output files to delete" in res.output
    assert "2" in res.output
    assert f1.exists() and f2.exists()

    # Purge with older-than 5d (should only delete f1)
    res = runner.invoke(cli, ["purge", "--clean-tool-output", "--older-than", "5d", "--force"])
    assert res.exit_code == 0
    assert "Deleted 1 tool output file(s)" in res.output
    assert not f1.exists()
    assert f2.exists()

    # Purge remaining with force
    res = runner.invoke(cli, ["purge", "--clean-tool-output", "--force"])
    assert res.exit_code == 0
    assert "Deleted 1 tool output file(s)" in res.output
    assert not f2.exists()

    # When no tool output files exist
    res = runner.invoke(cli, ["purge", "--clean-tool-output", "--force"])
    assert res.exit_code == 0
    assert "No tool output files found" in res.output


def test_filter_clause_building() -> None:
    # Directory: absolute path
    conds, params = db._build_filter_clause(directory="/Users/alice/my-repo", version=2)
    assert len(conds) == 1
    assert "COLLATE NOCASE" in conds[0]
    assert params == ["/Users/alice/my-repo", "/Users/alice/my-repo/%"]

    # Directory: relative current dir '.'
    conds, params = db._build_filter_clause(directory=".", version=2)
    assert len(conds) == 1
    assert os.path.abspath(".").replace("\\", "/").rstrip("/") == params[0]

    # Directory: wildcard
    conds, params = db._build_filter_clause(directory="*my-repo*", version=2)
    assert len(conds) == 1
    assert "LIKE" in conds[0]
    assert "%my-repo%" in params

    # Directory: bare name
    conds, params = db._build_filter_clause(directory="my-repo", version=2)
    assert len(conds) == 1
    assert params == ["my-repo", "%/my-repo", "%/my-repo/%"]

    # Project: v2 exact
    conds, params = db._build_filter_clause(project="proj_xyz", version=2)
    assert len(conds) == 1
    assert "s.project_id = ?" in conds[0]
    assert "proj_xyz" in params

    # Project: v2 wildcard
    conds, params = db._build_filter_clause(project="*xyz*", version=2)
    assert len(conds) == 1
    assert "s.project_id LIKE" in conds[0]
    assert "%xyz%" in params

    # Project: v1 fallback to directory
    conds, params = db._build_filter_clause(project="my-repo", version=1)
    assert len(conds) == 1
    assert "project_id" not in conds[0]
    assert params == ["my-repo", "%/my-repo", "%/my-repo/%"]


def test_get_sessions_filtered(tmp_path: Path) -> None:
    # Test v1 filtering
    db1 = tmp_path / "v1_filter.db"
    conn1 = create_v1_db(db1)

    # Exact directory match
    s_exact = db.get_sessions(conn1, directory="/path/to/project")
    assert len(s_exact) == 2

    # Bare directory name
    s_bare = db.get_sessions(conn1, directory="project")
    assert len(s_bare) == 2

    # Wildcard directory
    s_wild = db.get_sessions(conn1, directory="*proj*")
    assert len(s_wild) == 2

    # Non-matching directory
    s_none = db.get_sessions(conn1, directory="/path/to/other")
    assert len(s_none) == 0

    # Project name matching directory
    s_proj = db.get_sessions(conn1, project="project")
    assert len(s_proj) == 2

    conn1.close()

    # Test v2 filtering
    db2 = tmp_path / "v2_filter.db"
    conn2 = create_v2_db(db2)

    # Filter by project_id
    s2_proj = db.get_sessions(conn2, project="proj_1")
    assert len(s2_proj) == 2
    assert s2_proj[0].project_id == "proj_1"

    # Filter by project wildcard
    s2_wild = db.get_sessions(conn2, project="*proj*")
    assert len(s2_wild) == 2

    # Filter by directory
    s2_dir = db.get_sessions(conn2, directory="/path/to/project")
    assert len(s2_dir) == 2

    # Non-matching project
    s2_none = db.get_sessions(conn2, project="proj_nonexistent")
    assert len(s2_none) == 0

    conn2.close()


def test_purge_session_ids_filtered(tmp_path: Path) -> None:
    db2 = tmp_path / "v2_purge_filter.db"
    conn2 = create_v2_db(db2)
    now_ms = int(time.time() * 1000)

    # Match by project_id
    ids = db.get_session_ids_for_purge(conn2, project="proj_1")
    assert sorted(ids) == ["ses_v2_root", "ses_v2_sub"]

    # Match by directory
    ids_dir = db.get_session_ids_for_purge(conn2, directory="/path/to/project")
    assert sorted(ids_dir) == ["ses_v2_root", "ses_v2_sub"]

    # Match by directory + subagents_only
    ids_sub = db.get_session_ids_for_purge(conn2, directory="/path/to/project", subagents_only=True)
    assert ids_sub == ["ses_v2_sub"]

    # Match by directory + keep_latest 1
    ids_keep = db.get_session_ids_for_purge(conn2, directory="/path/to/project", keep_latest=1)
    assert ids_keep == ["ses_v2_root"]

    # Non-matching directory
    ids_empty = db.get_session_ids_for_purge(conn2, directory="/nonexistent/path")
    assert ids_empty == []

    # Combined with older_than_ms
    ids_older = db.get_session_ids_for_purge(
        conn2,
        project="proj_1",
        older_than_ms=int(1.5 * 86400 * 1000),
        now_ms=now_ms,
    )
    assert ids_older == ["ses_v2_root"]

    conn2.close()


def test_snapshot_projects_and_purge_filtered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage_base = tmp_path / "opencode_storage"
    monkeypatch.setattr(db, "get_storage_dir", lambda: storage_base)

    snap_dir = storage_base / "snapshot"
    snap_dir.mkdir(parents=True)

    snap_a = snap_dir / "proj_alpha"
    snap_a.mkdir()
    (snap_a / "pack.dat").write_text("alpha data")

    snap_b = snap_dir / "proj_beta"
    snap_b.mkdir()
    (snap_b / "pack.dat").write_text("beta data")

    snap_legacy = snap_dir / "legacy-repo"
    snap_legacy.mkdir()
    (snap_legacy / "pack.dat").write_text("legacy data")

    # All snapshot projects
    all_projects = db.get_snapshot_projects()
    assert len(all_projects) == 3
    assert {name for name, _ in all_projects} == {"proj_alpha", "proj_beta", "legacy-repo"}

    # Filter by exact project name
    alpha_projects = db.get_snapshot_projects(project="proj_alpha")
    assert len(alpha_projects) == 1
    assert alpha_projects[0][0] == "proj_alpha"

    # Filter by project wildcard
    proj_wild = db.get_snapshot_projects(project="*proj*")
    assert len(proj_wild) == 2
    assert {name for name, _ in proj_wild} == {"proj_alpha", "proj_beta"}

    # Filter by directory path (directory basename matches legacy-repo)
    legacy_projects = db.get_snapshot_projects(directory="~/Projects/legacy-repo")
    assert len(legacy_projects) == 1
    assert legacy_projects[0][0] == "legacy-repo"

    # Filter by non-existent project
    none_projects = db.get_snapshot_projects(project="nonexistent")
    assert len(none_projects) == 0

    # Purge filtered snapshot by project
    res_alpha = db.purge_snapshots(project="proj_alpha")
    assert res_alpha.files_deleted == 1
    assert not snap_a.exists()
    assert snap_b.exists()
    assert snap_legacy.exists()

    # Purge filtered snapshot by directory
    res_legacy = db.purge_snapshots(directory="/some/path/legacy-repo")
    assert res_legacy.files_deleted == 1
    assert not snap_legacy.exists()
    assert snap_b.exists()


def test_cli_sessions_and_purge_scoped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    storage_base = tmp_path / "opencode_storage"
    storage_base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(db, "get_storage_dir", lambda: storage_base)

    db2 = storage_base / "opencode.db"
    create_v2_db(db2).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db2))

    # 1. sessions with matching --project
    res = runner.invoke(cli, ["sessions", "--project", "proj_1"])
    assert res.exit_code == 0
    assert "V2 Root Session" in res.output

    # 2. sessions with matching -p
    res = runner.invoke(cli, ["sessions", "-p", "proj_1"])
    assert res.exit_code == 0
    assert "V2 Root Session" in res.output

    # 3. sessions with non-matching --project
    res = runner.invoke(cli, ["sessions", "--project", "nonexistent"])
    assert res.exit_code == 0
    assert "No sessions found matching the given criteria." in res.output

    # 4. sessions with --directory
    res = runner.invoke(cli, ["sessions", "--directory", "/path/to/project"])
    assert res.exit_code == 0
    assert "V2 Root Session" in res.output

    # 5. sessions with -d short flag
    res = runner.invoke(cli, ["sessions", "-d", "project"])
    assert res.exit_code == 0
    assert "V2 Root Session" in res.output

    # 6. purge dry-run with --project
    res = runner.invoke(cli, ["purge", "--project", "proj_1", "--dry-run"])
    assert res.exit_code == 0
    assert "Dry Run — Nothing will be deleted" in res.output
    assert "Project filter" in res.output
    assert "proj_1" in res.output

    # 7. purge dry-run with --directory
    res = runner.invoke(cli, ["purge", "--directory", "/path/to/project", "--dry-run"])
    assert res.exit_code == 0
    assert "Directory filter" in res.output
    assert "/path/to/project" in res.output

    # 8. snapshot cleanup with --clean-snapshots and --project
    snap_dir = storage_base / "snapshot" / "proj_1"
    snap_dir.mkdir(parents=True, exist_ok=True)
    (snap_dir / "test.pack").write_text("snapshot content")

    res = runner.invoke(cli, ["purge", "--clean-snapshots", "--project", "proj_1", "--dry-run"])
    assert res.exit_code == 0
    assert "Dry Run — Snapshots to delete" in res.output
    assert "Project filter" in res.output
    assert snap_dir.exists()

    res = runner.invoke(cli, ["purge", "--clean-snapshots", "--project", "proj_1", "--force"])
    assert res.exit_code == 0
    assert "Deleted 1 snapshot dir(s)" in res.output
    assert not snap_dir.exists()

    # 9. purge sessions with --project and --force
    res = runner.invoke(cli, ["purge", "--project", "proj_1", "--force"])
    assert res.exit_code == 0
    assert "Deleted 2 sessions" in res.output

    # Verify sessions are gone
    res = runner.invoke(cli, ["sessions"])
    assert res.exit_code == 0
    assert "No sessions found" in res.output


def test_like_escaping_special_characters(tmp_path: Path) -> None:
    db_file = tmp_path / "like_escape.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE session (
            id TEXT PRIMARY KEY,
            parent_id TEXT,
            directory TEXT NOT NULL,
            title TEXT,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL
        );
        CREATE TABLE message (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            time_created INTEGER,
            time_updated INTEGER,
            data TEXT
        );
        CREATE TABLE part (
            id TEXT PRIMARY KEY,
            message_id TEXT,
            session_id TEXT NOT NULL,
            time_created INTEGER,
            time_updated INTEGER,
            data TEXT
        );
    """)
    now = int(time.time() * 1000)
    conn.execute("INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)", ("s1", None, "/path/to/my_app", "App", now, now))
    conn.execute("INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)", ("s2", None, "/path/to/myXapp", "Other", now, now))
    conn.commit()

    # Exact directory with underscore
    sessions = db.get_sessions(conn, directory="my_app")
    assert len(sessions) == 1
    assert sessions[0].id == "s1"
    conn.close()


def test_purge_blank_project_or_directory_fails_safely(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")
    db2 = tmp_path / "v2.db"
    create_v2_db(db2).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db2))

    res = runner.invoke(cli, ["purge", "--project", "   "])
    assert res.exit_code != 0
    assert "At least one purge flag is required" in res.output

    res2 = runner.invoke(cli, ["purge", "--directory", ""])
    assert res2.exit_code != 0
    assert "At least one purge flag is required" in res2.output


def test_clean_orphans_with_project_flag_does_not_purge_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    storage_base = tmp_path / "opencode_storage"
    storage_base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(db, "get_storage_dir", lambda: storage_base)

    db2 = storage_base / "opencode.db"
    create_v2_db(db2).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db2))

    # Orphan file
    diff_dir = storage_base / "storage" / "session_diff"
    diff_dir.mkdir(parents=True, exist_ok=True)
    (diff_dir / "orphan_123.json").write_text("{}")

    # Clean orphans with project filter passed
    res = runner.invoke(cli, ["purge", "--clean-orphans", "--project", "proj_1", "--force"])
    assert res.exit_code == 0
    assert "Deleted 1 orphan file(s)" in res.output

    # Crucial assertion: sessions must NOT have been purged!
    conn = sqlite3.connect(str(db2))
    count = conn.execute("SELECT COUNT(*) FROM session_v2").fetchone()[0]
    conn.close()
    assert count == 2


def test_snapshot_dual_filter_intersection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage_base = tmp_path / "opencode_storage"
    monkeypatch.setattr(db, "get_storage_dir", lambda: storage_base)

    snap_dir = storage_base / "snapshot"
    snap_dir.mkdir(parents=True)

    snap_a = snap_dir / "proj_a"
    snap_a.mkdir()
    (snap_a / "pack.dat").write_text("a")

    snap_b = snap_dir / "proj_b"
    snap_b.mkdir()
    (snap_b / "pack.dat").write_text("b")

    # Project A and Directory proj_b (mutually exclusive) -> intersection is empty
    res = db.get_snapshot_projects(project="proj_a", directory="/path/to/proj_b")
    assert len(res) == 0

    # Project A and Directory proj_a -> matches proj_a
    res2 = db.get_snapshot_projects(project="proj_a", directory="/path/to/proj_a")
    assert len(res2) == 1
    assert res2[0][0] == "proj_a"


def test_checkpoint_db_truncate(tmp_path: Path) -> None:
    db_path = tmp_path / "wal_test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, content TEXT)")
    conn.commit()

    # Keep a background reader open to prevent automatic checkpoint on close
    bg_reader = sqlite3.connect(str(db_path))
    bg_reader.execute("PRAGMA journal_mode=WAL")

    # Generate WAL frames
    for i in range(50):
        conn.execute("INSERT INTO t VALUES (?, ?)", (i, "payload data " * 100))
    conn.commit()
    conn.close()

    wal_path = Path(str(db_path) + "-wal")
    assert wal_path.exists()
    assert wal_path.stat().st_size > 0
    wal_size_before = wal_path.stat().st_size

    result = db.checkpoint_db(mode="truncate", path=db_path)
    bg_reader.close()

    assert result.mode == "TRUNCATE"
    assert result.busy == 0
    assert result.wal_before == wal_size_before
    assert result.wal_after == 0
    assert result.wal_saved == wal_size_before
    assert result.log_frames >= 0
    assert result.checkpointed_frames >= 0


def test_checkpoint_db_modes(tmp_path: Path) -> None:
    db_path = tmp_path / "modes_test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (x TEXT)")
    conn.commit()
    conn.close()

    for mode in ["PASSIVE", "FULL", "RESTART", "TRUNCATE", "truncate", "passive"]:
        res = db.checkpoint_db(mode=mode, path=db_path)
        assert res.mode == mode.upper()
        assert res.busy == 0

    with pytest.raises(ValueError, match="Invalid checkpoint mode"):
        db.checkpoint_db(mode="invalid_mode", path=db_path)


def test_checkpoint_db_nonexistent(tmp_path: Path) -> None:
    nonexistent = tmp_path / "nonexistent.db"
    with pytest.raises(FileNotFoundError, match="not found"):
        db.checkpoint_db(path=nonexistent)


def test_checkpoint_db_busy_state(tmp_path: Path) -> None:
    db_path = tmp_path / "busy_test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, content TEXT)")
    conn.commit()

    # Background reader starts active read transaction
    reader = sqlite3.connect(str(db_path))
    reader.execute("PRAGMA journal_mode=WAL")

    # Generate WAL frames
    for i in range(50):
        conn.execute("INSERT INTO t VALUES (?, ?)", (i, "payload data " * 100))
    conn.commit()
    conn.close()

    reader.execute("BEGIN")
    reader.execute("SELECT * FROM t LIMIT 1").fetchall()

    # Checkpoint should report busy because reader holds an open transaction
    result_busy = db.checkpoint_db(mode="TRUNCATE", path=db_path)
    assert result_busy.busy == 1
    assert result_busy.wal_after > 0

    # Once reader commits, checkpoint succeeds completely
    reader.commit()
    reader.close()

    result_ok = db.checkpoint_db(mode="TRUNCATE", path=db_path)
    assert result_ok.busy == 0
    assert result_ok.wal_after == 0


def test_cli_checkpoint_and_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    db_path = tmp_path / "cli_checkpoint.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, text TEXT)")
    conn.commit()

    bg = sqlite3.connect(str(db_path))
    bg.execute("PRAGMA journal_mode=WAL")

    for i in range(50):
        conn.execute("INSERT INTO t VALUES (?, ?)", (i, "log content " * 100))
    conn.commit()
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_path))

    # 1. Default CLI checkpoint
    res = runner.invoke(cli, ["checkpoint"])
    assert res.exit_code == 0
    assert "WAL Checkpoint Complete" in res.output
    assert "TRUNCATE" in res.output
    assert "Completed" in res.output

    # 2. Modes via CLI
    res_passive = runner.invoke(cli, ["checkpoint", "--mode", "passive"])
    assert res_passive.exit_code == 0
    assert "PASSIVE" in res_passive.output

    res_invalid = runner.invoke(cli, ["checkpoint", "--mode", "invalid"])
    assert res_invalid.exit_code != 0
    assert "Invalid value for '--mode'" in res_invalid.output

    bg.close()


def test_cli_checkpoint_running_prompt_and_force(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.delenv("OCGC_SKIP_RUNNING_CHECK", raising=False)
    monkeypatch.setattr(db, "check_opencode_running", lambda: True)

    db_path = tmp_path / "running_check.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (x TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db_path))

    # User cancels at prompt
    res_cancel = runner.invoke(cli, ["checkpoint"], input="n\n")
    assert res_cancel.exit_code == 0
    assert "opencode is currently running" in res_cancel.output
    assert "WAL Checkpoint Complete" not in res_cancel.output

    # User proceeds with --force
    res_force = runner.invoke(cli, ["checkpoint", "--force"])
    assert res_force.exit_code == 0
    assert "WAL Checkpoint Complete" in res_force.output


def test_cli_checkpoint_locked_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    db_path = tmp_path / "locked.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
    conn.close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db_path))

    def mock_checkpoint_locked(*args: object, **kwargs: object) -> object:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db, "checkpoint_db", mock_checkpoint_locked)

    res = runner.invoke(cli, ["checkpoint"])
    assert res.exit_code != 0
    assert "Database is locked" in res.output


def test_vacuum_db_with_path(tmp_path: Path) -> None:
    db_path = tmp_path / "vac.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (x TEXT)")
    conn.commit()
    conn.close()

    before, after = db.vacuum_db(path=db_path)
    assert before > 0
    assert after > 0


def test_vacuum_db_nonexistent(tmp_path: Path) -> None:
    nonexistent = tmp_path / "nonexistent.db"
    with pytest.raises(FileNotFoundError, match="not found"):
        db.vacuum_db(path=nonexistent)


def test_cli_checkpoint_busy_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    db_path = tmp_path / "busy_cli.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
    conn.close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db_path))

    from ocgc.db import CheckpointResult

    fake_busy_result = CheckpointResult(
        mode="TRUNCATE",
        busy=1,
        log_frames=10,
        checkpointed_frames=10,
        wal_before=1000,
        wal_after=1000,
        db_before=4096,
        db_after=4096,
        total_before=5096,
        total_after=5096,
    )
    monkeypatch.setattr(db, "checkpoint_db", lambda *args, **kwargs: fake_busy_result)

    res = runner.invoke(cli, ["checkpoint"])
    assert res.exit_code == 1
    assert "WAL Checkpoint Incomplete" in res.output
    assert "Busy (locks held)" in res.output


def test_truncate_text_if_large() -> None:
    # 1. 文本长度 <= 1500 字符：不截断
    short_text = "a" * 1500
    res_text, orig_b, rec_b, truncated = db._truncate_text_if_large(short_text, threshold_bytes=500)
    assert not truncated
    assert res_text == short_text
    assert orig_b == 0 and rec_b == 0

    # 2. 文本 > 1500 但字节数 <= threshold_bytes：不截断
    long_text = "a" * 2000
    res_text, orig_b, rec_b, truncated = db._truncate_text_if_large(long_text, threshold_bytes=3000)
    assert not truncated
    assert res_text == long_text

    # 3. 文本超过 threshold_bytes：成功截断
    huge_text = "HEAD_" + ("x" * 5000) + "_TAIL"
    res_text, orig_b, rec_b, truncated = db._truncate_text_if_large(
        huge_text, threshold_bytes=2000, label="output", head_chars=1000, tail_chars=500
    )
    assert truncated
    assert res_text.startswith(huge_text[:1000])
    assert res_text.endswith(huge_text[-500:])
    assert "[ocgc: truncated" in res_text
    assert "of output]" in res_text
    assert orig_b == len(huge_text.encode("utf-8"))
    assert rec_b > 0
    assert len(res_text.encode("utf-8")) < orig_b


def test_strip_large_outputs_v1(tmp_path: Path) -> None:
    db_path = tmp_path / "strip_large_v1.db"
    conn = create_v1_db(db_path)
    now = int(time.time() * 1000)

    # 插入一个超过 10KB 的 tool part
    huge_tool_output = "START_LOG_" + ("A" * 10000) + "_END_LOG"
    conn.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
        (
            "part_huge_tool",
            "msg_1",
            "ses_v1_root",
            now,
            now,
            json.dumps({
                "type": "tool",
                "call": "bash",
                "state": {"status": "completed", "output": huge_tool_output},
            }),
        ),
    )

    # 插入一个超过 10KB 的 image part
    huge_image_data = "data:image/png;base64," + ("B" * 10000)
    conn.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
        (
            "part_huge_image",
            "msg_1",
            "ses_v1_root",
            now,
            now,
            json.dumps({"type": "image", "data": huge_image_data}),
        ),
    )
    conn.commit()

    # 阈值设为 5KB (5120 bytes)
    threshold = 5120

    # 1. 扫描 summary
    summary = db.get_strip_large_outputs_summary(conn, threshold_bytes=threshold)
    assert summary.session_count == 1
    assert summary.part_count == 2
    assert summary.original_bytes > 20000
    assert summary.reclaimed_bytes > 15000

    # 2. 指定非目标 session_ids
    summary_empty = db.get_strip_large_outputs_summary(
        conn, threshold_bytes=threshold, session_ids=["ses_v1_sub"]
    )
    assert summary_empty.part_count == 0

    # 3. 真实执行截断
    res = db.strip_large_outputs(conn, threshold_bytes=threshold)
    assert res.sessions_affected == 1
    assert res.parts_truncated == 2
    assert res.bytes_reclaimed > 15000

    # 4. 验证 tool output 正确被截断
    row_tool = conn.execute("SELECT data FROM part WHERE id = 'part_huge_tool'").fetchone()
    data_tool = json.loads(row_tool["data"])
    truncated_out = data_tool["state"]["output"]
    assert truncated_out.startswith(huge_tool_output[:1000])
    assert truncated_out.endswith(huge_tool_output[-500:])
    assert "[ocgc: truncated" in truncated_out

    # 5. 验证 image 正确被截断
    row_img = conn.execute("SELECT data FROM part WHERE id = 'part_huge_image'").fetchone()
    data_img = json.loads(row_img["data"])
    assert "[ocgc: truncated" in data_img["data"]
    assert "of image data]" in data_img["data"]

    # 6. 再次截断应具有幂等性
    summary_after = db.get_strip_large_outputs_summary(conn, threshold_bytes=threshold)
    assert summary_after.part_count == 0
    res_after = db.strip_large_outputs(conn, threshold_bytes=threshold)
    assert res_after.parts_truncated == 0

    conn.close()


def test_strip_large_outputs_v2(tmp_path: Path) -> None:
    db_path = tmp_path / "strip_large_v2.db"
    conn = create_v2_db(db_path)
    now = int(time.time() * 1000)

    # 在 root session 中插入带有超大 tool output、超大 image 以及超大 file 附件的消息
    huge_bash = "BASH_START_" + ("X" * 8000) + "_BASH_END"
    huge_img = "IMG_BASE64_" + ("Y" * 8000)
    huge_error = "ERR_START_" + ("Z" * 8000) + "_ERR_END"
    huge_file_url = "data:image/png;base64," + ("F" * 8000)

    msg_data = json.dumps({
        "time": {"created": now},
        "content": [
            {
                "type": "tool",
                "id": "tool_huge",
                "name": "bash",
                "state": {
                    "status": "completed",
                    "output": huge_bash,
                    "error": huge_error,
                    "content": [{"type": "text", "text": "normal"}],
                },
            },
            {
                "type": "image",
                "data": huge_img,
            },
            {
                "type": "file",
                "url": huge_file_url,
            },
        ],
    })

    conn.execute(
        "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("msg_huge_v2", "ses_v2_root", "assistant", 10, now, now, msg_data),
    )

    # 在 subagent session 中插入一个较小但超过 2K 的部件（state.content 为单个 dict 对象）
    medium_log = "SUB_START_" + ("M" * 3000) + "_SUB_END"
    sub_data = json.dumps({
        "time": {"created": now},
        "content": [
            {
                "type": "tool",
                "id": "tool_sub",
                "name": "read",
                "state": {
                    "status": "completed",
                    "content": {"type": "text", "text": medium_log},
                },
            }
        ],
    })
    conn.execute(
        "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("msg_sub_v2", "ses_v2_sub", "assistant", 2, now, now, sub_data),
    )
    conn.commit()

    # 1. 阈值 5KB (5120 bytes) -> 只有 root 会被匹配到 (huge_bash, huge_img, huge_error, huge_file_url 共 4 处)
    summary_5k = db.get_strip_large_outputs_summary(conn, threshold_bytes=5120)
    assert summary_5k.session_count == 1
    assert summary_5k.part_count == 4

    # 2. 阈值 2KB (2048 bytes) -> root 与 sub 均被匹配 (4 + 1 = 5 处)
    summary_2k = db.get_strip_large_outputs_summary(conn, threshold_bytes=2048)
    assert summary_2k.session_count == 2
    assert summary_2k.part_count == 5

    # 3. 指定 session_ids 只截断 subagent
    res_sub = db.strip_large_outputs(conn, threshold_bytes=2048, session_ids=["ses_v2_sub"])
    assert res_sub.sessions_affected == 1
    assert res_sub.parts_truncated == 1

    # 检查 sub 已被截断（单 dict content 正确被截断）
    sub_row = conn.execute("SELECT data FROM session_message WHERE id = 'msg_sub_v2'").fetchone()
    sub_parsed = json.loads(sub_row["data"])
    assert "[ocgc: truncated" in sub_parsed["content"][0]["state"]["content"]["text"]

    # 检查 root 依然未被修改
    root_row = conn.execute("SELECT data FROM session_message WHERE id = 'msg_huge_v2'").fetchone()
    assert "[ocgc: truncated" not in root_row["data"]

    # 4. 全库截断剩余内容
    res_all = db.strip_large_outputs(conn, threshold_bytes=2048)
    assert res_all.sessions_affected == 1
    assert res_all.parts_truncated == 4

    root_row_after = conn.execute("SELECT data FROM session_message WHERE id = 'msg_huge_v2'").fetchone()
    root_parsed = json.loads(root_row_after["data"])
    tool_st = root_parsed["content"][0]["state"]
    assert "[ocgc: truncated" in tool_st["output"]
    assert "[ocgc: truncated" in tool_st["error"]
    assert "[ocgc: truncated" in root_parsed["content"][1]["data"]
    assert "[ocgc: truncated" in root_parsed["content"][2]["url"]
    assert "of image data]" in root_parsed["content"][2]["url"]

    conn.close()


def test_cli_strip_large_outputs_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    db_path = tmp_path / "cli_strip_large.db"
    conn = create_v2_db(db_path)
    now = int(time.time() * 1000)

    # 插入一个超过 10KB 的 tool output
    large_str = "LOG_HEAD_" + ("W" * 10000) + "_LOG_TAIL"
    msg_data = json.dumps({
        "time": {"created": now},
        "content": [
            {
                "type": "tool",
                "id": "t1",
                "name": "bash",
                "state": {"status": "completed", "output": large_str},
            }
        ],
    })
    conn.execute(
        "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("msg_cli_1", "ses_v2_root", "assistant", 20, now, now, msg_data),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db_path))

    # 1. --strip-reasoning 与 --strip-large-outputs 互斥
    res_conflict = runner.invoke(cli, ["purge", "--strip-reasoning", "--strip-large-outputs"])
    assert res_conflict.exit_code != 0
    assert "cannot be used together" in res_conflict.output

    # 2. Dry run with threshold 5K
    res_dry = runner.invoke(cli, ["purge", "--strip-large-outputs", "--threshold", "5K", "--dry-run"])
    assert res_dry.exit_code == 0
    assert "Large outputs/media to truncate" in res_dry.output
    assert "Estimated freed" in res_dry.output

    # 验证未被修改
    conn2 = sqlite3.connect(str(db_path))
    row = conn2.execute("SELECT data FROM session_message WHERE id = 'msg_cli_1'").fetchone()
    assert "[ocgc: truncated" not in row[0]
    conn2.close()

    # 3. 真实运行带 --force
    res_force = runner.invoke(cli, ["purge", "--strip-large-outputs", "--threshold", "5K", "--force"])
    assert res_force.exit_code == 0
    assert "Truncated 1 large output/media part(s)" in res_force.output

    # 验证已成功截断
    conn3 = sqlite3.connect(str(db_path))
    row_done = conn3.execute("SELECT data FROM session_message WHERE id = 'msg_cli_1'").fetchone()
    assert "[ocgc: truncated" in row_done[0]
    conn3.close()

    # 4. 再次执行提示未找到超大部件
    res_none = runner.invoke(cli, ["purge", "--strip-large-outputs", "--threshold", "5K", "--force"])
    assert res_none.exit_code == 0
    assert "No large tool outputs or media parts found" in res_none.output

    # 5. 测试与过滤条件组合（--session 以及 --project）
    # 向 ses_v2_sub 插入超大数据
    conn4 = sqlite3.connect(str(db_path))
    sub_large = "SUB_CLI_" + ("S" * 8000) + "_END"
    conn4.execute(
        "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "msg_cli_sub",
            "ses_v2_sub",
            "assistant",
            30,
            now,
            now,
            json.dumps({"type": "tool", "state": {"output": sub_large}}),
        ),
    )
    conn4.commit()
    conn4.close()

    # 通过 --session 指定 ses_v2_sub 进行截断
    res_sid = runner.invoke(
        cli,
        ["purge", "--strip-large-outputs", "--threshold", "5K", "--session", "ses_v2_sub", "--force"],
    )
    assert res_sid.exit_code == 0
    assert "Truncated 1 large output/media part(s)" in res_sid.output

    conn5 = sqlite3.connect(str(db_path))
    row_sub = conn5.execute("SELECT data FROM session_message WHERE id = 'msg_cli_sub'").fetchone()
    assert "[ocgc: truncated" in row_sub[0]
    conn5.close()





