"""Unit and integration tests for ocgc auto (one-click storage optimization presets)."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from test_v1_and_v2 import create_v1_db, create_v2_db

from ocgc import db
from ocgc.cli import cli
from ocgc.optimizer import execute_optimization, plan_optimization


def test_auto_safe_v2_execution(tmp_path: Path) -> None:
    """验证 v2 模式下一键优化 Safe 策略的执行（清理孤立diff、临时工具输出、14天前会话reasoning及WAL checkpoint）。"""
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)

    now = int(time.time() * 1000)
    day = 86400 * 1000

    # 插入一个 20 天前的旧会话（含 reasoning）
    conn.execute(
        """
        INSERT INTO session_v2 (
            id, project_id, parent_id, slug, directory, title, version,
            cost, tokens_input, tokens_output, tokens_reasoning,
            tokens_cache_read, tokens_cache_write, time_created, time_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("ses_old_20d", "proj_1", None, "old-slug", "/path/to/project", "Old Session", "2.0",
         0, 0, 0, 100, 0, 0, now - 20 * day, now - 20 * day),
    )
    conn.execute(
        """
        INSERT INTO session_message (id, session_id, type, seq, time_created, time_updated, data)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "msg_old_1",
            "ses_old_20d",
            "assistant",
            1,
            now - 20 * day,
            now - 20 * day,
            json.dumps({"content": [{"type": "reasoning", "text": "deep thoughts"}, {"type": "text", "text": "ans"}]}),
        ),
    )
    conn.commit()
    conn.close()

    # 准备孤立 diff 文件
    diff_dir = tmp_path / "storage" / "session_diff"
    diff_dir.mkdir(parents=True, exist_ok=True)
    orphan_file = diff_dir / "ses_nonexistent.json"
    orphan_file.write_text("{}", encoding="utf-8")
    valid_diff = diff_dir / "ses_v2_root.json"
    valid_diff.write_text("{}", encoding="utf-8")

    # 准备工具输出缓存文件
    tool_dir = tmp_path / "tool-output"
    tool_dir.mkdir(parents=True, exist_ok=True)
    tool_file = tool_dir / "output.txt"
    tool_file.write_text("some large tool output", encoding="utf-8")

    # 准备 WAL 文件
    wal_file = tmp_path / "opencode.db-wal"
    wal_file.write_bytes(b"\x00" * 4096)

    runner = CliRunner(env={"COLUMNS": "200"})
    with patch.object(db, "get_db_path", return_value=db_file), patch.object(
        db, "get_storage_dir", return_value=tmp_path
    ), patch.object(db, "check_opencode_running", return_value=False):
        result = runner.invoke(cli, ["auto", "--preset", "safe", "--force"])
        assert result.exit_code == 0, result.output
        assert "Optimization Complete (SAFE)" in result.output
        assert "Deleted 1 orphan diff file(s)" in result.output
        assert re.search(r"Deleted 1\s+tool output", result.output)
        assert re.search(r"Deleted 1\s+reasoning part\(s\)", result.output)

    # 验证孤立 diff 被删除，有效会话的 diff 保留
    assert not orphan_file.exists()
    assert valid_diff.exists()
    # 验证工具输出文件被清理
    assert not tool_file.exists()

    # 验证 20 天旧会话的 reasoning 被剥离，但会话本身保留
    check_conn = sqlite3.connect(str(db_file))
    check_conn.row_factory = sqlite3.Row
    s_row = check_conn.execute("SELECT id FROM session_v2 WHERE id = 'ses_old_20d'").fetchone()
    assert s_row is not None
    m_row = check_conn.execute("SELECT data FROM session_message WHERE id = 'msg_old_1'").fetchone()
    data = json.loads(m_row["data"])
    types = [c.get("type") for c in data.get("content", [])]
    assert "reasoning" not in types
    assert "text" in types

    # 验证活跃会话 ses_v2_root 依然完整
    root_row = check_conn.execute("SELECT id FROM session_v2 WHERE id = 'ses_v2_root'").fetchone()
    assert root_row is not None
    check_conn.close()


def test_auto_safe_v1_execution(tmp_path: Path) -> None:
    """验证 v1 模式下一键优化 Safe 策略的执行。"""
    db_file = tmp_path / "opencode.db"
    conn = create_v1_db(db_file)

    now = int(time.time() * 1000)
    day = 86400 * 1000

    # 插入一个 15 天前旧会话
    conn.execute(
        "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
        ("ses_v1_old_15d", None, "/path/to/project", "Old V1 Session", now - 15 * day, now - 15 * day),
    )
    conn.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
        ("msg_v1_old", "ses_v1_old_15d", now - 15 * day, now - 15 * day, "{}"),
    )
    conn.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
        (
            "part_v1_old_reasoning",
            "msg_v1_old",
            "ses_v1_old_15d",
            now - 15 * day,
            now - 15 * day,
            json.dumps({"type": "reasoning", "text": "thinking..."}),
        ),
    )
    conn.commit()
    conn.close()

    runner = CliRunner(env={"COLUMNS": "200"})
    with patch.object(db, "get_db_path", return_value=db_file), patch.object(
        db, "get_storage_dir", return_value=tmp_path
    ), patch.object(db, "check_opencode_running", return_value=False):
        result = runner.invoke(cli, ["auto", "--preset", "safe", "--force"])
        assert result.exit_code == 0, result.output
        assert "Optimization Complete (SAFE)" in result.output
        assert re.search(r"Deleted 1\s+reasoning part\(s\)", result.output)

    # 验证旧会话保留但 reasoning 已删除
    check_conn = sqlite3.connect(str(db_file))
    r_part = check_conn.execute("SELECT * FROM part WHERE id = 'part_v1_old_reasoning'").fetchone()
    assert r_part is None
    s_row = check_conn.execute("SELECT id FROM session WHERE id = 'ses_v1_old_15d'").fetchone()
    assert s_row is not None
    check_conn.close()


def test_auto_aggressive_v2_execution(tmp_path: Path) -> None:
    """验证 v2 模式下一键优化 Aggressive 策略的执行（清理30天前旧会话、清空快照、剥离全库reasoning及VACUUM）。"""
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)

    now = int(time.time() * 1000)
    day = 86400 * 1000

    # 插入一个 35 天前旧会话
    conn.execute(
        """
        INSERT INTO session_v2 (
            id, project_id, parent_id, slug, directory, title, version,
            cost, tokens_input, tokens_output, tokens_reasoning,
            tokens_cache_read, tokens_cache_write, time_created, time_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("ses_old_35d", "proj_1", None, "ancient", "/path/to/project", "Ancient Session", "2.0",
         0, 0, 0, 50, 0, 0, now - 35 * day, now - 35 * day),
    )
    conn.commit()
    conn.close()

    # 准备 snapshot 目录
    snap_dir = tmp_path / "snapshot" / "proj_1"
    snap_dir.mkdir(parents=True, exist_ok=True)
    (snap_dir / "packfile.pack").write_bytes(b"snapshotpack")

    runner = CliRunner(env={"COLUMNS": "200"})
    with patch.object(db, "get_db_path", return_value=db_file), patch.object(
        db, "get_storage_dir", return_value=tmp_path
    ), patch.object(db, "check_opencode_running", return_value=False):
        result = runner.invoke(cli, ["auto", "--preset", "aggressive", "--force"])
        assert result.exit_code == 0, result.output
        assert "Optimization Complete (AGGRESSIVE)" in result.output
        assert "Deleted 1 session(s)" in result.output
        assert "Deleted 1 snapshot dir(s)" in result.output
        assert re.search(r"Deleted \d+\s+reasoning part\(s\)", result.output)

    # 验证 35 天会话已被物理删除
    check_conn = sqlite3.connect(str(db_file))
    check_conn.row_factory = sqlite3.Row
    s_row = check_conn.execute("SELECT id FROM session_v2 WHERE id = 'ses_old_35d'").fetchone()
    assert s_row is None
    # 验证活跃会话仍存在，但其 reasoning 被剥离
    root_row = check_conn.execute("SELECT id FROM session_v2 WHERE id = 'ses_v2_root'").fetchone()
    assert root_row is not None
    m_row = check_conn.execute("SELECT data FROM session_message WHERE id = 'msg_v2_2'").fetchone()
    assert m_row is not None
    data = json.loads(m_row["data"])
    types = [c.get("type") for c in data.get("content", [])]
    assert "reasoning" not in types

    # 验证快照目录已删除
    assert not snap_dir.exists()
    check_conn.close()


def test_auto_dry_run_leaves_data_intact(tmp_path: Path) -> None:
    """验证 --dry-run 仅展示计划，不修改任何文件和数据库内容。"""
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    # 创建孤立 diff
    diff_dir = tmp_path / "storage" / "session_diff"
    diff_dir.mkdir(parents=True, exist_ok=True)
    orphan_file = diff_dir / "ses_nonexistent.json"
    orphan_file.write_text("{}", encoding="utf-8")

    runner = CliRunner(env={"COLUMNS": "200"})
    with patch.object(db, "get_db_path", return_value=db_file), patch.object(
        db, "get_storage_dir", return_value=tmp_path
    ), patch.object(db, "check_opencode_running", return_value=False):
        result = runner.invoke(cli, ["auto", "--preset", "safe", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "Dry Run — Optimization Plan" in result.output
        assert "No changes were applied" in result.output

    # 验证孤立 diff 仍然存在
    assert orphan_file.exists()


def test_auto_json_output(tmp_path: Path) -> None:
    """验证 --json 模式下的结构化 JSON 输出（dry-run 及 force 两种情形）。"""
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    runner = CliRunner()
    with patch.object(db, "get_db_path", return_value=db_file), patch.object(
        db, "get_storage_dir", return_value=tmp_path
    ), patch.object(db, "check_opencode_running", return_value=False):
        # 1. dry-run JSON
        dry_res = runner.invoke(cli, ["auto", "--preset", "safe", "--dry-run", "--json"])
        assert dry_res.exit_code == 0, dry_res.output
        plan_data = json.loads(dry_res.output)
        assert plan_data["preset"] == "safe"
        assert plan_data["db_version"] == 2
        assert "steps" in plan_data
        assert len(plan_data["steps"]) == 4

        # 2. execution JSON with force
        exec_res = runner.invoke(cli, ["auto", "--preset", "safe", "--force", "--json"])
        assert exec_res.exit_code == 0, exec_res.output
        exec_data = json.loads(exec_res.output)
        assert exec_data["preset"] == "safe"
        assert exec_data["dry_run"] is False
        assert "total_bytes_reclaimed" in exec_data
        assert len(exec_data["steps"]) == 4


def test_auto_missing_database_error(tmp_path: Path) -> None:
    """验证数据库不存在时优雅报错。"""
    missing_db = tmp_path / "nonexistent.db"
    runner = CliRunner()
    with patch.object(db, "get_db_path", return_value=missing_db), patch.object(
        db, "check_opencode_running", return_value=False
    ):
        result = runner.invoke(cli, ["auto", "--preset", "safe"])
        assert result.exit_code == 1
        assert "Database not found" in result.output or "Error:" in result.output


def test_auto_prompt_abort(tmp_path: Path) -> None:
    """验证用户在交互式确认中选择取消时中止操作。"""
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    runner = CliRunner()
    with patch.object(db, "get_db_path", return_value=db_file), patch.object(
        db, "get_storage_dir", return_value=tmp_path
    ), patch.object(db, "check_opencode_running", return_value=False):
        # 输入 'n' 中止执行
        result = runner.invoke(cli, ["auto", "--preset", "safe"], input="n\n")
        assert result.exit_code == 0
        assert "Optimization aborted." in result.output


def test_auto_opencode_running_prompt(tmp_path: Path) -> None:
    """验证 OpenCode 处于运行状态时的交互提示与防护。"""
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    runner = CliRunner()
    with patch.object(db, "get_db_path", return_value=db_file), patch.object(
        db, "get_storage_dir", return_value=tmp_path
    ), patch.object(db, "check_opencode_running", return_value=True):
        # 用户在 OpenCode 运行提示中选择 'n'
        result = runner.invoke(cli, ["auto", "--preset", "safe"], input="n\n")
        assert result.exit_code == 0
        assert "opencode appears to be running" in result.output


def test_auto_direct_plan_and_execution_api(tmp_path: Path) -> None:
    """直接测试 plan_optimization 和 execute_optimization 的 API 数据结构。"""
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    with patch.object(db, "get_storage_dir", return_value=tmp_path):
        plan = plan_optimization(preset="safe", db_path=db_file)
        assert plan.preset == "safe"
        assert plan.db_version == 2
        assert len(plan.steps) == 4
        assert plan.steps[0].step_id == "clean_orphans"
        assert plan.steps[1].step_id == "clean_tool_output"
        assert plan.steps[2].step_id == "strip_reasoning"
        assert plan.steps[3].step_id == "checkpoint"

        result = execute_optimization(plan, db_path=db_file)
        assert result.preset == "safe"
        assert result.dry_run is False
        assert len(result.steps) == 4
        res_dict = result.to_dict()
        assert res_dict["preset"] == "safe"
        assert "total_bytes_reclaimed" in res_dict
