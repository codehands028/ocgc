"""一键优化安全策略引擎 (One-click storage optimization presets)."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from ocgc import db
from ocgc.display import (
    console,
    print_auto_plan,
    print_auto_result,
    warn_opencode_running,
)
from ocgc.units import format_bytes


@dataclass
class OptimizationStepPlan:
    """单个优化步骤的预估计划数据。"""

    step_id: str
    name: str
    items_count: int
    estimated_bytes: int
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return {
            "step_id": self.step_id,
            "name": self.name,
            "items_count": self.items_count,
            "estimated_bytes": self.estimated_bytes,
            "detail": self.detail,
        }


@dataclass
class OptimizationPlan:
    """优化整体计划数据模型。"""

    preset: str
    db_path: str
    db_version: int
    estimated_total_bytes: int
    steps: list[OptimizationStepPlan]

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return {
            "preset": self.preset,
            "db_path": self.db_path,
            "db_version": self.db_version,
            "estimated_total_bytes": self.estimated_total_bytes,
            "steps": [s.to_dict() for s in self.steps],
        }


@dataclass
class OptimizationStepResult:
    """单个优化步骤的执行结果数据。"""

    step_id: str
    name: str
    items_affected: int
    bytes_reclaimed: int
    status: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return {
            "step_id": self.step_id,
            "name": self.name,
            "items_affected": self.items_affected,
            "bytes_reclaimed": self.bytes_reclaimed,
            "status": self.status,
            "message": self.message,
        }


@dataclass
class OptimizationResult:
    """优化整体执行结果数据模型。"""

    preset: str
    dry_run: bool
    db_path: str
    db_version: int
    total_bytes_reclaimed: int
    steps: list[OptimizationStepResult]

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return {
            "preset": self.preset,
            "dry_run": self.dry_run,
            "db_path": self.db_path,
            "db_version": self.db_version,
            "total_bytes_reclaimed": self.total_bytes_reclaimed,
            "steps": [s.to_dict() for s in self.steps],
        }


def plan_optimization(preset: str, db_path: Path | None = None) -> OptimizationPlan:
    """生成一键优化的预估计划（只读分析，不产生写入）。"""
    norm_preset = preset.lower().strip()
    if norm_preset not in ("safe", "aggressive"):
        raise ValueError(f"Unknown preset: {preset!r}. Must be 'safe' or 'aggressive'.")

    target_db = db_path if db_path is not None else db.get_db_path()
    if not target_db.exists():
        raise FileNotFoundError(f"OpenCode database not found at {target_db}")

    storage_dir = target_db.parent
    conn = db.connect(readonly=True, path=target_db)
    try:
        version = db.detect_version(conn)
        now_ms = int(time.time() * 1000)
        steps: list[OptimizationStepPlan] = []

        if norm_preset == "safe":
            # 步骤 1: 孤立 diff 文件清理预估
            orphans = db.get_orphan_session_diffs(conn, version=version, storage_dir=storage_dir)
            orphan_count = len(orphans)
            orphan_bytes = sum(o.size for o in orphans)
            steps.append(
                OptimizationStepPlan(
                    step_id="clean_orphans",
                    name="Clean orphan diff files",
                    items_count=orphan_count,
                    estimated_bytes=orphan_bytes,
                    detail=f"{orphan_count} orphan file(s)",
                )
            )

            # 步骤 2: 工具输出临时文件清理预估
            tool_files = db.get_tool_output_files(storage_dir=storage_dir)
            tool_count = len(tool_files)
            tool_bytes = sum(f.size for f in tool_files)
            steps.append(
                OptimizationStepPlan(
                    step_id="clean_tool_output",
                    name="Clean cached tool output files",
                    items_count=tool_count,
                    estimated_bytes=tool_bytes,
                    detail=f"{tool_count} cached tool file(s)",
                )
            )

            # 步骤 3: 剥离 14 天前旧会话的 Reasoning 预估（逻辑数据裁剪，不直接缩小 DB 文件）
            cutoff_14d_ms = 14 * 86400 * 1000
            sids_14d = db.get_session_ids_for_purge(
                conn, older_than_ms=cutoff_14d_ms, now_ms=now_ms, version=version
            )
            if sids_14d:
                rs_summary = db.get_reasoning_summary(conn, session_ids=sids_14d, version=version)
                rs_parts = rs_summary["part_count"]
                rs_bytes = rs_summary["total_bytes"]
            else:
                rs_parts = 0
                rs_bytes = 0
            steps.append(
                OptimizationStepPlan(
                    step_id="strip_reasoning",
                    name="Strip reasoning from sessions older than 14d",
                    items_count=rs_parts,
                    estimated_bytes=rs_bytes,
                    detail=f"{rs_parts} part(s) across {len(sids_14d)} session(s)",
                )
            )

            # 步骤 4: WAL 检查点 (TRUNCATE) 预估
            wal_path = Path(str(target_db) + "-wal")
            wal_bytes = wal_path.stat().st_size if wal_path.exists() else 0
            steps.append(
                OptimizationStepPlan(
                    step_id="checkpoint",
                    name="Flush and reset WAL log (TRUNCATE)",
                    items_count=1 if wal_bytes > 0 else 0,
                    estimated_bytes=wal_bytes,
                    detail=f"Current WAL size: {format_bytes(wal_bytes)}",
                )
            )

            # Safe 模式物理磁盘回收量 = 孤立 diff + 工具输出 + WAL 截断
            total_physical_bytes = orphan_bytes + tool_bytes + wal_bytes

        else:
            # 模式: aggressive
            # 步骤 1: 清理 30 天以前会话预估
            cutoff_30d_ms = 30 * 86400 * 1000
            sids_30d = db.get_session_ids_for_purge(
                conn, older_than_ms=cutoff_30d_ms, now_ms=now_ms, version=version
            )
            diff_dir = storage_dir / "storage" / "session_diff"
            diff_bytes = 0
            if diff_dir.is_dir() and sids_30d:
                for sid in sids_30d:
                    p = diff_dir / f"{sid}.json"
                    if p.exists():
                        diff_bytes += p.stat().st_size

            if sids_30d:
                ps_summary = db.get_purge_summary(conn, sids_30d, version=version)
                session_logical_bytes = ps_summary["total_bytes"]
            else:
                session_logical_bytes = 0

            steps.append(
                OptimizationStepPlan(
                    step_id="purge_sessions",
                    name="Delete sessions older than 30d",
                    items_count=len(sids_30d),
                    estimated_bytes=diff_bytes,
                    detail=f"{len(sids_30d)} session(s) (>30d, {format_bytes(session_logical_bytes)} DB data)",
                )
            )

            # 步骤 2: 清理全部 Git 快照预估
            snapshots = db.get_snapshot_projects(conn=conn, storage_dir=storage_dir)
            snap_count = len(snapshots)
            snap_bytes = sum(size for _, size in snapshots)
            steps.append(
                OptimizationStepPlan(
                    step_id="clean_snapshots",
                    name="Delete all git snapshots",
                    items_count=snap_count,
                    estimated_bytes=snap_bytes,
                    detail=f"{snap_count} snapshot project(s)",
                )
            )

            # 步骤 3: 剥离剩余会话 Reasoning 预估
            all_rs = db.get_reasoning_summary(conn, session_ids=None, version=version)
            sids_30d_rs = (
                db.get_reasoning_summary(conn, session_ids=sids_30d, version=version)
                if sids_30d
                else {"part_count": 0, "total_bytes": 0}
            )
            rem_parts = max(0, all_rs["part_count"] - sids_30d_rs["part_count"])
            rem_bytes = max(0, all_rs["total_bytes"] - sids_30d_rs["total_bytes"])
            steps.append(
                OptimizationStepPlan(
                    step_id="strip_reasoning",
                    name="Strip reasoning from remaining sessions",
                    items_count=rem_parts,
                    estimated_bytes=rem_bytes,
                    detail=f"{rem_parts} remaining reasoning part(s)",
                )
            )

            # 步骤 4: VACUUM 释放空闲页面预估（回收前序删除产生的空闲空间）
            db_size = target_db.stat().st_size if target_db.exists() else 0
            estimated_vac_bytes = min(db_size, session_logical_bytes + rem_bytes)
            steps.append(
                OptimizationStepPlan(
                    step_id="vacuum",
                    name="Run VACUUM to defragment and reclaim database pages",
                    items_count=1,
                    estimated_bytes=estimated_vac_bytes,
                    detail=f"Current DB size: {format_bytes(db_size)}",
                )
            )

            # Aggressive 模式物理磁盘回收量 = diff 文件 + 快照 + VACUUM 释放页面
            total_physical_bytes = diff_bytes + snap_bytes + estimated_vac_bytes

        return OptimizationPlan(
            preset=norm_preset,
            db_path=str(target_db),
            db_version=version,
            estimated_total_bytes=total_physical_bytes,
            steps=steps,
        )
    finally:
        conn.close()


def execute_optimization(plan: OptimizationPlan, db_path: Path | None = None) -> OptimizationResult:
    """按照生成的计划执行一键优化操作。"""
    norm_preset = plan.preset.lower().strip()
    if norm_preset not in ("safe", "aggressive"):
        raise ValueError(f"Unknown preset: {plan.preset!r}. Must be 'safe' or 'aggressive'.")

    target_db = db_path if db_path is not None else Path(plan.db_path)
    storage_dir = target_db.parent
    now_ms = int(time.time() * 1000)
    results: list[OptimizationStepResult] = []

    if norm_preset == "safe":
        # Safe 策略依次执行
        conn = db.connect(readonly=False, path=target_db)
        try:
            # 步骤 1: 清理孤立 diff
            orphans = db.get_orphan_session_diffs(conn, version=plan.db_version, storage_dir=storage_dir)
            if orphans:
                orphan_res = db.purge_orphan_diffs(orphans)
                results.append(
                    OptimizationStepResult(
                        step_id="clean_orphans",
                        name="Clean orphan diff files",
                        items_affected=orphan_res.files_deleted,
                        bytes_reclaimed=orphan_res.bytes_freed,
                        status="ok",
                        message=f"Deleted {orphan_res.files_deleted} orphan diff file(s)",
                    )
                )
            else:
                results.append(
                    OptimizationStepResult(
                        step_id="clean_orphans",
                        name="Clean orphan diff files",
                        items_affected=0,
                        bytes_reclaimed=0,
                        status="skipped",
                        message="No orphan diff files found",
                    )
                )

            # 步骤 2: 清理工具输出缓存文件
            tool_files = db.get_tool_output_files(storage_dir=storage_dir)
            if tool_files:
                tool_res = db.purge_tool_outputs(tool_files)
                results.append(
                    OptimizationStepResult(
                        step_id="clean_tool_output",
                        name="Clean cached tool output files",
                        items_affected=tool_res.files_deleted,
                        bytes_reclaimed=tool_res.bytes_freed,
                        status="ok",
                        message=f"Deleted {tool_res.files_deleted} tool output file(s)",
                    )
                )
            else:
                results.append(
                    OptimizationStepResult(
                        step_id="clean_tool_output",
                        name="Clean cached tool output files",
                        items_affected=0,
                        bytes_reclaimed=0,
                        status="skipped",
                        message="No tool output files found",
                    )
                )

            # 步骤 3: 剥离 14 天前旧会话的 Reasoning
            cutoff_14d_ms = 14 * 86400 * 1000
            sids_14d = db.get_session_ids_for_purge(
                conn, older_than_ms=cutoff_14d_ms, now_ms=now_ms, version=plan.db_version
            )
            if sids_14d:
                rs_summary = db.get_reasoning_summary(conn, session_ids=sids_14d, version=plan.db_version)
                if rs_summary["part_count"] > 0:
                    stripped_count = db.strip_reasoning(conn, session_ids=sids_14d, version=plan.db_version)
                    results.append(
                        OptimizationStepResult(
                            step_id="strip_reasoning",
                            name="Strip reasoning from sessions older than 14d",
                            items_affected=stripped_count,
                            bytes_reclaimed=rs_summary["total_bytes"],
                            status="ok",
                            message=f"Deleted {stripped_count} reasoning part(s)",
                        )
                    )
                else:
                    results.append(
                        OptimizationStepResult(
                            step_id="strip_reasoning",
                            name="Strip reasoning from sessions older than 14d",
                            items_affected=0,
                            bytes_reclaimed=0,
                            status="skipped",
                            message="No reasoning parts in older sessions",
                        )
                    )
            else:
                results.append(
                    OptimizationStepResult(
                        step_id="strip_reasoning",
                        name="Strip reasoning from sessions older than 14d",
                        items_affected=0,
                        bytes_reclaimed=0,
                        status="skipped",
                        message="No sessions older than 14d",
                    )
                )
        finally:
            # 必须在 checkpoint 前关闭写连接，防止 SQLite 锁冲突
            conn.close()

        # 步骤 4: 执行 WAL checkpoint (TRUNCATE)
        try:
            cp_result = db.checkpoint_db(mode="TRUNCATE", path=target_db)
            status = "ok" if cp_result.busy == 0 else "warn"
            msg = (
                f"Reset WAL to 0 B (freed {format_bytes(cp_result.wal_saved)})"
                if cp_result.busy == 0
                else "WAL checkpoint busy"
            )
            results.append(
                OptimizationStepResult(
                    step_id="checkpoint",
                    name="Flush and reset WAL log (TRUNCATE)",
                    items_affected=1 if cp_result.wal_saved > 0 else 0,
                    bytes_reclaimed=cp_result.wal_saved,
                    status=status,
                    message=msg,
                )
            )
        except sqlite3.Error as e:
            results.append(
                OptimizationStepResult(
                    step_id="checkpoint",
                    name="Flush and reset WAL log (TRUNCATE)",
                    items_affected=0,
                    bytes_reclaimed=0,
                    status="error",
                    message=f"Checkpoint failed: {e}",
                )
            )

        # Safe 模式实际物理回收量：文件清理 + WAL 截断
        physical_reclaimed = sum(
            r.bytes_reclaimed
            for r in results
            if r.step_id in ("clean_orphans", "clean_tool_output", "checkpoint")
        )

    else:
        # Aggressive 策略依次执行
        conn = db.connect(readonly=False, path=target_db)
        try:
            # 步骤 1: 清理 30 天以前会话
            cutoff_30d_ms = 30 * 86400 * 1000
            sids_30d = db.get_session_ids_for_purge(
                conn, older_than_ms=cutoff_30d_ms, now_ms=now_ms, version=plan.db_version
            )
            if sids_30d:
                ps_summary = db.get_purge_summary(conn, sids_30d, version=plan.db_version)
                purge_files_res = db.purge_sessions(conn, sids_30d, version=plan.db_version)
                msg = f"Deleted {len(sids_30d)} session(s) ({format_bytes(ps_summary['total_bytes'])} logical data)"
                results.append(
                    OptimizationStepResult(
                        step_id="purge_sessions",
                        name="Delete sessions older than 30d",
                        items_affected=len(sids_30d),
                        bytes_reclaimed=purge_files_res.bytes_freed,
                        status="ok",
                        message=msg,
                    )
                )
            else:
                results.append(
                    OptimizationStepResult(
                        step_id="purge_sessions",
                        name="Delete sessions older than 30d",
                        items_affected=0,
                        bytes_reclaimed=0,
                        status="skipped",
                        message="No sessions older than 30d",
                    )
                )

            # 步骤 2: 清理全部 Git 快照
            snapshots = db.get_snapshot_projects(conn=conn, storage_dir=storage_dir)
            if snapshots:
                snap_res = db.purge_snapshots(names=[name for name, _ in snapshots], storage_dir=storage_dir)
                results.append(
                    OptimizationStepResult(
                        step_id="clean_snapshots",
                        name="Delete all git snapshots",
                        items_affected=snap_res.files_deleted,
                        bytes_reclaimed=snap_res.bytes_freed,
                        status="ok",
                        message=f"Deleted {snap_res.files_deleted} snapshot dir(s)",
                    )
                )
            else:
                results.append(
                    OptimizationStepResult(
                        step_id="clean_snapshots",
                        name="Delete all git snapshots",
                        items_affected=0,
                        bytes_reclaimed=0,
                        status="skipped",
                        message="No snapshot directories found",
                    )
                )

            # 步骤 3: 剥离剩余会话 Reasoning
            rs_summary = db.get_reasoning_summary(conn, session_ids=None, version=plan.db_version)
            if rs_summary["part_count"] > 0:
                count = db.strip_reasoning(conn, session_ids=None, version=plan.db_version)
                results.append(
                    OptimizationStepResult(
                        step_id="strip_reasoning",
                        name="Strip reasoning from remaining sessions",
                        items_affected=count,
                        bytes_reclaimed=rs_summary["total_bytes"],
                        status="ok",
                        message=f"Deleted {count} reasoning part(s)",
                    )
                )
            else:
                results.append(
                    OptimizationStepResult(
                        step_id="strip_reasoning",
                        name="Strip reasoning from remaining sessions",
                        items_affected=0,
                        bytes_reclaimed=0,
                        status="skipped",
                        message="No reasoning parts found",
                    )
                )
        finally:
            # 必须在 vacuum 前关闭连接，以获取独占排他锁
            conn.close()

        # 步骤 4: 执行 VACUUM
        try:
            before, after = db.vacuum_db(path=target_db)
            vac_freed = max(0, before - after)
            results.append(
                OptimizationStepResult(
                    step_id="vacuum",
                    name="Run VACUUM to defragment database",
                    items_affected=1 if vac_freed > 0 else 0,
                    bytes_reclaimed=vac_freed,
                    status="ok",
                    message=f"Reclaimed {format_bytes(vac_freed)}",
                )
            )
        except sqlite3.Error as e:
            results.append(
                OptimizationStepResult(
                    step_id="vacuum",
                    name="Run VACUUM to defragment database",
                    items_affected=0,
                    bytes_reclaimed=0,
                    status="error",
                    message=f"VACUUM failed: {e}",
                )
            )

        # Aggressive 模式物理回收量：外部 diff 文件 + 快照 + VACUUM 实际缩减大小
        physical_reclaimed = sum(
            r.bytes_reclaimed
            for r in results
            if r.step_id in ("purge_sessions", "clean_snapshots", "vacuum")
        )

    return OptimizationResult(
        preset=norm_preset,
        dry_run=False,
        db_path=str(target_db),
        db_version=plan.db_version,
        total_bytes_reclaimed=physical_reclaimed,
        steps=results,
    )


def run_auto(
    preset: str = "safe",
    dry_run: bool = False,
    force: bool = False,
    json_output: bool = False,
    db_path: Path | None = None,
) -> OptimizationResult | None:
    """CLI 入口：编排一键优化安全策略的检查、交互确认与执行流程。"""
    norm_preset = preset.lower().strip()
    if norm_preset not in ("safe", "aggressive"):
        raise click.BadParameter(
            f"Unknown preset {preset!r}. Must be 'safe' or 'aggressive'.",
            param_hint="'--preset'",
        )

    opencode_running = db.check_opencode_running()
    if opencode_running:
        if not json_output:
            warn_opencode_running()
        if not dry_run and not force:
            if json_output:
                click.echo(
                    json.dumps(
                        {"error": "OpenCode is currently running. Pass --force to proceed.", "success": False},
                        indent=2,
                        ensure_ascii=False,
                    )
                )
                raise SystemExit(1)
            if not click.confirm("OpenCode is running. Continue anyway?"):
                return None

    try:
        plan = plan_optimization(preset=norm_preset, db_path=db_path)
    except FileNotFoundError as e:
        if json_output:
            click.echo(json.dumps({"error": str(e), "success": False}, indent=2, ensure_ascii=False))
        else:
            click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None
    except RuntimeError as e:
        if json_output:
            click.echo(json.dumps({"error": str(e), "success": False}, indent=2, ensure_ascii=False))
        else:
            click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None

    if dry_run:
        if json_output:
            click.echo(json.dumps(plan.to_dict(), indent=2, ensure_ascii=False))
        else:
            print_auto_plan(plan, dry_run=True)
        return None

    if not force:
        if json_output:
            raise click.UsageError("--json without --dry-run requires --force for non-interactive execution.")
        print_auto_plan(plan, dry_run=False)
        prompt = f"Apply {norm_preset.upper()} optimization plan?"
        if not click.confirm(prompt):
            console.print("[dim]Optimization aborted.[/]")
            return None

    with console.status(f"[bold cyan]Applying {norm_preset.upper()} optimization policy...[/]"):
        try:
            result = execute_optimization(plan, db_path=db_path)
        except Exception as e:
            if json_output:
                click.echo(
                    json.dumps(
                        {"error": f"Optimization execution failed: {e}", "success": False},
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            else:
                console.print(f"[red]Optimization failed:[/] {e}")
            raise SystemExit(1) from None

    if json_output:
        click.echo(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print_auto_result(result)

    # 若任一步骤发生失败，非零码退出以保障 CI 与自动化感知
    if any(s.status == "error" for s in result.steps):
        raise SystemExit(1)

    return result
