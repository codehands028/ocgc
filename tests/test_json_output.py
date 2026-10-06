"""结构化 JSON 输出功能单元与集成测试 (Structured JSON output tests)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from test_v1_and_v2 import create_v1_db, create_v2_db

from ocgc import db
from ocgc.cli import cli


def test_models_to_dict(tmp_path: Path) -> None:
    """测试各数据模型对象的 to_dict 方法序列化正确性。"""
    # 1. DBInfo
    db_info = db.DBInfo(path=tmp_path / "opencode.db", db_size=1024, wal_size=512, version=2)
    db_dict = db_info.to_dict()
    assert db_dict["path"] == str(tmp_path / "opencode.db")
    assert db_dict["db_size"] == 1024
    assert db_dict["wal_size"] == 512
    assert db_dict["total_size"] == 1536
    assert db_dict["version"] == 2

    # 2. SessionRow
    session_row = db.SessionRow(
        id="ses_123",
        parent_id=None,
        directory="/work/app",
        title="测试会话",
        time_created=1000,
        time_updated=2000,
        size_bytes=4096,
        message_count=5,
        project_id="proj_1",
    )
    s_dict = session_row.to_dict()
    assert s_dict["id"] == "ses_123"
    assert s_dict["parent_id"] is None
    assert s_dict["directory"] == "/work/app"
    assert s_dict["title"] == "测试会话"
    assert s_dict["time_created"] == 1000
    assert s_dict["time_updated"] == 2000
    assert s_dict["size_bytes"] == 4096
    assert s_dict["message_count"] == 5
    assert s_dict["project_id"] == "proj_1"
    assert s_dict["is_subagent"] is False

    # 3. ProjectRow
    project_row = db.ProjectRow(
        key="proj_1",
        directory="/work/app",
        project_id="proj_1",
        session_count=3,
        data_size=8192,
        snapshot_size=2048,
        last_active=3000,
    )
    p_dict = project_row.to_dict()
    assert p_dict["directory"] == "/work/app"
    assert p_dict["project_id"] == "proj_1"
    assert p_dict["session_count"] == 3
    assert p_dict["data_size"] == 8192
    assert p_dict["snapshot_size"] == 2048
    assert p_dict["total_size"] == 10240
    assert p_dict["last_active"] == 3000

    # 4. PartTypeStats
    part_stat = db.PartTypeStats(type_name="text", count=10, size_bytes=2048)
    part_dict = part_stat.to_dict()
    assert part_dict == {"type_name": "text", "count": 10, "size_bytes": 2048}

    # 5. FilesystemStats
    fs_stats = db.FilesystemStats(
        session_diff_size=100,
        snapshot_size=200,
        tool_output_size=300,
        session_diff_count=1,
        snapshot_count=2,
        tool_output_count=3,
    )
    fs_dict = fs_stats.to_dict()
    assert fs_dict["session_diff_size"] == 100
    assert fs_dict["snapshot_size"] == 200
    assert fs_dict["tool_output_size"] == 300
    assert fs_dict["total_size"] == 600

    # 6. OrphanDiff
    orphan = db.OrphanDiff(session_id="ses_orphan", path=tmp_path / "ses_orphan.json", size=50)
    orphan_dict = orphan.to_dict()
    assert orphan_dict == {
        "session_id": "ses_orphan",
        "path": str(tmp_path / "ses_orphan.json"),
        "size": 50,
    }


def test_status_json_v1_and_v2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试 status --json 在 v1 和 v2 数据库下的完整结构与字段。"""
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    # 1. 测试 v1 数据库
    db1 = tmp_path / "v1.db"
    create_v1_db(db1).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db1))

    res_v1 = runner.invoke(cli, ["status", "--json"])
    assert res_v1.exit_code == 0
    data_v1 = json.loads(res_v1.output)
    assert data_v1["version"] == 1
    assert data_v1["database"]["version"] == 1
    assert "db_size" in data_v1["database"]
    assert "total_size" in data_v1["database"]
    assert data_v1["sessions"]["total"] == 2
    assert data_v1["sessions"]["root"] == 1
    assert data_v1["sessions"]["subagent"] == 1
    assert "filesystem" in data_v1
    assert "total_on_disk" in data_v1
    assert isinstance(data_v1["part_types"], list)
    assert isinstance(data_v1["age_distribution"], dict)

    # 2. 测试 v2 数据库
    db2 = tmp_path / "v2.db"
    create_v2_db(db2).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db2))

    res_v2 = runner.invoke(cli, ["status", "--json"])
    assert res_v2.exit_code == 0
    data_v2 = json.loads(res_v2.output)
    assert data_v2["version"] == 2
    assert data_v2["database"]["version"] == 2
    assert data_v2["sessions"]["total"] == 2
    assert data_v2["sessions"]["root"] == 1
    assert data_v2["sessions"]["subagent"] == 1
    assert len(data_v2["part_types"]) > 0


