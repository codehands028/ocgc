# ocgc: OpenCode 存储空间深度分析与垃圾回收工具

[ [English](README.md) | **简体中文** ]

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](pyproject.toml)
[![OpenCode v1 & v2](https://img.shields.io/badge/OpenCode-v1%20%7C%20v2-green.svg)](https://github.com/anomalyco/opencode)
[![OpenCode Skill](https://img.shields.io/badge/OpenCode-Skill%20Ready-purple.svg)](skills/ocgc/SKILL.md)
[![skills.sh](https://skills.sh/b/codehands028/ocgc)](https://skills.sh/codehands028/ocgc)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](https://github.com/codehands028/ocgc)
[![CI](https://github.com/codehands028/ocgc/actions/workflows/ci.yml/badge.svg)](https://github.com/codehands028/ocgc/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-126%20passed-brightgreen.svg)](tests/)

**ocgc** 是一款专为 [OpenCode](https://github.com/anomalyco/opencode) 设计的存储深度分析与智能垃圾回收工具。全面原生支持 **OpenCode v1 与 v2** 架构，完美跨 **Windows、macOS 与 Linux** 全平台。

OpenCode 将会话（Sessions）、消息（Messages）以及具体内容部件（Parts）保存在本地 SQLite 数据库中，随着使用会不断膨胀且[没有内置清理机制](https://github.com/anomalyco/opencode/issues/4980)。此外，OpenCode 还会将完整的文件修改差异（session_diff）与 Git 快照（snapshot）持久化到磁盘上。思考过程（reasoning tokens）、快照和历史会话会持续累积，具体占用比例因使用习惯而异。

`ocgc` 能够直观可视化存储分布，并提供安全、细粒度的清理策略帮您彻底收回磁盘空间。

---

> **关于 v1 → v2 架构断裂：** 本项目最初源自 [whtsky/ocgc](https://github.com/whtsky/ocgc) 的分支（Fork）。原项目仅支持 OpenCode v1 数据库结构，在当前 OpenCode 版本上已无法运行。`ocgc` 同时兼容 v1 与 v2 两种架构，并会在运行时自动识别当前使用的架构。完整的能力差异对比请见 [docs/FORK_COMPARISON.md](docs/FORK_COMPARISON.md)。

---

## 📸 运行效果截图

### 存储仪表盘看板 (`ocgc status`)
显示数据库体积、WAL 日志、文件系统差异/快照体积，以及色彩丰富的部件类型占比图表：

![status](screenshots/status.png)

### 深度存储分析报告 (`ocgc analyze`)
最大会话 Top 10、主会话 vs 子代理（Subagent）空间对比、日均增长率以及孤立文件扫描：

![analyze](screenshots/analyze.png)

### 安全演练预览 (`ocgc purge --dry-run`)
清理前的详细预演，清晰列出会话、消息、部件和文件差异的预计释放空间：

![purge](screenshots/purge.png)

---

## 🚀 快速上手：OpenCode 原生技能

`ocgc` 内置了开箱即用的 OpenCode 原生技能（Skill），符合标准 Agent Skills 规范。安装后，您的 OpenCode 助手即可自主分析、预览并安全清理本地存储。

### 方式 1：纯 Python / uvx 原生一键安装（强烈推荐）

直接通过 `uvx` 运行，无需额外安装 npm，也无需克隆仓库：

```bash
# 全局安装至 OpenCode 技能目录 (~/.agents/skills/ocgc)
uvx --from git+https://github.com/codehands028/ocgc.git ocgc install-skill
```

*(如需仅安装到当前项目工作区，可追加 `--workspace` 参数)*。

### 方式 2：通过 `skills.sh` 通用包管理器安装

如果您习惯使用 [skills.sh](https://skills.sh) 生态：

```bash
npx skills add codehands028/ocgc
```

---

### 💬 在 OpenCode 中直接用自然语言吩咐

安装完成后，在与 OpenCode 对话时，直接用日常自然语言交流即可：

- *“帮我检查一下 OpenCode 的磁盘占用情况，并按大小分析前 10 个最大的会话”*
- *“安全演练并清理 30 天前的旧会话，看看能释放多少空间”*
- *“剥离历史会话中的思考过程（Reasoning Tokens），保留文本记录”*
- *“执行 VACUUM 紧凑化收缩数据库”*

OpenCode 将自动严格遵循安全规范（status 状态诊断 $\rightarrow$ dry-run 演练预览 $\rightarrow$ 确认后再执行清理 $\rightarrow$ vacuum 收缩）。

### 直接作为 Prompt 发送给 OpenCode
如果您暂未安装 Skill 文件，也可以直接在 OpenCode 聊天框中发送以下 Prompt：

```
请阅读 https://raw.githubusercontent.com/codehands028/ocgc/refs/heads/main/README_CN.md 并帮我分析与清理 OpenCode 的存储空间。
```

---

## 📦 安装方式

### 推荐方式（通过 uv）

无需安装直接运行（即用即走，类似于 npx）：

```bash
uvx --from git+https://github.com/codehands028/ocgc.git ocgc status
```

作为全局工具安装：

```bash
uv tool install git+https://github.com/codehands028/ocgc.git
```

### 通过 pipx 安装

```bash
pipx install git+https://github.com/codehands028/ocgc.git
```

### 通过 pip 安装

```bash
pip install git+https://github.com/codehands028/ocgc.git
```

---

## 🔍 核心功能与使用指南

### 1. 存储状态透视与深度分析

#### 全局健康看板
```bash
ocgc status

# 输出结构化 JSON（供脚本 / CI 流水线 / Agent 解析）
ocgc status --json
```
展示内容包括：
- 数据库实际路径及检测出的架构版本（**OpenCode v1** 或 **OpenCode v2**）
- SQLite 数据库大小、WAL 日志大小及数据库总占用
- 文件系统存储大小：Session Diffs、Snapshot 项目快照、工具输出缓存
- 主会话（Root）与子代理（Subagent）数量统计
- **按部件类型统计的柱状图**：直观展示思考过程（`reasoning`）、工具调用（`tool`）、用户与助手文本（`text`）、代码补丁（`patch`）等所占比例
- **会话时间分布图**：按活跃时间区间（<24h, 1-7d, 7-14d, 14-30d, >30d）展示会话留存

#### 会话浏览器
```bash
# 查看体积最大的 20 个会话（默认按大小降序）
ocgc sessions --limit 20

# 按项目名称或 ID 过滤查看会话
ocgc sessions --project my-app

# 按工作目录路径或通配符过滤会话
ocgc sessions --directory ~/Projects/legacy-repo
ocgc sessions --directory "*test*"

# 按创建时间或名称排序
ocgc sessions --sort age --limit 20
ocgc sessions --sort name

# 输出结构化 JSON
ocgc sessions --limit 10 --json
```
表格清晰列出各会话的 ID、工作目录、标题、体积、创建时长、类型（`root` 主会话或 `sub` 子代理）及消息总数。

#### 交互式终端选择器 (`browse`)
```bash
# 启动交互式终端选择器
ocgc browse

# 按项目过滤并按创建时间排序
ocgc browse --project my-app --sort age
```
键盘快捷操作：
- `↑ / ↓ / j / k`：上下移动光标
- `PageUp / PageDown`：向上 / 向下翻页
- `d`：标记当前高亮会话待物理删除 `[D]`（再按取消）
- `r`：标记当前高亮会话待剥离思考过程 `[R]`（再按取消）
- `Space / u`：清除当前会话标记
- `a`：全选 / 清空切换
- `Enter`：提交所选操作，弹出预览清单与 `[y/N]` 二次确认
- `?`：切换按键帮助说明面板
- `q / Esc`：直接退出，不做任何修改

#### 深度存储分析
```bash
ocgc analyze

# 输出结构化 JSON
ocgc analyze --json
```
深入洞察：
- 全局体积最大的 10 个会话排行
- 平均每个会话占用的存储空间
- **预估增长速度**：每个活跃使用日的平均新增存储（MB/active day）
- **主会话 vs 子代理消耗对比**：详细对比主会话与后台子代理各占用了多少消息和字节
- **孤立文件扫描**：精确找出磁盘中存在但数据库中对应记录已被删除的无效 diff 冗余文件

#### 项目级存储大盘
```bash
# 按占用空间降序展示各项目/工作区
ocgc projects

# 按会话数量排序
ocgc projects --sort sessions

# 仅展示占用最大的 10 个项目，并输出结构化 JSON
ocgc projects --limit 10
ocgc projects --json
```
以项目/工作区为单位聚合，一眼看清各个 Git 仓库的空间占用排行：
- **Sessions**：该项目下的会话总数（含主会话与子代理）
- **Data Size**：数据库中消息 / 部件数据的实际占用
- **Snapshots**：归属该项目的 Git 快照目录占用
- **Total**：数据 + 快照的合计磁盘占用（`--sort size` 即按此排序）
- **Last Active**：该项目最后一次活跃时间

---

### 2. 细粒度智能垃圾清理 (`ocgc purge`)

`ocgc purge` 支持多样化的组合过滤条件，多个过滤条件默认按 **AND** 逻辑组合生效。

> 💡 **安全优先机制**：默认情况下，`ocgc purge` 会先弹出本次变动的详细摘要信息并要求确认。执行前推荐使用 `--dry-run` 进行完全无副作用的预览。

#### 预览演练（Dry-run）
```bash
# 模拟预览清理 14 天前的所有旧会话，不进行真实删除
ocgc purge --older-than 14d --dry-run
```

#### 剥离思考过程（往往是收益最大的空间节省项💥）
深度思考模型（Claude Sonnet Thinking、o 系列等）会在每次会话中写入思考 token（reasoning tokens），且永不自动清理。其实际占比因使用习惯而异，建议先运行 `ocgc status` 查看 **Storage by Part Type** 分布，确认 `reasoning` 在你的库中是否占比可观：

```bash
# 剥离所有会话的 reasoning 思考内容（完美保留用户提示词、助手回答正文与工具调用历史）
ocgc purge --strip-reasoning

# 仅剥离 7 天以前会话的思考内容
ocgc purge --strip-reasoning --older-than 7d
```
*说明：在 OpenCode v2 中，`ocgc` 会深入消息 JSON 的 content 列表中移除思考节点，自动将 `tokens.reasoning` 置零并清空 `session_v2.tokens_reasoning` 统计，确保数据库一致性。*

#### 超大工具输出与多媒体部件截断 (`--strip-large-outputs`)
当某些会话因模型拉取了巨型日志或用户发送了超大 Base64 高清图片而异常膨胀时，可在保留完整会话链条的前提下安全裁剪：

```bash
# 裁剪所有会话中超过 500KB 的工具输出和媒体部件（保留前 1000 字符与后 500 字符，嵌入截断标记）
ocgc purge --strip-large-outputs

# 自定义截断阈值（如超过 1MB 裁剪）
ocgc purge --strip-large-outputs --threshold 1M

# 结合会话过滤或项目范围进行演练预览
ocgc purge --strip-large-outputs --project my-repo --dry-run
```

#### 按时间、类型或大小精细清理
```bash
# 清理 7 天前的子代理（Subagent）会话（主会话不受影响）
ocgc purge --subagents --older-than 7d

# 清理体积大于 50MB 的臃肿会话
ocgc purge --larger-than 50M

# 仅保留最近的 50 个最新会话，删除更早的旧会话
ocgc purge --keep-latest 50

# 按会话 ID 精准删除某个特定会话
ocgc purge --session ses_01955c4d32a078b5a03e1e24748ef534
```

#### 按项目/工作区目录范围定向清理 (`--project` / `--directory`)
精准清理已废弃或特定项目的旧会话与磁盘快照：

```bash
# 预览/清理指定项目的所有历史会话
ocgc purge --directory ~/Projects/legacy-repo --dry-run
ocgc purge --project legacy-repo --force

# 仅清除特定项目的 Git 快照
ocgc purge --clean-snapshots --project legacy-repo

# 组合过滤：仅清理特定项目中超过 14 天的会话
ocgc purge --project legacy-repo --older-than 14d
```

#### 清理前安全归档 (`--archive-to`)
在物理删除前先将会话导出为人类可读的 Markdown 文件备份，彻底消除误删顾虑：

```bash
# 清理 30 天以前的旧会话，并在删除前自动归档至指定目录
ocgc purge --older-than 30d --archive-to ~/.opencode_archives/

# 预览会清理哪些会话以及预归档路径（演练模式，不发生写入与删除）
ocgc purge --older-than 30d --archive-to ~/.opencode_archives/ --dry-run
```

#### 磁盘冗余文件清理
```bash
# 清理数据库已不存在、但磁盘仍遗留的孤立 session diff 文件
ocgc purge --clean-orphans

# 清理所有项目的 Git snapshot 快照（OpenCode 后续在需要时会自动重新创建）
ocgc purge --clean-snapshots

# 仅清理指定项目或工作目录的 Git 快照
ocgc purge --clean-snapshots --project my-app
ocgc purge --clean-snapshots --directory ~/Projects/legacy-repo

# 清理工具执行产生的临时标准输出缓存文件（支持通过 --older-than 过滤过期文件）
ocgc purge --clean-tool-output
ocgc purge --clean-tool-output --older-than 7d
```

#### 组合批量清理与无交互模式
```bash
# 一键清理孤立文件、Git 快照、过期工具输出缓存，并清理两周前的子代理会话（--force 免交互确认）
ocgc purge --clean-orphans --clean-snapshots --clean-tool-output --subagents --older-than 14d --force
```

---

### 3. 会话 Markdown 导出与归档 (`ocgc export`)

将历史对话导出为排版规范、结构清晰的 GitHub-flavored Markdown 文档，完整保留会话元数据（标题、ID、目录、创建/更新时间、模型与Token消耗）、用户提问与附件、折叠的工具调用日志及思考过程：

```bash
# 导出特定会话至指定目录
ocgc export --session ses_01955c4d32a078b5a03e1e24748ef534 -o ./exports/

# 导出特定会话为指定文件
ocgc export --session ses_01955c4d32a078b5a03e1e24748ef534 -o my_session.md

# 批量导出特定项目的所有会话
ocgc export --project my-project -o ./project_docs/

# 批量导出 30 天以前的会话
ocgc export --older-than 30d -o ./archive/

# 导出全部会话（精简视图，排除思考过程）
ocgc export --all --no-reasoning -o ./exports/
```

---

### 4. 轻量级 WAL 归并与重置 (`ocgc checkpoint`)

SQLite 在预写日志（WAL）模式下会将所有写入操作追加到 `opencode.db-wal` 中。长久运行或高频对话后，WAL 日志可能膨胀到数百兆且不释放。相比耗时较长且需要 2 倍空闲磁盘空间的 `vacuum`，`checkpoint` 可以在毫秒级内将 WAL 页面安全同步写回主库文件并将 WAL 日志截断重置为 0 字节：

```bash
# 默认执行 TRUNCATE 模式，将 WAL 重置为 0 字节
ocgc checkpoint

# 支持指定不同模式：truncate (默认), restart, full, passive
ocgc checkpoint --mode truncate
```

---

### 5. 释放物理磁盘空间 (`ocgc vacuum`)

SQLite 在删除数据行后，默认会将空闲页保留在数据库内部以便复用，并不会立即将磁盘空间归还给操作系统。执行 `vacuum` 命令可以完成物理磁盘整理与收缩：

```bash
ocgc vacuum
```
*命令执行后会对比整理前后的体积变化，并清晰显示实际为磁盘释放的物理空间大小。*

---

### 6. 数据库体检与健康诊断 (`ocgc doctor`)

对 OpenCode 数据库与存储空间执行全面健康检查，涵盖 SQLite 物理完整性、Schema 完备性、WAL 日志异常膨胀、跨表孤立悬空脏数据、文件系统读写权限以及磁盘孤立 diff 探测：

```bash
# 执行完整体检
ocgc doctor

# 快速检测模式（使用 PRAGMA quick_check）
ocgc doctor --quick

# 输出结构化 JSON（供脚本集成或 CI 流水线消费）
ocgc doctor --json
```

---

## 🗄️ OpenCode 存储架构图解

OpenCode 将数据分布在数据库与本地文件系统中：

```
~/.local/share/opencode/                  (Windows 下为 %LOCALAPPDATA%\opencode)
├── opencode.db                          <- SQLite 核心数据库（存放会话、消息、部件、事件等）
├── opencode.db-wal                      <- SQLite WAL 预写日志
├── storage/
│   └── session_diff/                    <- 各会话关联的差异记录 (*.json，记录完整文件改动)
├── snapshot/                            <- 各项目目录下的 Git packfile 状态快照
└── tool-output/                         <- 命令行及工具运行产生的临时标准输出缓存
```

1. **SQLite 数据库 (`opencode.db`)**：
   - **v1 模式**：`session`, `message`, `part`, `todo`, `session_share` 表。
   - **v2 模式**：`session_v2`, `session_message`, `session_inbox`, `session_pending`, `instruction_entry`, `instruction_state`, `todo`, `session_share`, `event`, `event_sequence` 等表。
2. **会话文件差异 (`storage/session_diff/`)**：
   - 包含每次会话改动的文件内容完整快照。删除会话时，`ocgc` 会联动清理对应的 `.json` 文件。
3. **工作区快照 (`snapshot/`)**：
   - OpenCode 在文件修改前通过 Git packfile 形式保存的项目快照仓库。
4. **工具输出缓存 (`tool-output/`)**：
   - 存储工具执行产生的大体积输出。

---

## 🛡️ 安全与工程可靠性保障

- **默认全流程只读保护**：`status`、`sessions`、`analyze`、`projects`、`doctor` 与 `export` 命令均以严格的 SQLite 只读 URI 模式（`?mode=ro`）打开数据库，绝不修改任何数据；仅 `purge`、`checkpoint` 与 `vacuum` 会以写入模式打开数据库。
- **活跃进程冲突检测与预警**：运行前自动检测 OpenCode 是否处于运行状态（Unix 环境使用 `pgrep`，Windows 环境使用 `tasklist` CSV 智能匹配），避免并发写入造成数据库锁死或损坏。
- **9 表级联原子事务回滚**：在 v2 模式下，针对 9 张关联引用表的级联删除全程处于同一数据库事务中，若发生意外错误会自动回滚，确保数据零损坏。
- **Windows 只读文件权限处理**：在 Windows 系统上，Git 快照目录下的文件常带有只读权限。`ocgc` 实现了安全递归删除机制（`_rmtree_safe` 结合 `chmod S_IWRITE`），彻底杜绝由于权限不足导致的崩溃。
- **交互确认与二次防误触**：所有破坏性清理操作必须交互确认（除非显式指定 `--force`），避免误删重要数据。

---

## ⚙️ 环境变量与自定义配置

| 环境变量 | 作用说明 | 默认值 |
| :--- | :--- | :--- |
| `OCGC_DB_PATH` | 显式指定 `opencode.db` 的绝对路径 | 自动探测 |
| `OPENCODE_DATA` | 显式指定 OpenCode 的数据根目录路径 | 自动探测 |
| `OCGC_SKIP_RUNNING_CHECK` | 设为 `1` 时跳过 OpenCode 是否正在运行的检测 | `0` |

### 各平台默认数据库路径
- **Windows**: `%LOCALAPPDATA%\opencode\opencode.db` (或 `%USERPROFILE%\AppData\Local\opencode\opencode.db`)
- **Linux & macOS**: `$XDG_DATA_HOME/opencode/opencode.db` (回退到 `~/.local/share/opencode/opencode.db`)

自定义路径示例：
```bash
export OCGC_DB_PATH=/path/to/your/opencode.db
ocgc status
```

---

## 🧪 测试验证

本项目包含完整的自动化测试集，对 OpenCode v1 和 v2 架构的模式探测、分析统计、级联删除、Reasoning 剥离、孤立文件处理和 CLI 交互进行全面测试验证：

```bash
uv run pytest
```

---

## 📄 开源许可证

本项目基于 [MIT](LICENSE) 许可证开源。

---

## 🙏 致谢

本项目最初由 [Wu Haotian (@whtsky)](https://github.com/whtsky) 作为 [whtsky/ocgc](https://github.com/whtsky/ocgc) 创建。
