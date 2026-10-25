"""Token 消耗与缓存命中率大盘测试。"""

import json
import sqlite3
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from ocgc import db
from ocgc.cli import cli


def create_mock_v1_db(path: Path) -> sqlite3.Connection:
    """创建 v1 版本的测试数据库。"""
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
    """)
    now = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO session VALUES ('ses_v1_1', NULL, '/work/p1', 'V1 Session', ?, ?)",
        (now, now),
    )
    conn.commit()
    return conn


def create_mock_v2_db(path: Path) -> sqlite3.Connection:
    """创建包含 Token 指标的 v2 测试数据库。"""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE session_v2 (
            id TEXT PRIMARY KEY,
            project_id TEXT,
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
        CREATE TABLE project (
            id TEXT PRIMARY KEY,
            worktree TEXT,
            time_created INTEGER,
            time_updated INTEGER
        );
    """)

    now = int(time.time() * 1000)
    day = 86400 * 1000

    conn.execute(
        "INSERT INTO project VALUES ('proj_alpha', '/workspace/alpha', ?, ?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO project VALUES ('proj_beta', '/workspace/beta', ?, ?)",
        (now, now),
    )

    # 会话 1: proj_alpha, 模型 gemini-flash, 高缓存命中
    model_gemini = json.dumps({"id": "gemini-3.8-flash-high", "providerID": "gemini"})
    conn.execute(
        """
        INSERT INTO session_v2 (
            id, project_id, slug, directory, title, version,
            cost, tokens_input, tokens_output, tokens_reasoning,
            tokens_cache_read, tokens_cache_write, model,
            time_created, time_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ses_1", "proj_alpha", "slug-1", "/workspace/alpha", "Session Alpha 1", "v2",
            0.15, 1000, 500, 200, 9000, 100, model_gemini, now - day, now - day,
        ),
    )

    # 会话 2: proj_alpha, 模型 gpt-4o, 无缓存命中
    model_gpt = json.dumps({"id": "gpt-4o", "providerID": "openai"})
    conn.execute(
        """
        INSERT INTO session_v2 (
            id, project_id, slug, directory, title, version,
            cost, tokens_input, tokens_output, tokens_reasoning,
            tokens_cache_read, tokens_cache_write, model,
            time_created, time_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ses_2", "proj_alpha", "slug-2", "/workspace/alpha", "Session Alpha 2", "v2",
            0.80, 2000, 1000, 0, 0, 0, model_gpt, now - 2 * day, now - 2 * day,
        ),
    )

    # 会话 3: proj_beta, 模型 gemini-flash, 普通缓存命中
    conn.execute(
        """
        INSERT INTO session_v2 (
            id, project_id, slug, directory, title, version,
            cost, tokens_input, tokens_output, tokens_reasoning,
            tokens_cache_read, tokens_cache_write, model,
            time_created, time_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ses_3", "proj_beta", "slug-3", "/workspace/beta", "Session Beta", "v2",
            0.05, 3000, 800, 300, 3000, 50, model_gemini, now, now,
        ),
    )

    # 会话 4: 无项目 ID，普通字符串模型，所有 token 为 0（除以零边界）
    conn.execute(
        """
        INSERT INTO session_v2 (
            id, project_id, slug, directory, title, version,
            cost, tokens_input, tokens_output, tokens_reasoning,
            tokens_cache_read, tokens_cache_write, model,
            time_created, time_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ses_4", None, "slug-4", "/workspace/other", "Session Empty", "v2",
            0.0, 0, 0, 0, 0, 0, "custom-model", now + 10, now + 10,
        ),
    )

    conn.commit()
    return conn


