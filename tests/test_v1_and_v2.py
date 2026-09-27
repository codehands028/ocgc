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
