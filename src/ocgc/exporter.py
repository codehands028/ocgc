"""Markdown export and archiving logic for OpenCode sessions."""

import contextlib
import html
import json
import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ocgc import db


@dataclass
class ExportResult:
    sessions_exported: int = 0
    bytes_written: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


def sanitize_filename(name: str, max_length: int = 50) -> str:
    """Sanitize string for cross-platform filesystem filenames (Windows/POSIX)."""
    if not name:
        return "untitled"

    # Replace forbidden path/name characters with underscores
    cleaned = re.sub(r'[\\/*?:"<>|\r\n\t：／＼＊？＂＜＞｜]', "_", name)
    # Replace whitespace sequences with single underscore
    cleaned = re.sub(r"\s+", "_", cleaned)
    # Remove leading/trailing dots and underscores
    cleaned = cleaned.strip(" ._-")

    if not cleaned:
        return "untitled"

    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(" ._-")

    return cleaned or "untitled"


def format_timestamp(ms: int) -> str:
    """Format millisecond epoch to human-readable string YYYY-MM-DD HH:MM:SS."""
    if ms <= 0:
        return "N/A"
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return str(ms)


def generate_export_filename(transcript: db.SessionTranscript) -> str:
    """Generate standardized filename: YYYY-MM-DD_<safe_title>_<id_short>.md."""
    date_str = "unknown_date"
    if transcript.time_created > 0:
        with contextlib.suppress(Exception):
            date_str = datetime.fromtimestamp(transcript.time_created / 1000).strftime("%Y-%m-%d")

    title_part = sanitize_filename(transcript.title or "session")
    # Take meaningful short slice of session ID
    sid_short = transcript.id[-8:] if len(transcript.id) >= 8 else transcript.id
    return f"{date_str}_{title_part}_{sid_short}.md"


def _markdown_fence(content: str, default_len: int = 3) -> str:
    """Calculate a code fence of backticks that is strictly longer than any backtick sequence in content."""
    matches = re.findall(r"`+", content)
    max_len = max((len(m) for m in matches), default=0)
    return "`" * max(default_len, max_len + 1)


def render_session_to_markdown(
    transcript: db.SessionTranscript,
    include_reasoning: bool = True,
) -> str:
    """Render full session transcript into GitHub-flavored Markdown."""
    lines: list[str] = []

    # Title & Metadata
    title = transcript.title or f"Session {transcript.id}"
    lines.append(f"# {title}\n")

    lines.append(f"> **Session ID:** `{transcript.id}`  ")
    lines.append(f"> **Directory:** `{transcript.directory}`  ")
    if transcript.project_id:
        lines.append(f"> **Project:** `{transcript.project_id}`  ")
    lines.append(f"> **Created:** `{format_timestamp(transcript.time_created)}`  ")
    lines.append(f"> **Updated:** `{format_timestamp(transcript.time_updated)}`  ")
    if transcript.model:
        lines.append(f"> **Model:** `{transcript.model}`  ")
    if transcript.tokens:
        tok = transcript.tokens
        in_t = tok.get("input", 0)
        out_t = tok.get("output", 0)
        rsn_t = tok.get("reasoning", 0)
        lines.append(f"> **Tokens:** Input: {in_t:,} | Output: {out_t:,} | Reasoning: {rsn_t:,}  ")

    lines.append("\n---\n")

    # Messages
    for msg in transcript.messages:
        role = msg.role.lower()
        if role == "user":
            header = "## 👤 User"
        elif role == "assistant":
            header = "## 🤖 Assistant"
        elif role == "system":
            header = "## ⚙️ System"
        else:
            header = f"## 💬 {msg.role.capitalize()}"

        lines.append(header)
        lines.append("")

        files_attached: list[str] = []

        for part in msg.content_parts:
            if part.type == "text" and part.text:
                lines.append(part.text)
                lines.append("")
            elif part.type == "file":
                files_attached.append(part.text or "file")
            elif part.type == "reasoning":
                if include_reasoning and part.text and part.text.strip():
                    lines.append("<details>")
                    lines.append("<summary>💭 思考过程 (Reasoning)</summary>\n")
                    lines.append(part.text.strip())
                    lines.append("\n</details>\n")
            elif part.type == "tool":
                tool_name = html.escape(part.tool_name or "tool")
                status = html.escape(part.tool_status or "completed")
                lines.append("<details>")
                lines.append(f"<summary>🛠️ 工具调用: <code>{tool_name}</code> ({status})</summary>\n")

                if part.tool_input is not None:
                    lines.append("**输入 (Input):**")
                    if isinstance(part.tool_input, (dict, list)):
                        input_json = json.dumps(part.tool_input, ensure_ascii=False, indent=2)
                        fence = _markdown_fence(input_json)
                        lines.append(f"{fence}json\n{input_json}\n{fence}")
                    else:
                        input_str = str(part.tool_input)
                        fence = _markdown_fence(input_str)
                        lines.append(f"{fence}\n{input_str}\n{fence}")
                    lines.append("")

                if part.tool_output is not None:
                    lines.append("**输出 (Output):**")
                    fence = _markdown_fence(part.tool_output)
                    lines.append(f"{fence}text\n{part.tool_output}\n{fence}")
                    lines.append("")

                lines.append("</details>\n")
            elif part.text:
                lines.append(part.text)
                lines.append("")

        if files_attached:
            lines.append("**附件/上下文 (Attachments):**")
            for f in files_attached:
                lines.append(f"- `{f}`")
            lines.append("")

        lines.append("---\n")

    return "\n".join(lines).strip() + "\n"


