# VSCode AI 会话存储分析与 Agent Sessions Viewer 改造方案

> 面向零基础读者的技术说明与实施设计（初稿）  
> 日期：2026-10-23  
> 范围：Ubuntu、VSCode、GitHub Copilot Chat、VSCode Chat、OpenAI Codex、Agent Sessions Viewer  
> 状态：**已完成路径线索分析与源码静态检查；尚未在用户电脑上验证聊天正文位置，也尚未实施改造。**

---

## 0. 一分钟理解：我们要解决什么问题？

平时在 VSCode 里使用 Codex、Copilot 或内置 Chat 与 AI 交流，可能产生很多有价值的内容：问题、回答、代码建议、工具调用以及修改思路。但是不同工具会把历史记录存放在不同地方；某些记录只在插件里显示，无法方便地统一查找。

**我们的目标**：基于已有的 `agent-session` 项目，制作一个可以在浏览器里打开的本地“AI 会话档案馆”，自动寻找电脑里的 Codex、Copilot CLI、VSCode Chat 会话，按项目和时间展示，搜索并导出能够成功读取的内容。

首先必须区分两个概念：

- **会话索引**：像图书馆的目录卡，告诉我们“有哪本书、叫什么、何时更新”，但不一定有正文。
- **会话正文**：像书的内容，包含用户提问、AI 回答、工具调用等。

**已经找到 VSCode Chat 的索引，不代表已经找到完整对话。** 这是当前项目最重要的事实边界。

### 预期使用效果

用户在 Ubuntu 终端运行 `python3 backend/app.py`，浏览器访问 `http://127.0.0.1:9001/`，就能看到：

1. 来源筛选：Codex / Copilot CLI / VSCode Chat。
2. 工作区筛选：例如 `/home/tanyq3/wk/repo` 和 `/home/tanyq3/wk/repo/umf/map_fusion`。
3. 会话列表：标题、日期、来源、是否找到正文。
4. 会话详情：找到正文则显示聊天内容；只有索引则清楚显示“仅索引，正文未找到”。
5. 搜索、分类、导出、只读浏览，不修改原始聊天数据。

---

## 1. 零基础词汇表

| 术语 | 通俗解释 | 本项目中的作用 |
|---|---|---|
| VSCode | 用来编写代码的编辑器 | AI 插件的宿主程序 |
| 插件 / Extension | 给 VSCode 增加功能的小程序 | Copilot Chat、Codex 等 |
| 工作区 / Workspace | VSCode 当前打开的项目文件夹 | 区分不同项目的聊天历史 |
| Session / 会话 | 一次或一组连续 AI 对话 | 浏览器中的一张会话卡片 |
| SQLite | 把数据存在一个文件中的小型数据库 | 读取 `state.vscdb` |
| `state.vscdb` | VSCode 工作区状态数据库 | 可能保存会话索引、界面状态等 |
| Key / Value | 数据库里的“名称—内容”配对 | `chat.ChatSessionStore.index` 是一个 key |
| JSON | 人容易阅读的结构化数据格式 | 索引和接口的数据表示 |
| JSONL | 一行一个 JSON 对象的日志文件 | Codex 会话常见格式 |
| Flask | Python 编写的轻量 Web 服务框架 | 把本地数据提供给浏览器 |
| API | 前端向后端请求数据的接口 | 如 `/api/sessions` |
| Parser / 解析器 | 把原始文件转换成统一数据的程序 | 适配不同 AI 工具的记录格式 |
| Provider / 数据源适配器 | 专门读取一种来源的模块 | Codex、Copilot CLI、VSCode Chat 各一个 |
| 只读 | 可以查看但不更改源文件 | 避免破坏 VSCode 数据 |

---

## 2. 用户电脑上已经确认的事实

以下结论来自本次对话中用户亲自执行的命令及输出，而非推测。

### 2.1 没有发现独立的 `chatSessions` 目录

运行：

```bash
find ~/.config/Code/User/workspaceStorage \
  -type d -name "chatSessions" 2>/dev/null
```

