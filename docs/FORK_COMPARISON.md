# 与上游的差异说明 (Differences from Upstream)

本文档记录本仓库相对上游 [whtsky/ocgc](https://github.com/whtsky/ocgc) 的具体差异。

本项目是 `whtsky/ocgc` 的增强分支(fork)。上游于 2026-04-15 后停止维护，仅支持 OpenCode v1 schema，且在非 Unix 环境下存在若干问题。OpenCode 升级到 **v2** 后数据库schema 完全重构（`session_v2`、`session_message`、内嵌JSON content 数组、多张关联表），导致上游无法工作。

主 README 关注「解决什么问题、怎么用」，差异对比这类信息放在这里，不干扰首次访问的阅读。

---

## 📊 功能对比矩阵

| 功能 / 能力 | 上游 (`whtsky/ocgc`) | 本仓库 (`codehands028/ocgc`) |
| :--- | :---: | :---: |
| **OpenCode v2 Schema 支持** | ❌ 失败 (`no such table: session`) | ✅ **完整支持** (`session_v2`, `session_message` 等) |
| **OpenCode v1 Schema 支持** | ✅ 支持 | ✅ **支持**（向后兼容） |
| **Schema 自动识别** | ❌ 无（硬编码 v1） | ✅ **自动**（动态识别 v1 / v2） |
| **v2 Part Type 存储分析** | ❌ 不支持 | ✅ **深度 SQLite JSON 解析**（`json_each` 数组提取） |
| **v2 级联 Session 清理** | ❌ 不支持 | ✅ **跨 9 张表原子级联**并带事务回滚 |
| **v2 Reasoning Token剥离** | ❌ 不支持 | ✅ **完整 JSON content 解析 + token 计数重置** |
| **原生 Windows 支持** | ⚠️ 存在缺陷（POSIX 路径、`pgrep`、快照权限错误） | ✅ **一等公民**（原生 AppData、`tasklist`、路径归一化） |
| **Windows 只读快照清理** | ❌ git packfile 上失败 (`AccessDenied`) | ✅ **安全 `_rmtree_safe`**，清除 `chmod S_IWRITE` 属性 |
| **Windows 进程检测** | ❌ 失败（找不到 `pgrep`） | ✅ **`tasklist` CSV 解析**（`opencode.exe`、`opencode-server.exe` 等） |
| **SQLite 只读 URI 处理** | ⚠️ 字符串拼接较脆弱 | ✅ **标准 `path.resolve().as_uri()`**，全平台一致 |
| **文件系统孤立diff 检测** | ⚠️ 仅 v1 | ✅ **v1 与 v2 schema 感知的孤立检测** |
| **工具输出缓存清理** | ❌ 无 | ✅ **原生**（`--clean-tool-output`，含时间过滤与安全检查） |
| **按项目 / 目录定向清理** | ❌ 无 | ✅ **原生**（`--project`、`--directory`，覆盖 `sessions` 与 `purge`） |
| **项目级存储大盘** | ❌ 无 | ✅ **原生**（`ocgc projects` 聚合 session、data 与 snapshot） |
| **轻量级 WAL 归并** | ❌ 无 | ✅ **毫秒级重置**（`ocgc checkpoint`，TRUNCATE 模式） |
| **超大内容 / 媒体裁剪** | ❌ 无 | ✅ **原生**（`--strip-large-outputs`，可配 `--threshold`） |
| **会话 Markdown 导出与归档** | ❌ 无 | ✅ **完整 GFM 导出**（`ocgc export`、`purge --archive-to`） |
| **数据库体检与诊断** | ❌ 无 | ✅ **`ocgc doctor`**（完整性、WAL 膨胀、悬空行、权限） |
| **结构化 JSON 输出** | ❌ 无 | ✅ **原生**（`status` / `sessions` / `analyze` / `projects` / `doctor`） |
| **OpenCode 原生 Skill 集成** | ❌ 无 | ✅ **内置**（`ocgc install-skill`） |
| **自动化测试覆盖** | ⚠️ 较少 | ✅ **111 个测试**，覆盖 v1 与 v2 端到端流程 |

---

## 🤝 致谢与共建

本项目由 [Wu Haotian (whtsky)](https://github.com/whtsky) 原创，感谢其搭建了OpenCode 存储管理的基础。

上游自 2026-04-15 起未再更新，其仓库中仍有若干未处理的 feature request 与 PR。本仓库在这些方向上的实现并非为了取代上游，而是因为 v2 schema 支持的缺失使得上游版本无法在当前 OpenCode 版本上运行。

如果这些改动对上游有价值，欢迎向上游仓库提交 PR 或 issue 讨论共建。相关差异与上游 issue 追踪：

- [上游 issue #3 — event 表感知（6 条讨论）](https://github.com/whtsky/ocgc/issues/3)
- [上游 issue #5 — DB 大小与 ocgc 统计不符](https://github.com/whtsky/ocgc/issues/5)

---

## 📄 License

MIT License. See [LICENSE](../LICENSE) for details.