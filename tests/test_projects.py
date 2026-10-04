"""Unit and integration tests for the project-level storage dashboard (`ocgc projects`)."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from test_v1_and_v2 import create_v1_db, create_v2_db

from ocgc import db
from ocgc.cli import cli


def _write_snapshot(base: Path, name: str, size: int) -> None:
    snap = base / "snapshot" / name
    snap.mkdir(parents=True, exist_ok=True)
    (snap / "pack.pack").write_bytes(b"x" * size)


def test_project_stats_v2_with_snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)

    expected_data = sum(s.size_bytes for s in db.get_sessions(conn, sort_by="size"))
    _write_snapshot(tmp_path, "proj_1", 4096)
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    projects = db.get_project_stats(conn)
    assert len(projects) == 1
    p = projects[0]
    assert p.directory == "/path/to/project"
    assert p.project_id == "proj_1"
    assert p.session_count == 2
    assert p.data_size == expected_data
    assert p.snapshot_size == 4096
    assert p.total_size == expected_data + 4096
    conn.close()


def test_project_stats_v1_with_snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "v1.db"
    conn = create_v1_db(db_file)

    _write_snapshot(tmp_path, "project", 2048)
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    projects = db.get_project_stats(conn)
    assert len(projects) == 1
    p = projects[0]
    assert p.project_id is None
    assert p.directory == "/path/to/project"
    assert p.session_count == 2
    assert p.snapshot_size == 2048
    conn.close()


def test_project_stats_prefers_project_worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.execute("CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT NOT NULL)")
    conn.execute("INSERT INTO project VALUES (?, ?)", ("proj_1", "/canonical/ocgc-worktree"))
    conn.commit()
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    projects = db.get_project_stats(conn)
    assert len(projects) == 1
    assert projects[0].directory == "/canonical/ocgc-worktree"
    conn.close()


def test_project_stats_multi_project_sorting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    now = int(time.time() * 1000)

    # Project A: one session with a large message payload.
    conn.execute(
        "INSERT INTO session_v2 (id, project_id, slug, directory, title, version, time_created, time_updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("ses_a", "proj_a", "a", "/work/a", "A", "v2", now - 1000, now),
    )
    conn.execute(
        "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("msg_a", "ses_a", "assistant", 1, now, now, json.dumps({"content": "x" * 5000})),
    )
    # Project B: three tiny sessions.
    for i in range(3):
        conn.execute(
            "INSERT INTO session_v2 (id, project_id, slug, directory, title, version, time_created, time_updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"ses_b{i}", "proj_b", f"b{i}", "/work/b", f"B{i}", "v2", now - 1000, now - i * 10),
        )
        conn.execute(
            "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"msg_b{i}", f"ses_b{i}", "assistant", 1, now, now, json.dumps({"content": "y"})),
        )
    conn.commit()

    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    by_size = db.get_project_stats(conn, sort_by="size")
    size_order = [p.project_id for p in by_size]
    assert size_order.index("proj_a") < size_order.index("proj_b")

    by_sessions = db.get_project_stats(conn, sort_by="sessions")
    assert by_sessions[0].project_id == "proj_b"
    assert by_sessions[0].session_count == 3

    limited = db.get_project_stats(conn, sort_by="size", limit=1)
    assert len(limited) == 1
    assert limited[0].project_id == "proj_a"

    by_name = db.get_project_stats(conn, sort_by="name")
    name_order = [p.project_id for p in by_name]
    # /path/to/project (proj_1) < /work/a (proj_a) < /work/b (proj_b)
    assert name_order.index("proj_1") < name_order.index("proj_a") < name_order.index("proj_b")

    by_age = db.get_project_stats(conn, sort_by="age")
    age_order = [p.project_id for p in by_age]
    # proj_1 fixture has last_active = now - day (oldest), proj_a/proj_b = now.
    # proj_a and proj_b tie on last_active, secondary sort by directory: /work/a < /work/b.
    assert age_order.index("proj_1") < age_order.index("proj_a")
    assert age_order.index("proj_a") < age_order.index("proj_b")
    conn.close()


def test_project_stats_ambiguous_snapshot_basename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "v1.db"
    conn = create_v1_db(db_file)
    now = int(time.time() * 1000)
    # Two workspaces sharing the basename "api" -> snapshot attribution is ambiguous.
    conn.execute(
        "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
        ("ses_api_1", None, "/work/api", "API 1", now, now),
    )
    conn.execute(
        "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
        ("ses_api_2", None, "/oss/api", "API 2", now, now),
    )
    conn.commit()

    _write_snapshot(tmp_path, "api", 2048)
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    projects = {p.directory: p for p in db.get_project_stats(conn)}
    assert projects["/work/api"].snapshot_size == 0
    assert projects["/oss/api"].snapshot_size == 0
    # A single unambiguous basename elsewhere is still attributed.
    _write_snapshot(tmp_path, "project", 512)
    projects = {p.directory: p for p in db.get_project_stats(conn)}
    assert projects["/path/to/project"].snapshot_size == 512
    conn.close()


def test_project_stats_project_id_case_collision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    now = int(time.time() * 1000)
    conn.execute("DELETE FROM session_message")
    conn.execute("DELETE FROM session_v2")
    for sid, pid, directory in (("ses_a1", "Proj_A", "/work/a"), ("ses_a2", "proj_a", "/work/b")):
        conn.execute(
            "INSERT INTO session_v2 (id, project_id, slug, directory, title, version, time_created, time_updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, pid, sid, directory, sid, "v2", now, now),
        )
    conn.commit()

    _write_snapshot(tmp_path, "Proj_A", 4096)
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    projects = db.get_project_stats(conn)
    assert {p.project_id for p in projects} == {"Proj_A", "proj_a"}
    # Ambiguous case-insensitive project id match must not be attributed to either.
    assert all(p.snapshot_size == 0 for p in projects)
    conn.close()


def test_project_stats_empty_string_worktree_not_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty-string worktree in the project table must not overwrite valid directories."""
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.execute("CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT NOT NULL)")
    conn.execute("INSERT INTO project VALUES (?, ?)", ("proj_1", ""))
    conn.commit()
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    projects = db.get_project_stats(conn)
    # Should retain the session_v2.directory, not the empty worktree.
    assert any(p.directory == "/path/to/project" for p in projects)
    assert not any(p.directory == "" for p in projects)
    conn.close()