**结果为空。** 这只能说明被搜索的 `workspaceStorage` 树下没有名为 `chatSessions` 的目录；**不能推断没有聊天记录**，也不能排除其他目录、数据库或插件私有存储。

### 2.2 发现 Copilot 扩展全局目录

运行：

```bash
find ~/.config/Code/User/globalStorage \
  -maxdepth 2 -iname "*copilot*" 2>/dev/null
```

发现：

```text
/home/tanyq3/.config/Code/User/globalStorage/github.copilot-chat
/home/tanyq3/.config/Code/User/globalStorage/github.copilot-chat/copilot-cli-images
/home/tanyq3/.config/Code/User/globalStorage/github.copilot-chat/copilotCli
```

这说明 Copilot 扩展确实使用了该目录，**但仅凭目录名无法判断是否包含聊天正文**。例如 `copilotCli` 也可能保存程序组件。

### 2.3 发现 22 个 VSCode 工作区状态数据库

它们的共同形式是：

```text
~/.config/Code/User/workspaceStorage/<工作区ID>/state.vscdb
```

其中两个工作区已经出现明确的 Chat 会话索引：

| 工作区路径 | 工作区 ID | 数据库 Key | Value 长度 |
|---|---|---|---:|
| `/home/tanyq3/wk/repo/umf/map_fusion` | `5b6b14665796360df7c84100d7ac38ab` | `chat.ChatSessionStore.index` | 3,920 字节 |
| `/home/tanyq3/wk/repo` | `871529f0f5b5745fed2774655884891d` | `chat.ChatSessionStore.index` | 7,728 字节 |

**字节数不是会话数量**，不能由 3,920 或 7,728 字节直接计算有多少段聊天。

另一个工作区 `1792663104469` 出现 `agentSessions.model.cache` 等状态键，但本次展示的结果没有 `chat.ChatSessionStore.index`。

### 2.4 已发现的键分别可能是什么

| Key | 合理解释 | 是否等于聊天正文 |
|---|---|---|
| `chat.ChatSessionStore.index` | VSCode Chat 会话目录或索引 | **尚未证实**；优先作为元数据分析 |
| `chat.untitledInputState` | 未提交输入框的状态 | 不是可靠的历史正文来源 |
| `GitHub.copilot-chat` | Copilot 扩展的工作区状态 | 需要检查实际内容 |
| `memento/interactive-session-view-copilot` | Copilot 界面或交互状态 | 不能仅凭名字判断 |
| `agentSessions.model.cache` | Agent 会话相关模型缓存 | 不代表完整正文 |
| `agentSessions.state.cache` | Agent 状态缓存 | 不代表完整正文 |
| `chat.customModes.local` | 本地自定义聊天模式配置 | 通常不是聊天正文 |
| `workbench.panel.chat` | Chat 面板布局和界面状态 | 通常不是聊天正文 |
| `memento/webviewView.chatgpt.sidebarSecondaryView` | 某个 ChatGPT 视图的状态 | 不等于 Codex 会话正文 |

**重要原则**：先读取真实值、确认结构，再决定如何解析；不要凭 Key 的名字硬编码“聊天消息”。

---

## 3. AI 会话通常可能存在哪里？

> 以下是需要扫描的候选位置，因产品版本、扩展版本和用户配置不同，实际文件不一定存在。

```text
/home/tanyq3/
├── .codex/
│   ├── sessions/                 # Codex 常见 JSONL 会话位置
│   ├── archived_sessions/        # 可能存在的归档会话
│   ├── history.jsonl             # 可能存在的命令/输入历史
│   └── state_*.sqlite            # 可能存在的索引或状态数据库
├── .copilot/
│   └── session-state/            # Copilot CLI 候选会话位置
└── .config/Code/User/
    ├── workspaceStorage/
    │   └── <工作区ID>/
    │       ├── workspace.json    # 工作区与实际项目的对应关系
    │       ├── state.vscdb       # 工作区状态 SQLite 数据库
    │       └── chatSessions/     # 部分版本可能存在；本机未找到
    └── globalStorage/
        ├── state.vscdb           # 全局状态数据库（如存在）
        └── github.copilot-chat/  # Copilot 扩展私有目录
```

