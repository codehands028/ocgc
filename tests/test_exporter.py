"""Unit and integration tests for session Markdown export and archiving."""

import json
import sqlite3
import time
from pathlib import Path

import pytest
from click.testing import CliRunner
from test_v1_and_v2 import create_v1_db, create_v2_db

from ocgc import db
from ocgc.cli import cli
from ocgc.exporter import (
    generate_export_filename,
    render_session_to_markdown,
    sanitize_filename,
)


def test_sanitize_filename() -> None:
    assert sanitize_filename("Normal Title") == "Normal_Title"
    assert sanitize_filename("File: With * Forbidden? Characters / Test") == "File__With___Forbidden__Characters___Test"
    assert sanitize_filename("  ...leading and trailing...  ") == "leading_and_trailing"
    assert sanitize_filename("中文标题测试：需求分析与架构设计") == "中文标题测试_需求分析与架构设计"
    assert sanitize_filename("", max_length=50) == "untitled"
    assert sanitize_filename("   ???   ", max_length=50) == "untitled"

    long_title = "a" * 100
    sanitized = sanitize_filename(long_title, max_length=30)
    assert len(sanitized) <= 30


def test_v1_get_session_transcript(tmp_path: Path) -> None:
    db_file = tmp_path / "v1.db"
    conn = create_v1_db(db_file)

    transcript = db.get_session_transcript(conn, "ses_v1_root", version=1)
    assert transcript is not None
    assert transcript.id == "ses_v1_root"
    assert transcript.title == "V1 Root Session"
    assert transcript.directory == "/path/to/project"
    assert len(transcript.messages) == 1

    msg = transcript.messages[0]
    part_types = [p.type for p in msg.content_parts]
    assert "text" in part_types
    assert "reasoning" in part_types
    assert "tool" in part_types

    tool_part = next(p for p in msg.content_parts if p.type == "tool")
    assert tool_part.tool_name == "read"

    conn.close()


def test_v2_get_session_transcript(tmp_path: Path) -> None:
    db_file = tmp_path / "v2.db"
    conn = create_v2_db(db_file)

    transcript = db.get_session_transcript(conn, "ses_v2_root", version=2)
    assert transcript is not None
    assert transcript.id == "ses_v2_root"
    assert transcript.title == "V2 Root Session"
    assert transcript.project_id == "proj_1"
    assert transcript.tokens is not None
    assert transcript.tokens["reasoning"] == 150

    # User message & assistant message
    assert len(transcript.messages) >= 2
    user_msg = transcript.messages[0]
    assert user_msg.role == "user"
    assert user_msg.content_parts[0].text == "User question"

    asst_msg = transcript.messages[1]
    assert asst_msg.role == "assistant"
    asst_types = [p.type for p in asst_msg.content_parts]
    assert "reasoning" in asst_types
    assert "tool" in asst_types

    tool_part = next(p for p in asst_msg.content_parts if p.type == "tool")
    assert tool_part.tool_name == "bash"
    assert tool_part.tool_status == "completed"

    # Non-existent session
    assert db.get_session_transcript(conn, "non_existent", version=2) is None
    conn.close()


def test_v1_json_non_dict_data_robustness(tmp_path: Path) -> None:
    db_file = tmp_path / "v1_robust.db"
    conn = create_v1_db(db_file)
    # Insert a message with non-dict JSON data (e.g. list or string)
    now = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
        ("msg_non_dict", "ses_v1_root", now, now, json.dumps(["an", "array"])),
    )
    conn.commit()

    transcript = db.get_session_transcript(conn, "ses_v1_root", version=1)
    assert transcript is not None
    non_dict_msg = next(m for m in transcript.messages if m.id == "msg_non_dict")
    assert non_dict_msg.role == "unknown"
    conn.close()


def test_v2_user_content_string_and_fallback(tmp_path: Path) -> None:
    db_file = tmp_path / "v2_user_str.db"
    conn = create_v2_db(db_file)
    now = int(time.time() * 1000)
    # Insert user message where content is a plain string
    conn.execute(
        "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("msg_u_str", "ses_v2_root", "user", 10, now, now, json.dumps({"content": "string content from user"})),
    )
    # Insert user message with unknown structure
    conn.execute(
        "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("msg_u_unk", "ses_v2_root", "user", 11, now, now, json.dumps({"custom_field": "custom_val"})),
    )
    conn.commit()

    transcript = db.get_session_transcript(conn, "ses_v2_root", version=2)
    assert transcript is not None
    str_msg = next(m for m in transcript.messages if m.id == "msg_u_str")
    assert str_msg.content_parts[0].text == "string content from user"
    unk_msg = next(m for m in transcript.messages if m.id == "msg_u_unk")
    assert "custom_field" in unk_msg.content_parts[0].text
    conn.close()