def test_status_json_running_warning_suppressed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试当 OpenCode 运行时，status --json 不会受到警告文本干扰，保持机器可读纯 JSON。"""
    runner = CliRunner()
    db2 = tmp_path / "v2.db"
    create_v2_db(db2).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db2))
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    with patch.object(db, "check_opencode_running", return_value=True):
        res = runner.invoke(cli, ["status", "--json"])

    assert res.exit_code == 0
    parsed = json.loads(res.output)
    assert parsed["version"] == 2


def test_sessions_json_v1_and_v2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试 sessions --json 基本输出及会话字段。"""
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    # 1. v1
    db1 = tmp_path / "v1.db"
    create_v1_db(db1).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db1))

    res_v1 = runner.invoke(cli, ["sessions", "--json"])
    assert res_v1.exit_code == 0
    data_v1 = json.loads(res_v1.output)
    assert data_v1["version"] == 1
    assert data_v1["count"] == 2
    assert len(data_v1["sessions"]) == 2
    s0 = data_v1["sessions"][0]
    assert "id" in s0
    assert "directory" in s0
    assert "title" in s0
    assert "size_bytes" in s0
    assert "is_subagent" in s0

    # 2. v2
    db2 = tmp_path / "v2.db"
    create_v2_db(db2).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db2))

    res_v2 = runner.invoke(cli, ["sessions", "--json"])
    assert res_v2.exit_code == 0
    data_v2 = json.loads(res_v2.output)
    assert data_v2["version"] == 2
    assert data_v2["count"] == 2
    root_s = next(s for s in data_v2["sessions"] if not s["is_subagent"])
    sub_s = next(s for s in data_v2["sessions"] if s["is_subagent"])
    assert root_s["title"] == "V2 Root Session"
    assert sub_s["title"] == "V2 Subagent Session"
    assert sub_s["parent_id"] == "ses_v2_root"