### 3.1 三种来源应分别处理

**Codex**：优先查找 `~/.codex/sessions/**/*.jsonl`；它是现有 Viewer 已支持的主要数据源。不能假定每条 JSONL 都是普通聊天文本，其中可能有上下文、事件和工具调用。

**Copilot CLI**：优先调查 `~/.copilot/` 中是否存在会话文件（例如 `session-state` 下的事件日志）；在发现真实文件及其结构之前，不应直接照搬 Codex 的解析规则。

**VSCode Copilot / Chat**：首先读取 `workspace.json` 确认工作区，再读取 `state.vscdb` 的 `chat.ChatSessionStore.index`；之后寻找索引引用的正文，或其他可关联的存储位置。**VSCode Chat 与 Copilot CLI 不是同一种存储机制。**

### 3.2 为什么会“看见会话标题，却看不到聊天内容”？

可以想象书店的系统：

```text
[书目索引] ——记录——> [书的编号、标题、时间]
     │
     └────需要找到────> [实际书籍正文]
```

当前发现的 `chat.ChatSessionStore.index` 类似“书目索引”。如果正文保存在别处、被清理、由扩展另行管理，或采用尚未识别的格式，那么 Viewer 只能展示会话目录，不能凭空恢复聊天内容。

---

## 4. 如何安全地确认真实数据格式（新手操作）

### 4.1 安装工具

```bash
sudo apt update
sudo apt install -y sqlite3 sqlitebrowser python3
```

### 4.2 不直接操作 VSCode 正在写入的数据库

建议先用 SQLite 的在线备份命令复制一致的数据库快照：

```bash
mkdir -p "$HOME/vscode_chat_backup"

sqlite3 "$HOME/.config/Code/User/workspaceStorage/871529f0f5b5745fed2774655884891d/state.vscdb" \
  ".backup '$HOME/vscode_chat_backup/repo-state.vscdb'"
```

`sqlite3` 的 `.backup` 命令比直接 `cp` 一个正在使用的数据库更适合获得一致快照。

### 4.3 检查表结构

```bash
sqlite3 "$HOME/vscode_chat_backup/repo-state.vscdb" ".tables"

sqlite3 "$HOME/vscode_chat_backup/repo-state.vscdb" \
  "PRAGMA table_info(ItemTable);"
```

如果存在 `ItemTable`，可以读取索引：

```bash
sqlite3 "$HOME/vscode_chat_backup/repo-state.vscdb" \
  "SELECT CAST(value AS TEXT) FROM ItemTable WHERE key='chat.ChatSessionStore.index';" \
  | python3 -m json.tool
```

如果 `json.tool` 报错，**不要认定数据损坏**：可能是非 JSON 文本、二进制、特殊编码或空值，需要另行检查类型和前缀。

### 4.4 用 Python 查看索引形状，不直接公开聊天内容

```python
import json
import sqlite3
from pathlib import Path

p = Path.home() / "vscode_chat_backup/repo-state.vscdb"
conn = sqlite3.connect(p.as_uri() + "?mode=ro", uri=True)
row = conn.execute(
    "SELECT value FROM ItemTable WHERE key=?",
    ("chat.ChatSessionStore.index",),
).fetchone()
conn.close()

if row is None:
    print("没有找到会话索引")
else:
    raw = row[0]
    print("原始类型:", type(raw).__name__)
    print("字节数:", len(raw))
    try:
        obj = json.loads(raw)
        print("JSON 顶层类型:", type(obj).__name__)
        if isinstance(obj, dict):
            print("顶层字段:", list(obj.keys()))
        elif isinstance(obj, list):
            print("条目数:", len(obj))
            if obj and isinstance(obj[0], dict):
                print("首条字段:", list(obj[0].keys()))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        print("暂时无法按 JSON 解析:", exc)
```