def test_v2_standalone_reasoning_message_row_filtered(tmp_path: Path) -> None:
    db_file = tmp_path / "v2_standalone_rsn.db"
    conn = create_v2_db(db_file)
    now = int(time.time() * 1000)
    # Insert standalone reasoning message row (type = 'reasoning')
    rsn_payload = json.dumps({"text": "Deep standalone reasoning text"})
    conn.execute(
        "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("msg_rsn_row", "ses_v2_root", "reasoning", 12, now, now, rsn_payload),
    )
    conn.commit()

    transcript = db.get_session_transcript(conn, "ses_v2_root", version=2)
    assert transcript is not None

    # Test include_reasoning = True
    md_true = render_session_to_markdown(transcript, include_reasoning=True)
    assert "Deep standalone reasoning text" in md_true
    assert "💭 思考过程 (Reasoning)" in md_true

    # Test include_reasoning = False
    md_false = render_session_to_markdown(transcript, include_reasoning=False)
    assert "Deep standalone reasoning text" not in md_false
    assert "💭 思考过程 (Reasoning)" not in md_false
    conn.close()


def test_render_session_to_markdown() -> None:
    now = int(time.time() * 1000)
    transcript = db.SessionTranscript(
        id="ses_12345678abcdef",
        parent_id=None,
        title="测试会话导出",
        directory="/workspace/demo",
        project_id="my-project",
        time_created=now,
        time_updated=now,
        model="gemini-3.8-flash-high",
        tokens={"input": 1200, "output": 500, "reasoning": 300},
        messages=[
            db.SessionMessageRecord(
                id="msg_1",
                role="user",
                seq=1,
                time_created=now,
                content_parts=[
                    db.SessionContentPart(type="text", text="请帮我写一个快速排序算法"),
                    db.SessionContentPart(type="file", text="main.py"),
                ],
            ),
            db.SessionMessageRecord(
                id="msg_2",
                role="assistant",
                seq=2,
                time_created=now + 1000,
                content_parts=[
                    db.SessionContentPart(type="reasoning", text="思考快速排序的基准选择和分区算法..."),
                    db.SessionContentPart(type="text", text="好的，以下是快速排序实现："),
                    db.SessionContentPart(
                        type="tool",
                        tool_name="write",
                        tool_status="completed",
                        tool_input={"path": "sort.py", "content": "def quicksort(): pass"},
                        tool_output="File created successfully.",
                    ),
                ],
            ),
        ],
    )

    md_with_reasoning = render_session_to_markdown(transcript, include_reasoning=True)
    assert "# 测试会话导出" in md_with_reasoning
    assert "> **Session ID:** `ses_12345678abcdef`" in md_with_reasoning
    assert "> **Project:** `my-project`" in md_with_reasoning
    assert "> **Model:** `gemini-3.8-flash-high`" in md_with_reasoning
    assert "## 👤 User" in md_with_reasoning
    assert "请帮我写一个快速排序算法" in md_with_reasoning
    assert "- `main.py`" in md_with_reasoning
    assert "## 🤖 Assistant" in md_with_reasoning
    assert "💭 思考过程 (Reasoning)" in md_with_reasoning
    assert "思考快速排序的基准选择" in md_with_reasoning
    assert "🛠️ 工具调用: <code>write</code> (completed)" in md_with_reasoning
    assert '"path": "sort.py"' in md_with_reasoning
    assert "File created successfully." in md_with_reasoning

    # Test with reasoning disabled
    md_no_reasoning = render_session_to_markdown(transcript, include_reasoning=False)
    assert "💭 思考过程 (Reasoning)" not in md_no_reasoning
    assert "思考快速排序的基准选择" not in md_no_reasoning
    assert "好的，以下是快速排序实现：" in md_no_reasoning