def test_parse_model_name() -> None:
    """测试模型名称解析与归一化。"""
    # 空值与默认值
    assert db.parse_model_name(None) == "(unknown)"
    assert db.parse_model_name("", default="none") == "none"

    # JSON 格式且带 provider
    json_str = '{"id":"gemini-3.8-flash-high","providerID":"gemini"}'
    assert db.parse_model_name(json_str) == "gemini/gemini-3.8-flash-high"
    assert db.parse_model_name(json_str, include_provider=False) == "gemini-3.8-flash-high"

    # JSON 格式但缺少 id 与 name，回退默认值
    json_no_id = '{"variant":"high"}'
    assert db.parse_model_name(json_no_id) == "(unknown)"
    assert db.parse_model_name(json_no_id, default="") == ""

    # JSON 格式但 id 已带 provider 前缀
    json_str_dup = '{"id":"anthropic/claude-3-7","providerID":"anthropic"}'
    assert db.parse_model_name(json_str_dup) == "anthropic/claude-3-7"

    # JSON 格式但只有 name
    json_name = '{"name":"deepseek-r1"}'
    assert db.parse_model_name(json_name) == "deepseek-r1"

    # 非 JSON 普通字符串
    assert db.parse_model_name("claude-opus") == "claude-opus"
    # 畸变 JSON 文本
    assert db.parse_model_name("{invalid json") == "{invalid json"


def test_token_dataclasses_and_zero_division() -> None:
    """测试 Token 数据类的计算与除以零保护。"""
    stats = db.TokenGroupStats(
        name="test",
        session_count=1,
        tokens_input=0,
        tokens_output=0,
        tokens_reasoning=0,
        tokens_cache_read=0,
        tokens_cache_write=0,
        cost=0.0,
    )
    assert stats.total_tokens == 0
    assert stats.cache_hit_rate == 0.0

    stats_normal = db.TokenGroupStats(
        name="normal",
        session_count=2,
        tokens_input=1000,
        tokens_output=500,
        tokens_reasoning=100,
        tokens_cache_read=3000,
        tokens_cache_write=200,
        cost=1.2345,
    )
    # total = 1000 + 500 + 3000 = 4500
    assert stats_normal.total_tokens == 4500
    # cache_hit_rate = 3000 / (3000 + 1000) = 0.75
    assert stats_normal.cache_hit_rate == 0.75

    d = stats_normal.to_dict()
    assert d["total_tokens"] == 4500
    assert d["cache_hit_rate"] == 0.75
    assert d["cost"] == 1.2345

    # format_cost 精度测试
    from ocgc.units import format_cost
    assert format_cost(0.0) == "$0.00"
    assert format_cost(0.00004) == "$0.000040"
    assert format_cost(0.0025) == "$0.0025"
    assert format_cost(1.5) == "$1.50"
    assert format_cost(-1.5) == "-$1.50"
    assert format_cost(-0.00004) == "-$0.000040"