**分享诊断结果时只分享字段名、类型和长度**，不要直接公开可能包含私有代码、聊天文本、令牌的完整值。

### 4.5 还应检查哪些目录？

```bash
# Codex 会话数量
find "$HOME/.codex/sessions" -type f -name '*.jsonl' 2>/dev/null | wc -l

# Copilot CLI 候选文件
find "$HOME/.copilot" -maxdepth 5 -type f \
  \( -name '*.jsonl' -o -name '*.json' -o -name '*.db' \) 2>/dev/null | head -30

# Copilot 扩展目录中最大的文件
find "$HOME/.config/Code/User/globalStorage/github.copilot-chat" \
  -type f -printf '%s %p\n' 2>/dev/null | sort -nr | head -30

# VSCode 全局状态数据库（如果存在）
ls -l "$HOME/.config/Code/User/globalStorage/state.vscdb" 2>/dev/null
```

### 4.6 验证成功的判断标准

- 找到会话索引：能列出真实的会话标识、标题等字段（以实际格式为准）。
- 找到会话正文：能解析出至少一条真实用户消息和一条真实 AI 消息，并关联同一会话。
- 没找到正文：明确标记 `index_only`，不得伪造空白对话或猜测内容。

---

## 5. 已上传的 agent-session 项目是什么？

本方案参考用户上传的 `agent-session.zip`，并检查了解压后的以下真实文件：

```text
agent-session/
├── backend/
│   ├── app.py
│   └── parser.py
├── frontend/
│   └── index.html
├── README.md
├── README.zh-CN.md
└── session_metadata.json
```

压缩包还包含 `backend/__pycache__/` 编译缓存；这不是开发所需源码。README 中提及 `tests/test_parser.py`，但**此次上传的压缩包内未见该文件**，后续应补齐测试。

### 5.1 当前已有能力

根据 README 和源码检查，现有项目提供：

- Flask 后端与单页 HTML 前端。
- Codex JSONL 会话读取与格式化。
- 会话列表、日期/类别分组、搜索、详情分页。
- Thinking、工具调用、关系树（master/subagent/reference）。
- 展示名、标签、置顶、归档等本地元数据。
- 远程访问控制配置与 token 机制。

这些功能应尽量保留，而不是重新实现一套界面。

### 5.2 当前源码的关键位置

| 文件或函数 | 现在做什么 | 改造意义 |
|---|---|---|
| `backend/app.py` 的 `--session_dir` | 指定 Codex 会话根目录 | 增加多来源配置 |
| `all_session_infos()` | 用 `BASE.rglob('*.jsonl')` 扫描 | 改为汇总多个 Provider |
| `session_info()` | 基于相对文件路径建立元数据 | 改为使用稳定的跨来源 ID |
| `cached_session()` | 缓存解析后的会话 | 缓存键应包含来源和版本信息 |
| `/api/sessions` | 返回会话列表 | 增加 provider、workspace、正文状态 |
| `/api/search` | 搜索现有 Codex 会话 | 支持跨来源搜索并遵守权限 |
| `/api/session/<path:sp>` | 根据相对文件路径读取详情 | 兼容旧接口，增加稳定 ID 接口 |
| `backend/parser.py` | 解析 Codex JSONL | 保留为 Codex 专用解析逻辑 |
| `frontend/index.html` | 展示 Codex 会话 | 新增来源、工作区、状态过滤 |
| `session_metadata.json` | 存分类、标签、访问配置 | 迁移为跨来源稳定 ID 索引 |

**源码级已确认的约束**：`app.py` 直接使用 `BASE / sp` 和 `BASE.rglob('*.jsonl')`，意味着它把“会话”与“某个 Codex JSONL 文件路径”强绑定。VSCode SQLite 索引无法直接塞进这一假设。

### 5.3 端口和安全细节

上传的 `backend/app.py` 实际最后运行的是：

```python
app.run(host="0.0.0.0", port=9001)
```