def test_export_filename_generation() -> None:
    now = 1767225600000  # 2026-01-01
    transcript = db.SessionTranscript(
        id="ses_abc12345678",
        parent_id=None,
        title="Project Design Spec",
        directory="/proj",
        project_id=None,
        time_created=now,
        time_updated=now,
        model=None,
        tokens=None,
        messages=[],
    )
    fname = generate_export_filename(transcript)
    assert fname.startswith("2026-01-01_Project_Design_Spec_")
    assert fname.endswith(".md")


def test_cli_export_single_session_to_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    out_file = tmp_path / "exports" / "custom_export.md"
    runner = CliRunner()
    result = runner.invoke(cli, ["export", "--session", "ses_v2_root", "-o", str(out_file)])
    assert result.exit_code == 0
    assert out_file.exists()

    content = out_file.read_text(encoding="utf-8")
    assert "# V2 Root Session" in content
    assert "User question" in content


def test_cli_export_batch_by_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    out_dir = tmp_path / "project_exports"
    runner = CliRunner()
    result = runner.invoke(cli, ["export", "--project", "proj_1", "-o", str(out_dir)])
    assert result.exit_code == 0
    assert out_dir.is_dir()

    exported_files = list(out_dir.glob("*.md"))
    # Should export both ses_v2_root and ses_v2_sub
    assert len(exported_files) == 2


def test_cli_export_no_filter_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    runner = CliRunner()
    result = runner.invoke(cli, ["export"])
    assert result.exit_code != 0
    assert "Please specify sessions to export" in result.output


def test_cli_purge_with_archive_to_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    archive_dir = tmp_path / "my_archives"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["purge", "--session", "ses_v2_sub", "--archive-to", str(archive_dir), "--dry-run"],
    )
    assert result.exit_code == 0
    assert "Dry Run" in result.output
    assert "Archive to" in result.output
    # No files should have been written in dry run
    assert not archive_dir.exists()


def test_cli_purge_with_archive_to_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    archive_dir = tmp_path / "my_archives"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["purge", "--session", "ses_v2_sub", "--archive-to", str(archive_dir), "--force"],
    )
    assert result.exit_code == 0
    assert "Archived 1 session(s)" in result.output
    assert "Deleted 1 sessions" in result.output

    # Check that archive file was created
    assert archive_dir.is_dir()
    archived_files = list(archive_dir.glob("*.md"))
    assert len(archived_files) == 1

    content = archived_files[0].read_text(encoding="utf-8")
    assert "ses_v2_sub" in content

    # Check that session was deleted from database
    check_conn = sqlite3.connect(str(db_file))
    row = check_conn.execute("SELECT COUNT(*) FROM session_v2 WHERE id = 'ses_v2_sub'").fetchone()
    assert row[0] == 0
    check_conn.close()


def test_export_file_collision_handling(tmp_path: Path) -> None:
    from ocgc.exporter import export_session_to_file

    transcript = db.SessionTranscript(
        id="ses_collision_test",
        parent_id=None,
        title="Collision Test",
        directory="/dir",
        project_id=None,
        time_created=1767225600000,
        time_updated=1767225600000,
        model=None,
        tokens=None,
        messages=[],
    )

    out_dir = tmp_path / "collision_exports"
    file1 = export_session_to_file(transcript, output_path=out_dir, overwrite=False)
    file2 = export_session_to_file(transcript, output_path=out_dir, overwrite=False)
    assert file1 != file2
    assert file1.exists()
    assert file2.exists()
    assert "_1.md" in file2.name

    # Overwrite mode
    file3 = export_session_to_file(transcript, output_path=file1, overwrite=True)
    assert file3 == file1


def test_export_sessions_missing_session_error(tmp_path: Path) -> None:
    from ocgc.exporter import export_sessions

    db_file = tmp_path / "v2.db"
    conn = create_v2_db(db_file)
    out_dir = tmp_path / "exports"

    res = export_sessions(["ses_v2_root", "non_existent_id"], output_dir=out_dir, conn=conn)
    assert res.sessions_exported == 1
    assert len(res.errors) == 1
    assert res.errors[0][0] == "non_existent_id"
    conn.close()


def test_cli_export_all_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    out_dir = tmp_path / "all_exports"
    runner = CliRunner()
    result = runner.invoke(cli, ["export", "--all", "-o", str(out_dir)])
    assert result.exit_code == 0
    assert out_dir.is_dir()
    assert len(list(out_dir.glob("*.md"))) == 2