def test_tokens_v1_compatibility(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试 v1 数据库运行 tokens 命令的平滑降级。"""
    db_file = tmp_path / "opencode.db"
    conn = create_mock_v1_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    # 直接调用数据层
    conn_ro = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    conn_ro.row_factory = sqlite3.Row
    report = db.get_token_stats(conn_ro, version=1)
    conn_ro.close()

    assert not report.supported
    assert report.version == 1
    assert "OpenCode v1 schema does not record" in str(report.message)

    # 命令行 JSON 输出验证
    runner = CliRunner()
    result = runner.invoke(cli, ["tokens", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["version"] == 1
    assert not data["supported"]
    assert data["summary"] is None

    # 命令行终端文本输出验证
    text_res = runner.invoke(cli, ["tokens"])
    assert text_res.exit_code == 0
    assert "OpenCode v1 schema does not record" in text_res.output


def test_tokens_v2_aggregation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试 v2 数据库的指标聚合、缓存命中率计算与模型/项目分组。"""
    db_file = tmp_path / "opencode.db"
    conn = create_mock_v2_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    runner = CliRunner()
    result = runner.invoke(cli, ["tokens", "--json"])
    assert result.exit_code == 0

    data = json.loads(result.output)
    assert data["version"] == 2
    assert data["supported"]

    summary = data["summary"]
    assert summary["total_sessions"] == 4
    # 总 input: 1000 + 2000 + 3000 + 0 = 6000
    assert summary["tokens_input"] == 6000
    # 总 output: 500 + 1000 + 800 + 0 = 2300
    assert summary["tokens_output"] == 2300
    # 总 reasoning: 200 + 0 + 300 + 0 = 500
    assert summary["tokens_reasoning"] == 500
    # 总 cache read: 9000 + 0 + 3000 + 0 = 12000
    assert summary["tokens_cache_read"] == 12000
    # 总 cache write: 100 + 0 + 50 + 0 = 150
    assert summary["tokens_cache_write"] == 150
    # 总 tokens: 6000 + 2300 + 12000 = 20300
    assert summary["total_tokens"] == 20300
    # 总 hit rate: 12000 / (12000 + 6000) = 12000 / 18000 = 0.6667
    assert summary["cache_hit_rate"] == 0.6667
    # 总 cost: 0.15 + 0.80 + 0.05 + 0.0 = 1.0
    assert summary["total_cost"] == 1.0

    # 模型分组校验
    models = {m["name"]: m for m in data["models"]}
    assert "gemini/gemini-3.8-flash-high" in models
    assert "openai/gpt-4o" in models
    assert "custom-model" in models

    gemini_m = models["gemini/gemini-3.8-flash-high"]
    assert gemini_m["session_count"] == 2
    # input: 1000 + 3000 = 4000, cache_read: 9000 + 3000 = 12000 -> hit rate = 12000/16000 = 0.75
    assert gemini_m["cache_hit_rate"] == 0.75

    gpt_m = models["openai/gpt-4o"]
    assert gpt_m["session_count"] == 1
    assert gpt_m["cache_hit_rate"] == 0.0
    assert gpt_m["cost"] == 0.8

    # 项目分组校验 (应优先映射 worktree 规范路径)
    projects = {p["name"]: p for p in data["projects"]}
    assert "/workspace/alpha" in projects
    assert "/workspace/beta" in projects
    assert "/workspace/other" in projects

    alpha_p = projects["workspace/alpha" if "workspace/alpha" in projects else "/workspace/alpha"]
    assert alpha_p["session_count"] == 2


def test_tokens_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试 --project 与 --directory 过滤参数。"""
    db_file = tmp_path / "opencode.db"
    conn = create_mock_v2_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    runner = CliRunner()

    # 1. 按项目过滤 proj_beta（默认 all 视图只输出 models + projects）
    res_proj = runner.invoke(cli, ["tokens", "--project", "proj_beta", "--json"])
    assert res_proj.exit_code == 0
    data_proj = json.loads(res_proj.output)
    assert data_proj["summary"]["total_sessions"] == 1
    assert len(data_proj["projects"]) == 1

    # 1.1 按项目过滤且切换至 session 视图
    res_proj_sess = runner.invoke(cli, ["tokens", "--project", "proj_beta", "--by", "session", "--json"])
    assert res_proj_sess.exit_code == 0
    data_proj_sess = json.loads(res_proj_sess.output)
    assert data_proj_sess["sessions"][0]["id"] == "ses_3"

    # 2. 按目录通配符过滤
    res_dir = runner.invoke(cli, ["tokens", "--directory", "*alpha*", "--json"])
    assert res_dir.exit_code == 0
    data_dir = json.loads(res_dir.output)
    assert data_dir["summary"]["total_sessions"] == 2


def test_tokens_sorting_and_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试 --sort 与 --limit 排序与截断。"""
    db_file = tmp_path / "opencode.db"
    conn = create_mock_v2_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    runner = CliRunner()

    # 按费用排序并取前 1 个模型
    res_cost = runner.invoke(cli, ["tokens", "--sort", "cost", "--limit", "1", "--json"])
    assert res_cost.exit_code == 0
    data_cost = json.loads(res_cost.output)
    assert len(data_cost["models"]) == 1
    assert data_cost["models"][0]["name"] == "openai/gpt-4o"

    # 按命中率排序
    res_hr = runner.invoke(cli, ["tokens", "--sort", "hit-rate", "--json"])
    assert res_hr.exit_code == 0
    data_hr = json.loads(res_hr.output)
    assert data_hr["models"][0]["name"] == "gemini/gemini-3.8-flash-high"


def test_tokens_terminal_output_views(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试终端下 --by model, --by project, --by session 以及默认 all 视图。"""
    db_file = tmp_path / "opencode.db"
    conn = create_mock_v2_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    runner = CliRunner()

    # 默认 all 视图
    res_all = runner.invoke(cli, ["tokens"])
    assert res_all.exit_code == 0
    assert "Token Usage & Cache by Model" in res_all.output
    assert "Token Usage & Cache by Project" in res_all.output

    # 仅 model 视图
    res_model = runner.invoke(cli, ["tokens", "--by", "model"])
    assert res_model.exit_code == 0
    assert "Token Usage & Cache by Model" in res_model.output
    assert "Token Usage & Cache by Project" not in res_model.output

    # 仅 project 视图
    res_proj = runner.invoke(cli, ["tokens", "--by", "project"])
    assert res_proj.exit_code == 0
    assert "Token Usage & Cache by Model" not in res_proj.output
    assert "Token Usage & Cache by Project" in res_proj.output

    # 仅 session 视图
    res_sess = runner.invoke(cli, ["tokens", "--by", "session"])
    assert res_sess.exit_code == 0
    assert "Session Token Details" in res_sess.output

    # JSON 模式下 --by 过滤验证
    res_m_json = runner.invoke(cli, ["tokens", "--by", "model", "--json"])
    assert res_m_json.exit_code == 0
    data_m = json.loads(res_m_json.output)
    assert "models" in data_m and "projects" not in data_m and "sessions" not in data_m

    res_p_json = runner.invoke(cli, ["tokens", "--by", "project", "--json"])
    assert res_p_json.exit_code == 0
    data_p = json.loads(res_p_json.output)
    assert "projects" in data_p and "models" not in data_p and "sessions" not in data_p

    res_s_json = runner.invoke(cli, ["tokens", "--by", "session", "--json"])
    assert res_s_json.exit_code == 0
    data_s = json.loads(res_s_json.output)
    assert "sessions" in data_s and "models" not in data_s and "projects" not in data_s


def test_tokens_limit_zero_and_missing_project_id(tmp_path: Path) -> None:
    """测试 limit=0 语义以及缺少 project_id 列的防御性降级。"""
    db_file = tmp_path / "opencode_no_proj.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    # 建立缺少 project_id 列的精简 session_v2
    conn.executescript("""
        CREATE TABLE session_v2 (
            id TEXT PRIMARY KEY,
            directory TEXT NOT NULL,
            title TEXT,
            model TEXT,
            cost REAL DEFAULT 0,
            tokens_input INTEGER DEFAULT 0,
            tokens_output INTEGER DEFAULT 0,
            tokens_reasoning INTEGER DEFAULT 0,
            tokens_cache_read INTEGER DEFAULT 0,
            tokens_cache_write INTEGER DEFAULT 0,
            time_created INTEGER NOT NULL
        );
        INSERT INTO session_v2 VALUES (
            'ses_legacy', '/workspace/demo', 'Legacy', 'gemini-flash',
            0.1, 100, 50, 0, 500, 0, 1000
        );
    """)
    conn.commit()

    # 1. 验证缺少 project_id 传入 project 过滤不会抛 OperationalError
    report_filter = db.get_token_stats(conn, project="demo", version=2)
    assert report_filter.supported
    assert report_filter.summary is not None
    assert report_filter.summary.total_sessions == 1

    # 2. 验证 limit=0 截断行为与 get_project_stats 保持一致返回空列表
    report_zero = db.get_token_stats(conn, limit=0, version=2)
    assert report_zero.supported
    assert len(report_zero.models) == 0
    assert len(report_zero.projects) == 0
    assert len(report_zero.sessions) == 0

    conn.close()