但上传的 README 写的是 `127.0.0.1:9000`。**文档与代码不一致，以实际代码为准**。改造时应统一默认端口为 `9001`（也可以另行统一为 `9000`，但要同步修改文档和配置），默认监听 `127.0.0.1`，避免无意暴露全部会话。Flask 开发服务器不应直接作为公网生产服务。

---

## 6. 初步改造的整体架构

核心思路：**前端尽量不动，后端增加多数据源适配层**。

```text
                        浏览器
              ┌────────────────────────┐
              │ frontend/index.html    │
              │ 列表 / 搜索 / 聊天详情 │
              └────────────┬───────────┘
                           │ HTTP 请求
              ┌────────────▼───────────┐
              │ backend/app.py         │
              │ Flask API / 权限控制   │
              └────────────┬───────────┘
                           │
              ┌────────────▼───────────┐
              │ registry.py            │
              │ 合并会话 / 统一 ID     │
              └──────┬─────┬─────┬─────┘
                     │     │     │
              ┌──────▼─┐ ┌─▼────┐ ┌▼───────────────┐
              │ Codex  │ │ CLI  │ │ VSCode Chat    │
              │ JSONL  │ │JSONL │ │ SQLite / 索引  │
              └────────┘ └──────┘ └────────────────┘
```

### 6.1 建议的文件结构

```text
agent-session/
├── backend/
│   ├── app.py                  # 现有 Flask 服务，逐步调整
│   ├── parser.py               # 保留旧 Codex 解析器
│   ├── registry.py             # 聚合不同 Provider
│   ├── discovery.py            # 自动发现本机数据源
│   ├── models.py               # 统一会话/消息数据结构
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py             # 适配器接口
│   │   ├── codex.py            # 调用原 parser.py
│   │   ├── copilot_cli.py      # 读取 Copilot CLI 日志
│   │   └── vscode_chat.py      # 读取 VSCode 数据库/索引
│   └── tests/
│       ├── test_codex.py
│       ├── test_vscode_index.py
│       ├── test_registry.py
│       └── test_api.py
├── frontend/
│   └── index.html
├── session_metadata.json
├── README.md
└── README.zh-CN.md
```

### 6.2 统一的数据结构

不管会话来自哪种工具，前端看到的字段应尽量一致。

```json
{
  "id": "vscode-chat:871529f0f5b5745fed2774655884891d:EXAMPLE_ID",
  "provider": "vscode-chat",
  "workspace": "/home/tanyq3/wk/repo",
  "title": "示例会话（非真实数据）",
  "created_at": null,
  "updated_at": null,
  "source_path": ".../state.vscdb",
  "content_status": "index_only",
  "has_transcript": false,
  "turn_count": null
}
```

这是**设计示例**，不是从用户数据库读出的真实记录。字段含义：

- `id`：跨来源唯一标识，避免两个工具使用相同会话 ID 时冲突。
- `provider`：记录来自哪个工具。
- `workspace`：聊天关联的项目目录。
- `content_status`：`full`（已读到正文）、`partial`（只读到部分）、`index_only`（只有索引）、`error`（解析失败）。
- `has_transcript`：是否存在可展示的实际消息。
- `turn_count`：无法确认时应为 `null`，不能随意写成 0。

消息的统一结构可设计为：

```json
{
  "id": "message-1",
  "role": "user",
  "timestamp": null,
  "content": "示例问题",
  "kind": "message",
  "tool_calls": []
}
```

现有前端使用的 `turns` 格式应由一层**格式转换器**生成，避免新 Provider 必须模仿 Codex 原始事件格式。

### 6.3 Provider 适配器的职责

每个 Provider 至少实现以下能力：

```python
class SessionProvider:
    provider_id = "base"

    def discover(self):
        """发现本来源的会话，返回统一会话摘要列表。"""
        raise NotImplementedError

    def load(self, session_id):
        """按稳定 ID 读取会话详情。"""
        raise NotImplementedError
```