def test_cli_purge_archive_to_abort_on_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    # Create a regular file where archive directory is expected to cause an OSError
    conflict_file = tmp_path / "blocker_file"
    conflict_file.write_text("blocking directory creation")
    archive_path = conflict_file / "sub_dir"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["purge", "--session", "ses_v2_sub", "--archive-to", str(archive_path), "--force"],
    )
    assert result.exit_code != 0
    assert "Aborting operation to protect against data loss" in result.output

    # Crucial safety assertion: the session must NOT be deleted!
    check_conn = sqlite3.connect(str(db_file))
    row = check_conn.execute("SELECT COUNT(*) FROM session_v2 WHERE id = 'ses_v2_sub'").fetchone()
    assert row[0] == 1
    check_conn.close()


def test_cli_export_multiple_sessions_to_single_file_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    out_file = tmp_path / "single_file.md"
    runner = CliRunner()
    result = runner.invoke(cli, ["export", "--all", "-o", str(out_file)])
    assert result.exit_code != 0
    assert "Cannot export" in result.output
    assert "into a single file" in result.output


def test_markdown_fence_dynamic_with_backticks() -> None:
    now = int(time.time() * 1000)
    transcript = db.SessionTranscript(
        id="ses_backticks",
        parent_id=None,
        title="Backticks Test",
        directory="/dir",
        project_id=None,
        time_created=now,
        time_updated=now,
        model=None,
        tokens=None,
        messages=[
            db.SessionMessageRecord(
                id="msg_1",
                role="assistant",
                seq=1,
                time_created=now,
                content_parts=[
                    db.SessionContentPart(
                        type="tool",
                        tool_name="bash<script>",
                        tool_status="completed",
                        tool_input={"cmd": "echo '```python print(1) ```'"},
                        tool_output="Output with ```triple``` and ````quadruple```` backticks.",
                    )
                ],
            )
        ],
    )
    md = render_session_to_markdown(transcript)
    assert "bash&lt;script&gt;" in md
    # Should use at least 5 backticks to safely wrap 4 backticks
    assert "`````text" in md


def test_cli_purge_archive_to_requires_criteria(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    archive_dir = tmp_path / "archive_test"
    runner = CliRunner()
    result = runner.invoke(cli, ["purge", "--archive-to", str(archive_dir), "--force"])
    assert result.exit_code != 0
    assert "At least one purge selection flag is required with --archive-to" in result.output


def test_cli_purge_archive_to_all_sessions_and_diffs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    # Set up mock session_diff file
    diff_dir = tmp_path / "storage" / "session_diff"
    diff_dir.mkdir(parents=True, exist_ok=True)
    (diff_dir / "ses_v2_sub.json").write_text('{"diff": "sample diff content"}')

    archive_dir = tmp_path / "archive_all"
    runner = CliRunner()
    result = runner.invoke(cli, ["purge", "--project", "proj_1", "--archive-to", str(archive_dir), "--force"])
    assert result.exit_code == 0
    assert "Archived 2 session(s)" in result.output
    assert "1 session diff file(s)" in result.output
    assert "Deleted 2 sessions" in result.output

    # Check Markdown exports and diff archive
    assert (archive_dir / "diffs" / "ses_v2_sub.json").exists()
    md_files = list(archive_dir.glob("*.md"))
    assert len(md_files) == 2


def test_v1_tool_output_state_dict_handling(tmp_path: Path) -> None:
    db_file = tmp_path / "v1_tool_dict.db"
    conn = create_v1_db(db_file)
    now = int(time.time() * 1000)
    # Insert part with state dict containing dict output
    conn.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
        (
            "part_dict_tool",
            "msg_1",
            "ses_v1_root",
            now,
            now,
            json.dumps({
                "type": "tool",
                "call": "inspect_api",
                "state": {
                    "status": "completed",
                    "input": {"endpoint": "/v1/test"},
                    "output": {"status": "ok", "items": [1, 2, 3]},
                },
            }),
        ),
    )
    conn.commit()

    transcript = db.get_session_transcript(conn, "ses_v1_root", version=1)
    assert transcript is not None
    md = render_session_to_markdown(transcript)
    assert "inspect_api" in md
    assert '"status": "ok"' in md
    conn.close()


