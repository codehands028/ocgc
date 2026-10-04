"""Unit and integration tests for ocgc doctor (database and storage health check)."""

import json
import os
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from test_v1_and_v2 import create_v1_db, create_v2_db

from ocgc import db
from ocgc.cli import cli
from ocgc.doctor import CheckStatus, diagnose


def test_doctor_v2_healthy(tmp_path: Path) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    with patch.object(db, "get_storage_dir", return_value=tmp_path), patch.object(
        db, "check_opencode_running", return_value=False
    ):
        report = diagnose(db_path=db_file)

    assert report.is_healthy is True
    assert report.has_critical_error is False
    assert report.db_version == 2
    assert len(report.checks) >= 5
    for c in report.checks:
        assert c.status in (CheckStatus.OK, CheckStatus.INFO)


def test_doctor_v1_healthy(tmp_path: Path) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v1_db(db_file)
    conn.close()

    with patch.object(db, "get_storage_dir", return_value=tmp_path), patch.object(
        db, "check_opencode_running", return_value=False
    ):
        report = diagnose(db_path=db_file)

    assert report.is_healthy is True
    assert report.has_critical_error is False
    assert report.db_version == 1
    for c in report.checks:
        assert c.status in (CheckStatus.OK, CheckStatus.INFO)


def test_doctor_missing_db(tmp_path: Path) -> None:
    db_file = tmp_path / "nonexistent.db"
    report = diagnose(db_path=db_file)

    assert report.is_healthy is False
    assert report.has_critical_error is True
    assert report.db_version is None
    assert any(c.status == CheckStatus.ERROR and c.category == "permission" for c in report.checks)
    assert len(report.suggested_actions) > 0


def test_doctor_corrupt_db(tmp_path: Path) -> None:
    db_file = tmp_path / "corrupt.db"
    # Write invalid SQLite header / corrupt bytes
    db_file.write_bytes(b"SQLite format 3\x00" + b"\xff" * 500)

    report = diagnose(db_path=db_file)
    assert report.has_critical_error is True
    assert report.is_healthy is False
    assert any(
        c.category in ("integrity", "schema", "connection") and c.status == CheckStatus.ERROR
        for c in report.checks
    )


def test_doctor_wal_bloat(tmp_path: Path) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    wal_file = tmp_path / "opencode.db-wal"
    # Create 35 MB WAL
    wal_file.write_bytes(b"\x00" * (35 * 1024 * 1024))

    with patch.object(db, "get_storage_dir", return_value=tmp_path), patch.object(
        db, "check_opencode_running", return_value=False
    ):
        report = diagnose(db_path=db_file)

    assert report.is_healthy is False
    wal_checks = [c for c in report.checks if c.category == "wal"]
    assert len(wal_checks) == 1
    assert wal_checks[0].status == CheckStatus.WARN
    assert any("ocgc checkpoint" in act for act in report.suggested_actions)

    # Test extreme WAL bloat (> 100 MB)
    wal_file.write_bytes(b"\x00" * (105 * 1024 * 1024))
    with patch.object(db, "get_storage_dir", return_value=tmp_path), patch.object(
        db, "check_opencode_running", return_value=False
    ):
        report_large = diagnose(db_path=db_file)
    wal_checks_large = [c for c in report_large.checks if c.category == "wal"]
    assert "excessive uncommitted log" in wal_checks_large[0].message


def test_doctor_dangling_records_v2(tmp_path: Path) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    now = int(time.time() * 1000)

    # Insert dangling message (session does not exist)
    conn.execute(
        "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("msg_orphan", "ses_nonexistent", "user", 99, now, now, "{}"),
    )
    # Insert dangling instruction_entry (session does not exist)
    conn.execute(
        "INSERT INTO instruction_entry VALUES (?, ?, ?, ?, ?, ?)",
        ("inst_orphan", "ses_nonexistent", "entry", now, now, "{}"),
    )
    conn.commit()
    conn.close()

    with patch.object(db, "get_storage_dir", return_value=tmp_path), patch.object(
        db, "check_opencode_running", return_value=False
    ):
        report = diagnose(db_path=db_file)

    assert report.is_healthy is False
    rel_checks = [c for c in report.checks if c.category == "relational"]
    assert len(rel_checks) == 1
    assert rel_checks[0].status == CheckStatus.WARN
    assert "dangling record(s) found" in rel_checks[0].message


def test_doctor_dangling_records_v1(tmp_path: Path) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v1_db(db_file)
    now = int(time.time() * 1000)

    # Insert dangling message
    conn.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
        ("msg_v1_orphan", "ses_v1_missing", now, now, "{}"),
    )
    # Insert dangling part
    conn.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
        ("part_v1_orphan", "msg_v1_missing", "ses_v1_root", now, now, "{}"),
    )
    conn.commit()
    conn.close()

    with patch.object(db, "get_storage_dir", return_value=tmp_path), patch.object(
        db, "check_opencode_running", return_value=False
    ):
        report = diagnose(db_path=db_file)

    assert report.is_healthy is False
    rel_checks = [c for c in report.checks if c.category == "relational"]
    assert len(rel_checks) == 1
    assert rel_checks[0].status == CheckStatus.WARN
    assert "dangling record(s) found" in rel_checks[0].message