进阶版本再增加 `search()`、`refresh()`、`capabilities()`。第一阶段不必把接口设计得过于复杂。

---

## 7. 三种 Provider 应该如何工作？

### 7.1 Codex Provider：先保证原有功能不坏

**输入**：`~/.codex/sessions/**/*.jsonl`。  
**操作**：复用 `backend/parser.py` 的 `load_session()`、`load_session_meta()`、`load_session_preview()`。  
**输出**：统一会话摘要和消息。

保留原有的工具调用、Thinking、subagent 关系、搜索和分页。Codex 是已有能力，应该作为每次改动的回归测试基线。

### 7.2 Copilot CLI Provider：先发现，后解析

**输入候选**：`~/.copilot/session-state/` 等真实存在的会话文件。  
**操作**：列出文件 → 识别 JSONL 事件格式 → 提取用户/助手消息 → 关联工具调用。  
**输出**：统一会话摘要和消息。

不能假定 Copilot CLI JSONL 字段与 Codex 完全一致。必须准备脱敏的真实样本后实现字段映射。

### 7.3 VSCode Chat Provider：分两阶段

**阶段 A：索引模式（现在可以开始）**

1. 遍历 `~/.config/Code/User/workspaceStorage/*/state.vscdb`。
2. 读取同目录 `workspace.json`，获得项目路径。
3. 检查数据库是否存在 `ItemTable`。
4. 查询 `chat.ChatSessionStore.index`。
5. 识别其真实编码与 JSON 结构。
6. 根据真实字段提取会话 ID、标题、时间。
7. 展示为 `index_only`，不伪造正文。

**阶段 B：正文模式（必须先找到真实正文）**

1. 依据索引字段寻找对应会话正文文件或数据库记录。
2. 验证消息归属，避免把别的会话拼接进来。
3. 将用户消息、助手消息、工具调用映射成统一结构。
4. 找不到正文则继续保持 `index_only`。

**现阶段最大的未知数**：用户的 VSCode 版本到底把正文存在哪个路径、使用什么格式。不能在缺少真实样本时承诺完整恢复。

---

## 8. API 与界面如何改造

### 8.1 保留已有接口

已有接口例如：

```text
GET /api/sessions
GET /api/search
GET /api/session/<path>
```

先保持旧 Codex 入口可用，避免旧前端立即失效。

### 8.2 增加新的跨来源接口

建议：

```text
GET /api/providers
GET /api/v2/sessions?provider=vscode-chat&workspace=...
GET /api/v2/sessions/<session_id>
GET /api/v2/search?q=...
GET /api/v2/diagnostics
```

其中 `<session_id>` 应采用 URL 安全编码或路由编码，不允许直接把用户输入拼成任意文件路径。`/api/v2/diagnostics` 只输出来源是否存在、索引数量、解析失败数等，不输出密钥或聊天正文。

### 8.3 前端增加哪些内容？

建议第一阶段只增加：

- 来源筛选框：全部 / Codex / Copilot CLI / VSCode Chat。
- 工作区筛选框：例如 repo、map_fusion。
- 会话状态标签：完整、部分、仅索引、解析失败。
- 对“仅索引”的详情显示明确说明：“已发现此会话的目录信息，但尚未定位消息正文”。
- 错误详情：可复制不含敏感内容的诊断信息。

原有搜索、分类、布局、深浅色主题和会话关系继续复用。

### 8.4 元数据与关系如何避免冲突？

原来项目常用相对 JSONL 路径识别会话。新项目必须使用 `provider + source-specific-id` 构造稳定 ID，并将旧 Codex 元数据迁移映射到新 ID。不要直接覆盖已有 `session_metadata.json`；迁移前备份，并保留回滚路径。

---

## 9. 开发任务分阶段实施（推荐）

### P0：建立基线（必须先做）

- [ ] 备份原项目和 `session_metadata.json`。
- [ ] 在本地成功运行原有 Codex Viewer。
- [ ] 记录当前页面、会话数量、搜索和详情表现。
- [ ] 补齐至少一组 Codex 解析测试。
- [ ] 修正 README 与实际监听端口不一致问题。