def test_project_stats_limit_zero_is_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)
    assert db.get_project_stats(conn, limit=0) == []
    assert db.get_project_stats(conn, limit=-5) == []
    conn.close()


def test_project_stats_empty_directory_sorts_by_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When directory is empty, sorting by name should fall back to key (matching display)."""
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    now = int(time.time() * 1000)
    conn.execute("DELETE FROM session_message")
    conn.execute("DELETE FROM session_v2")
    # Insert sessions with empty directory so they fall back to project_id as display key.
    for sid, pid, key in (("ses_z", "zebra", "zebra"), ("ses_a", "alpha", "alpha")):
        conn.execute(
            "INSERT INTO session_v2 (id, project_id, slug, directory, title, version, time_created, time_updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, pid, sid, "", key, "v2", now, now),
        )
    conn.commit()
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    by_name = db.get_project_stats(conn, sort_by="name")
    # "alpha" should sort before "zebra" (empty directory falls back to key)
    assert [p.project_id for p in by_name] == ["alpha", "zebra"]
    conn.close()


def test_projects_cli_rejects_invalid_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")
    db_file = tmp_path / "v2.db"
    create_v2_db(db_file).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))

    for bad_limit in ("0", "-3"):
        res = runner.invoke(cli, ["projects", "--limit", bad_limit])
        assert res.exit_code != 0


def test_project_stats_missing_id_column_does_not_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A project table with worktree but no id column should not crash."""
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.execute("CREATE TABLE project_broken (worktree TEXT NOT NULL)")
    conn.execute("INSERT INTO project_broken VALUES ('/work/proj')")
    conn.commit()
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    # Should not raise OperationalError about missing id column.
    projects = db.get_project_stats(conn)
    assert isinstance(projects, list)
    conn.close()


def test_projects_cli_escapes_markup_in_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")
    db_file = tmp_path / "v2.db"
    conn = create_v2_db(db_file)
    now = int(time.time() * 1000)
    conn.execute("DELETE FROM session_message")
    conn.execute("DELETE FROM session_v2")
    conn.execute(
        "INSERT INTO session_v2 (id, project_id, slug, directory, title, version, time_created, time_updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("ses_bracket", "proj_bracket", "b", "/home/u/proj[1]", "bracket", "v2", now, now),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    res = runner.invoke(cli, ["projects"])
    assert res.exit_code == 0
    assert "[1]" in res.output


def test_projects_last_active_zero_shows_dash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A project with last_active == 0 should display '-' instead of a bogus age."""
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")
    db_file = tmp_path / "v2.db"
    conn = create_v2_db(db_file)
    conn.execute("DELETE FROM session_message")
    conn.execute("DELETE FROM session_v2")
    conn.execute(
        "INSERT INTO session_v2 (id, project_id, slug, directory, title, version, time_created, time_updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("ses_zero", "proj_zero", "z", "/work/zero", "Zero", "v2", 0, 0),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    res = runner.invoke(cli, ["projects"])
    assert res.exit_code == 0
    assert "-" in res.output
    assert "mo ago" not in res.output or "680mo" not in res.output


def test_projects_cli_and_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    db_file = tmp_path / "v2.db"
    create_v2_db(db_file).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)
    _write_snapshot(tmp_path, "proj_1", 1024)

    res = runner.invoke(cli, ["projects"])
    assert res.exit_code == 0
    assert "Project Storage Dashboard" in res.output
    assert "/path/to/project" in res.output

    res_sort = runner.invoke(cli, ["projects", "--sort", "sessions"])
    assert res_sort.exit_code == 0

    res_json = runner.invoke(cli, ["projects", "--json"])
    assert res_json.exit_code == 0
    payload = json.loads(res_json.output)
    assert payload["version"] == 2
    assert len(payload["projects"]) == 1
    assert payload["projects"][0]["snapshot_size"] == 1024
    assert payload["projects"][0]["session_count"] == 2

    # JSON output must stay machine-parseable even when OpenCode is detected as running.
    with patch.object(db, "check_opencode_running", return_value=True):
        res_json_running = runner.invoke(cli, ["projects", "--json"])
    assert res_json_running.exit_code == 0
    json.loads(res_json_running.output)


def test_projects_cli_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")
    # A v2 database with no sessions.
    db_file = tmp_path / "empty.db"
    conn = create_v2_db(db_file)
    conn.execute("DELETE FROM session_message")
    conn.execute("DELETE FROM session_v2")
    conn.commit()
    conn.close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    res = runner.invoke(cli, ["projects"])
    assert res.exit_code == 0
    assert "No projects found" in res.output

    res_json = runner.invoke(cli, ["projects", "--json"])
    assert res_json.exit_code == 0
    assert json.loads(res_json.output)["projects"] == []