def _path_exists(p: Path) -> bool:
    """Check if file or symlink (even dangling) exists on filesystem."""
    return os.path.lexists(str(p))


def _find_available_path(base_file: Path) -> Path:
    if not _path_exists(base_file):
        return base_file
    stem = base_file.stem
    suffix = base_file.suffix or ".md"
    parent = base_file.parent
    counter = 1
    while _path_exists(parent / f"{stem}_{counter}{suffix}"):
        counter += 1
    return parent / f"{stem}_{counter}{suffix}"


def export_session_to_file(
    transcript: db.SessionTranscript,
    output_path: Path,
    include_reasoning: bool = True,
    overwrite: bool = False,
) -> Path:
    """Export single session to file. Auto-generates filename if output_path is directory."""
    if output_path.is_dir() or not output_path.suffix:
        output_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        filename = generate_export_filename(transcript)
        target_file = output_path / filename
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target_file = output_path

    if not overwrite:
        target_file = _find_available_path(target_file)

    content = render_session_to_markdown(transcript, include_reasoning=include_reasoning)

    # Atomic write: write to secure temporary file in the same directory, then rename atomically
    parent_dir = target_file.parent
    tmp_fd, tmp_name = tempfile.mkstemp(dir=str(parent_dir), prefix=f".{target_file.name}.", suffix=".part")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        with contextlib.suppress(OSError):
            os.chmod(tmp_name, 0o600)

        if not overwrite:
            while True:
                try:
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                    if hasattr(os, "O_NOFOLLOW"):
                        flags |= os.O_NOFOLLOW
                    fd = os.open(target_file, flags, 0o600)
                    os.close(fd)
                    break
                except FileExistsError:
                    target_file = _find_available_path(target_file)

        os.replace(tmp_name, target_file)
        with contextlib.suppress(OSError):
            os.chmod(target_file, 0o600)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise

    return target_file


def archive_session_diffs(
    session_ids: list[str],
    archive_dir: Path,
    diff_dir: Path | None = None,
) -> tuple[int, list[str]]:
    """Archive matching session diff JSON files to archive_dir/diffs/.

    Returns:
        (diff_copied, diff_failed)
    """
    if diff_dir is None:
        diff_dir = db.get_storage_dir() / "storage" / "session_diff"

    diff_copied = 0
    diff_failed: list[str] = []
    if not diff_dir.is_dir() or not session_ids:
        return diff_copied, diff_failed

    diff_archive_dir = archive_dir / "diffs"
    try:
        diff_archive_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as e:
        diff_failed.append(f"mkdir: {e}")
        return diff_copied, diff_failed

    diff_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        diff_flags |= os.O_NOFOLLOW

    for sid in session_ids:
        src_diff = diff_dir / f"{sid}.json"
        if not src_diff.exists():
            continue
        dst_diff = _find_available_path(diff_archive_dir / f"{sid}.json")
        try:
            fd = os.open(dst_diff, diff_flags, 0o600)
            with os.fdopen(fd, "wb") as f_dst, src_diff.open("rb") as f_src:
                shutil.copyfileobj(f_src, f_dst)
            diff_copied += 1
        except OSError as e:
            diff_failed.append(f"{sid}: {e}")

    return diff_copied, diff_failed


def export_sessions(
    session_ids: list[str],
    output_dir: Path,
    include_reasoning: bool = True,
    overwrite: bool = False,
    conn: sqlite3.Connection | None = None,
) -> ExportResult:
    """Batch export multiple sessions to Markdown in target output directory."""
    result = ExportResult()
    if not session_ids:
        return result

    close_conn = False
    db_conn = conn
    if db_conn is None:
        db_conn = db.connect(readonly=True)
        close_conn = True

    try:
        version = db.detect_version(db_conn)
        output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

        for sid in session_ids:
            try:
                transcript = db.get_session_transcript(db_conn, sid, version=version)
                if not transcript:
                    result.errors.append((sid, "Session not found in database"))
                    continue

                saved_path = export_session_to_file(
                    transcript,
                    output_path=output_dir,
                    include_reasoning=include_reasoning,
                    overwrite=overwrite,
                )
                file_size = saved_path.stat().st_size
                result.sessions_exported += 1
                result.bytes_written += file_size
            except Exception as e:
                result.errors.append((sid, str(e)))
    finally:
        if close_conn:
            with contextlib.suppress(Exception):
                db_conn.close()

    return result