def test_doctor_incomplete_schema(tmp_path: Path) -> None:
    db_file = tmp_path / "opencode.db"
    conn = sqlite3.connect(str(db_file))
    # Only create session_v2, drop session_message
    conn.execute("CREATE TABLE session_v2 (id TEXT PRIMARY KEY, directory TEXT);")
    conn.commit()
    conn.close()

    with patch.object(db, "get_storage_dir", return_value=tmp_path), patch.object(
        db, "check_opencode_running", return_value=False
    ):
        report = diagnose(db_path=db_file)

    assert report.has_critical_error is True
    schema_checks = [c for c in report.checks if c.category == "schema"]
    assert any(c.status == CheckStatus.ERROR for c in schema_checks)


def test_doctor_orphan_diffs(tmp_path: Path) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    diff_dir = tmp_path / "storage" / "session_diff"
    diff_dir.mkdir(parents=True, exist_ok=True)
    # Create diff file for non-existent session
    orphan_file = diff_dir / "ses_orphan_123.json"
    orphan_file.write_text("diff content")

    with patch.object(db, "get_storage_dir", return_value=tmp_path), patch.object(
        db, "check_opencode_running", return_value=False
    ):
        report = diagnose(db_path=db_file)

    assert report.is_healthy is False
    diff_checks = [c for c in report.checks if c.category == "filesystem"]
    assert len(diff_checks) == 1
    assert diff_checks[0].status == CheckStatus.WARN
    assert "1 file(s) found" in diff_checks[0].message
    assert any("ocgc purge --clean-orphans" in act for act in report.suggested_actions)


def test_doctor_snapshot_readonly(tmp_path: Path) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    snap_file = tmp_path / "snapshot" / "proj_readonly" / "pack.pack"
    snap_file.parent.mkdir(parents=True, exist_ok=True)
    snap_file.write_text("packdata")
    os.chmod(snap_file, 0o444)

    try:
        with patch.object(db, "get_storage_dir", return_value=tmp_path), patch.object(
            db, "check_opencode_running", return_value=False
        ):
            report = diagnose(db_path=db_file)

        assert report.is_healthy is False
        perm_checks = [c for c in report.checks if c.title == "File permissions"]
        assert len(perm_checks) == 1
        assert perm_checks[0].status == CheckStatus.WARN
        assert "read-only item(s)" in perm_checks[0].message
    finally:
        os.chmod(snap_file, 0o666)


def test_doctor_snapshot_dir_itself_readonly(tmp_path: Path) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    snap_dir = tmp_path / "snapshot"
    snap_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(snap_dir, 0o555)

    try:
        with patch.object(db, "get_storage_dir", return_value=tmp_path), patch.object(
            db, "check_opencode_running", return_value=False
        ):
            report = diagnose(db_path=db_file)

        assert report.is_healthy is False
        perm_checks = [c for c in report.checks if c.title == "File permissions"]
        assert len(perm_checks) == 1
        assert perm_checks[0].status == CheckStatus.WARN
    finally:
        os.chmod(snap_dir, 0o755)


def test_doctor_running_opencode(tmp_path: Path) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    with patch.object(db, "check_opencode_running", return_value=True), patch.object(
        db, "get_storage_dir", return_value=tmp_path
    ):
        report = diagnose(db_path=db_file)

    assert report.is_healthy is False
    proc_checks = [c for c in report.checks if c.category == "process"]
    assert len(proc_checks) == 1
    assert proc_checks[0].status == CheckStatus.WARN
    assert "actively running" in proc_checks[0].message


def test_doctor_cli_runner(tmp_path: Path) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    runner = CliRunner()
    with patch.object(db, "get_db_path", return_value=db_file), patch.object(
        db, "get_storage_dir", return_value=tmp_path
    ), patch.object(db, "check_opencode_running", return_value=False):
        # Default invocation
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 0
        assert "ocgc doctor" in result.output
        assert "Database integrity" in result.output

        # Quick flag
        result_quick = runner.invoke(cli, ["doctor", "--quick"])
        assert result_quick.exit_code == 0
        assert "PRAGMA quick_check passed" in result_quick.output

        # JSON flag
        result_json = runner.invoke(cli, ["doctor", "--json"])
        assert result_json.exit_code == 0
        parsed = json.loads(result_json.output)
        assert parsed["healthy"] is True
        assert parsed["critical_error"] is False
        assert parsed["db_version"] == 2
        assert isinstance(parsed["checks"], list)


def test_doctor_cli_critical_error_exit_code(tmp_path: Path) -> None:
    db_file = tmp_path / "nonexistent.db"
    runner = CliRunner()
    with patch.object(db, "get_db_path", return_value=db_file):
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 1