**验收**：原版 Codex 浏览、搜索、详情、分类、权限功能正常。

### P1：VSCode 数据库发现与诊断

- [ ] 自动扫描所有工作区数据库。
- [ ] 识别 `workspace.json` 对应项目路径。
- [ ] 只读查询 `ItemTable`，记录相关 Key。
- [ ] 处理数据库不存在、锁冲突、损坏、非 JSON Value。
- [ ] 输出诊断报告，不泄露聊天内容。

**验收**：能够识别用户机器上至少已确认的两个有 Chat 索引的工作区；对其他工作区不误报。

### P2：会话索引展示

- [ ] 获取脱敏的 `chat.ChatSessionStore.index` 真实结构。
- [ ] 按实际字段提取会话 ID、标题、时间。
- [ ] 统一 Session 数据模型。
- [ ] 前端显示 VSCode Chat 来源及 `index_only` 状态。
- [ ] 完成按工作区、来源过滤。

**验收**：能在浏览器中查看真实索引条目；不显示虚构消息。

### P3：Copilot CLI 解析

- [ ] 确认 CLI 会话路径和格式。
- [ ] 编写事件解析器。
- [ ] 支持用户/助手消息与工具调用。
- [ ] 增加异常样本测试。

**验收**：至少一段真实、经脱敏的 CLI 会话能正确展示。

### P4：VSCode Chat 正文恢复

- [ ] 定位真实正文位置或关联机制。
- [ ] 建立索引与正文的一对一/一对多关联规则。
- [ ] 处理缺失、部分、损坏和多来源重复会话。
- [ ] 添加正文解析测试。

**验收**：对已找到正文的会话正确展示；未找到正文的会话明确标注“仅索引”。若正文不可得，该阶段允许以“无法恢复”的有证据结论结束。

### P5：统一搜索、导出与发布

- [ ] 跨来源搜索标题和已解析消息。
- [ ] 导出 Markdown/JSON（仅导出实际已读取内容）。
- [ ] 增加增量扫描和缓存。
- [ ] 完善安装、使用、备份与安全文档。
- [ ] 检查权限控制对所有新接口均生效。

**验收**：可长期作为本地只读会话档案馆使用。

---

## 10. 风险与防护措施

| 风险 | 可能后果 | 应对方式 |
|---|---|---|
| 误写 VSCode 数据库 | 插件状态损坏、历史丢失 | SQLite 只读连接；必要时使用一致性快照 |
| 索引被误当正文 | 展示错误或空白消息 | `content_status` 明确区分 |
| VSCode 版本变更 | 解析器失效 | 版本/格式检测、测试样本、失败回退 |
| 不同来源 ID 冲突 | 混淆两段聊天 | 使用带 Provider 前缀的稳定 ID |
| 文件路径穿越 | 读取不应访问的文件 | 只允许 Provider 管理的 ID，不拼接任意路径 |
| 搜索接口越权 | 未授权用户读到私密聊天 | 所有接口复用统一权限过滤 |
| 默认监听所有网卡 | 局域网其他设备可能访问 | 默认绑定 `127.0.0.1` |
| 会话含密码/密钥 | 导出或分享时泄露 | 默认本地访问；导出前提醒脱敏 |
| 扫描大量文件 | 启动慢、CPU 占用高 | 分页、缓存、增量索引、大小限制 |
| 元数据迁移错误 | 分类、标签丢失 | 迁移前备份、可回滚、自动化测试 |

特别说明：上传项目中已有远程访问权限逻辑，但**新增接口必须重新验证是否完全经过同一套授权检查**。不能因为旧版支持 token 就假设新功能天然安全。

---

## 11. 完成后的验收测试（零基础版）

假设最终项目仍使用 `backend/app.py` 启动：

```bash
cd agent-session
python3 -m pip install flask
python3 backend/app.py
```