def test_export_cmd_whitespace_session_id_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    runner = CliRunner()
    result = runner.invoke(cli, ["export", "--session", "   "])
    assert result.exit_code != 0
    assert "Please specify sessions to export" in result.output


def test_export_cmd_multiple_sessions_to_non_md_file_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    out_file = tmp_path / "custom_report.txt"
    runner = CliRunner()
    result = runner.invoke(cli, ["export", "--all", "-o", str(out_file)])
    assert result.exit_code != 0
    assert "Cannot export" in result.output
    assert "custom_report.txt" in result.output


def test_purge_strip_reasoning_with_archive_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    archive_dir = Path("/tmp/arch_rsn_test")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["purge", "--strip-reasoning", "--project", "proj_1", "--archive-to", str(archive_dir), "--dry-run"],
    )
    assert result.exit_code == 0
    assert "Reasoning parts to strip" in result.output
    assert "Archive to" in result.output
    assert "/tmp/arch_rsn_test" in result.output


def test_export_cmd_older_than_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "opencode.db"
    conn = create_v2_db(db_file)
    conn.close()

    monkeypatch.setenv("OCGC_DB_PATH", str(db_file))
    monkeypatch.setenv("OCGC_SKIP_RUNNING_CHECK", "1")

    out_dir = tmp_path / "export_0d"
    runner = CliRunner()
    result = runner.invoke(cli, ["export", "--older-than", "0d", "-o", str(out_dir)])
    assert result.exit_code == 0
    assert "Please specify sessions to export" not in result.output

    # Test combined --session and --older-than 0d
    res_comb = runner.invoke(
        cli,
        ["export", "--session", "ses_v2_root", "--older-than", "0d", "-o", str(out_dir)],
    )
    assert res_comb.exit_code == 0


def test_v1_structured_parts_json_fallback(tmp_path: Path) -> None:
    db_file = tmp_path / "v1_patch.db"
    conn = create_v1_db(db_file)
    now = int(time.time() * 1000)
    # Insert part with patch type having no 'text' or 'content'
    conn.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
        (
            "part_patch_1",
            "msg_1",
            "ses_v1_root",
            now,
            now,
            json.dumps({"type": "patch", "files": {"main.py": "diff content"}}),
        ),
    )
    conn.commit()

    transcript = db.get_session_transcript(conn, "ses_v1_root", version=1)
    assert transcript is not None
    patch_part = next(p for p in transcript.messages[0].content_parts if p.type == "patch")
    assert "diff content" in patch_part.text
    conn.close()


def test_v2_user_content_no_text_attachment(tmp_path: Path) -> None:
    db_file = tmp_path / "v2_user_attach.db"
    conn = create_v2_db(db_file)
    now = int(time.time() * 1000)
    # Insert user message with content item without 'text'
    conn.execute(
        "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "msg_u_file",
            "ses_v2_root",
            "user",
            15,
            now,
            now,
            json.dumps({"content": [{"type": "file", "url": "https://example.com/image.png"}]}),
        ),
    )
    conn.commit()

    transcript = db.get_session_transcript(conn, "ses_v2_root", version=2)
    assert transcript is not None
    msg = next(m for m in transcript.messages if m.id == "msg_u_file")
    assert "https://example.com/image.png" in msg.content_parts[0].text
    conn.close()


def test_dangling_symlink_does_not_infinite_loop(tmp_path: Path) -> None:
    from ocgc.exporter import export_session_to_file

    out_file = tmp_path / "session_export.md"
    # Create dangling symlink
    dangling_target = tmp_path / "does_not_exist_at_all.md"
    try:
        out_file.symlink_to(dangling_target)
    except OSError:
        pytest.skip("Symlinks not supported on this platform/filesystem")

    transcript = db.SessionTranscript(
        id="ses_symlink_test",
        parent_id=None,
        title="Symlink Test",
        directory="/dir",
        project_id=None,
        time_created=1767225600000,
        time_updated=1767225600000,
        model=None,
        tokens=None,
        messages=[],
    )

    # Should not infinite loop and should resolve to session_export_1.md
    saved = export_session_to_file(transcript, output_path=out_file, overwrite=False)
    assert saved != out_file
    assert saved.exists()
    assert "_1.md" in saved.name