def test_sessions_json_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试 sessions --json 配合 --limit, --sort, --project, --directory 选项。"""
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    db2 = tmp_path / "v2.db"
    conn = create_v2_db(db2)
    # 追加一个属于 proj_2 的会话，使 --project 过滤断言具备区分力
    # （仅断言 proj_1 会与不过滤时的总数相同，无法证明过滤真正生效）
    conn.execute(
        "INSERT INTO session_v2 (id, project_id, parent_id, slug, directory, title, version, "
        "time_created, time_updated, tokens_reasoning) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("ses_v2_proj2", "proj_2", None, "p2-slug", "/other/project", "V2 Proj2 Session", "v2", 1000, 1000, 0),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db2))

    # 测试 --limit 1
    res_limit = runner.invoke(cli, ["sessions", "--limit", "1", "--json"])
    assert res_limit.exit_code == 0
    data_limit = json.loads(res_limit.output)
    assert data_limit["count"] == 1
    assert len(data_limit["sessions"]) == 1

    # 测试 --sort age
    res_sort = runner.invoke(cli, ["sessions", "--sort", "age", "--json"])
    assert res_sort.exit_code == 0
    data_sort = json.loads(res_sort.output)
    assert data_sort["count"] == 3

    # 测试 --project proj_1（命中 root + subagent 共 2 条，少于总数 3）
    res_proj = runner.invoke(cli, ["sessions", "--project", "proj_1", "--json"])
    assert res_proj.exit_code == 0
    data_proj = json.loads(res_proj.output)
    assert data_proj["count"] == 2
    assert all(s["project_id"] == "proj_1" for s in data_proj["sessions"])

    # 测试 --project proj_2（命中 1 条，明确区别于不过滤时的 3 条）
    res_proj2 = runner.invoke(cli, ["sessions", "--project", "proj_2", "--json"])
    assert res_proj2.exit_code == 0
    data_proj2 = json.loads(res_proj2.output)
    assert data_proj2["count"] == 1
    assert data_proj2["sessions"][0]["id"] == "ses_v2_proj2"

    # 测试不存在的项目过滤 -> 返回 count 0 及空列表
    res_none = runner.invoke(cli, ["sessions", "--project", "nonexistent", "--json"])
    assert res_none.exit_code == 0
    data_none = json.loads(res_none.output)
    assert data_none["count"] == 0
    assert data_none["sessions"] == []


def test_sessions_json_empty_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试在空数据库下 sessions --json 正确返回空列表。"""
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    db_empty = tmp_path / "empty.db"
    conn = create_v2_db(db_empty)
    conn.execute("DELETE FROM session_message")
    conn.execute("DELETE FROM session_v2")
    conn.commit()
    conn.close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db_empty))

    res = runner.invoke(cli, ["sessions", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["version"] == 2
    assert data["count"] == 0
    assert data["sessions"] == []


def test_analyze_json_v1_and_v2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试 analyze --json 在 v1 和 v2 数据库下的完整分析报表结构。"""
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    # 1. v1
    db1 = tmp_path / "v1.db"
    create_v1_db(db1).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db1))

    res_v1 = runner.invoke(cli, ["analyze", "--json"])
    assert res_v1.exit_code == 0
    data_v1 = json.loads(res_v1.output)
    assert data_v1["version"] == 1
    assert data_v1["total_sessions"] == 2
    assert len(data_v1["top_sessions"]) == 2
    assert "total_part_bytes" in data_v1
    assert "avg_session_size" in data_v1
    assert "storage_by_session_type" in data_v1
    assert "root" in data_v1["storage_by_session_type"]
    assert "subagent" in data_v1["storage_by_session_type"]
    assert "filesystem" in data_v1
    assert "orphan_diffs" in data_v1

    # 2. v2
    db2 = tmp_path / "v2.db"
    create_v2_db(db2).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db2))

    res_v2 = runner.invoke(cli, ["analyze", "--json"])
    assert res_v2.exit_code == 0
    data_v2 = json.loads(res_v2.output)
    assert data_v2["version"] == 2
    assert data_v2["total_sessions"] == 2
    assert len(data_v2["top_sessions"]) == 2
    assert data_v2["top_sessions_limit"] == 10
    assert data_v2["storage_by_session_type"]["root"]["parts_count"] > 0
    assert data_v2["storage_by_session_type"]["subagent"]["parts_count"] > 0


def test_analyze_json_empty_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试空数据库下 analyze --json 返回有效的空报表结构而非崩溃。"""
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    db_empty = tmp_path / "empty.db"
    conn = create_v2_db(db_empty)
    conn.execute("DELETE FROM session_message")
    conn.execute("DELETE FROM session_v2")
    conn.commit()
    conn.close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db_empty))

    res = runner.invoke(cli, ["analyze", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["version"] == 2
    assert data["total_sessions"] == 0
    assert data["top_sessions"] == []
    assert data["total_part_bytes"] == 0
    assert data["avg_session_size"] == 0.0


def test_analyze_json_with_orphan_diffs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试包含孤立 diff 文件时，analyze --json 能正确输出孤立项。"""
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    db2 = tmp_path / "v2.db"
    create_v2_db(db2).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db2))

    # 创建一个孤立 diff 文件
    diff_dir = tmp_path / "storage" / "session_diff"
    diff_dir.mkdir(parents=True, exist_ok=True)
    orphan_file = diff_dir / "ses_unknown.json"
    orphan_file.write_text('{"diff": "data"}', encoding="utf-8")

    res = runner.invoke(cli, ["analyze", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["orphan_diffs"]["count"] == 1
    assert data["orphan_diffs"]["size_bytes"] > 0
    assert data["orphan_diffs"]["truncated"] is False
    assert data["orphan_diffs"]["items_limit"] == 20
    assert len(data["orphan_diffs"]["items"]) == 1
    assert data["orphan_diffs"]["items"][0]["session_id"] == "ses_unknown"


def test_analyze_json_orphan_diffs_truncated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试孤立 diff 超过上限时，analyze --json 仅返回前 N 条并标记 truncated。"""
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    db2 = tmp_path / "v2.db"
    create_v2_db(db2).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db2))

    # 创建超过 20 个孤立 diff 文件
    diff_dir = tmp_path / "storage" / "session_diff"
    diff_dir.mkdir(parents=True, exist_ok=True)
    for i in range(25):
        (diff_dir / f"ses_orphan_{i:02d}.json").write_text('{"diff": "data"}', encoding="utf-8")

    res = runner.invoke(cli, ["analyze", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["orphan_diffs"]["count"] == 25
    assert data["orphan_diffs"]["truncated"] is True
    assert data["orphan_diffs"]["items_limit"] == 20
    assert len(data["orphan_diffs"]["items"]) == 20


def test_sessions_non_json_still_warns_when_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试非 JSON 模式下，OpenCode 运行中仍会打印警告（JSON 模式才抑制）。"""
    runner = CliRunner()
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")
    monkeypatch.setattr(db, "get_storage_dir", lambda: tmp_path)

    db2 = tmp_path / "v2.db"
    create_v2_db(db2).close()
    monkeypatch.setenv("OCGC_DB_PATH", str(db2))

    with patch.object(db, "check_opencode_running", return_value=True):
        res = runner.invoke(cli, ["sessions"])

    assert res.exit_code == 0
    assert "appears to be running" in res.output