浏览器打开实际启动日志给出的地址。改造后默认推荐 `http://127.0.0.1:9001/`。

测试时逐项检查：

1. **原版兼容**：以前的 Codex 会话还在，能够打开和搜索。
2. **工作区识别**：列表里能看到 `/home/tanyq3/wk/repo`、`map_fusion` 等真实路径。
3. **索引可见**：能看到从 `chat.ChatSessionStore.index` 解析出来的真实会话条目。
4. **正文状态**：没找到正文时明确写“仅索引”，而不是显示假消息。
5. **过滤有效**：切换 Codex / Copilot / VSCode 不会混淆来源。
6. **只读安全**：使用前后原始 VSCode 数据库和 JSONL 文件不被工具修改。
7. **访问安全**：从非本机访问时，未经授权不能获取会话内容。
8. **异常稳健**：某个数据库格式不认识，其他会话仍可正常浏览。

**不要把“扫描到数据库”当作“完成聊天恢复”**；真正的恢复标准是能够准确展示与该会话对应的真实问答。

---

## 12. 下一步最需要的真实材料

为了从初步方案进入代码实现，当前最需要以下信息：

1. 两个工作区中 `chat.ChatSessionStore.index` 的 **JSON 顶层字段、条目字段及类型**（优先脱敏，不必分享聊天正文）。
2. `~/.config/Code/User/globalStorage/github.copilot-chat/` 下的文件名、大小和扩展名。
3. `~/.codex/sessions/` 和 `~/.copilot/` 是否存在，以及各自的会话文件格式。
4. VSCode 版本、GitHub Copilot Chat 扩展版本、Codex 扩展版本，以便解释存储格式差异。

有了这些材料，才能把“可能的存储位置”升级为“经本机验证的准确存储位置”，并实现可靠解析器。

---

## 13. 给实际开发者或 AI 编程助手的实施要求

**项目目标**：在用户上传的 `agent-session` 源码基础上，增加多 Provider 会话读取，优先支持 VSCode Chat 索引，并保持现有 Codex 功能完整。

**硬性约束**：

- 不重写已有前端和 Codex 解析器，除非确有必要。
- 不直接修改任何原始 VSCode、Codex、Copilot 会话文件。
- 不根据文件名或 Key 名称猜测消息内容；解析必须有真实格式证据。
- 统一会话模型必须区分 `full`、`partial`、`index_only`、`error`。
- 保留现有 metadata、分类、搜索、关系与权限行为。
- 先做 P0/P1/P2，确认有效后再做 P3/P4/P5。
- 所有新增接口必须具备路径安全与访问控制。
- 所有功能都要有可复现的测试、启动命令、示例输出和失败提示。

**第一阶段交付物**：

- `backend/providers/base.py`
- `backend/providers/codex.py`
- `backend/providers/vscode_chat.py`
- `backend/registry.py`
- 必要的 `app.py` 和 `frontend/index.html` 小范围改动
- VSCode SQLite 索引解析测试及脱敏测试数据
- 更新后的 README 和迁移说明

**第一阶段成功的定义**：用户能继续浏览 Codex 历史，并能在同一网页中看到 VSCode Chat 的真实会话索引，清楚知道哪些会话已经找到正文、哪些还没有。

---

## 14. 最终结论

当前调查已经证明：**用户电脑的两个 VSCode 工作区数据库中存在 `chat.ChatSessionStore.index` 记录**，说明有可供进一步研究的 Chat 会话索引线索；但尚无证据表明完整 Copilot Chat 正文位于这些数据库中。

用户上传的 `agent-session` 项目已经具备 Codex 会话浏览、搜索、分类和 Web 展示的基础能力。最佳改造路线不是重写项目，而是增加 **数据源发现 → 多 Provider 解析 → 统一会话模型 → 原有界面展示** 四层能力，并先交付“VSCode 会话索引可见”，再根据真实数据继续解决“正文恢复”。

这样既能快速产生可验证成果，也能避免因为猜测存储格式而误读或破坏原始数据。
