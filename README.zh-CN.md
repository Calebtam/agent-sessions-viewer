# Agent Sessions Viewer

[English](README.md) | 中文

一个轻量级 Web 查看器，用于浏览、整理、搜索和受控分享 Codex Agent 生成的 JSONL 会话日志。

## 版本 v0.0.3

v0.0.3 基于 v0.0.2 继续增强，重点完善会话分类、详情页阅读、subagent 关系建模、远程访问权限和大纲同步体验。

### 主要更新

- 分类管理
  - 主页支持按日期或类别分组。
  - 支持新增、重命名、删除分类。
  - Session 卡片和详情页都支持选择分类。
  - 分类信息写入 `session_metadata.json`，不会修改原始 `.jsonl` 文件。

- 关系模型
  - 相关 session 拆分为 `Masters`、`Subagents`、`References`。
  - subagent 会根据 `parent_thread_id`、`thread_source` 和 source metadata 识别。
  - 支持多层 subagent 调用树。
  - 针对 master 和 subagent 复用同一个 `session_id` 的情况，使用文件级 ID 处理，避免把 subagent 识别成它自己。
  - 人工添加的关联被视为 reference，可以删除；自动 subagent 关系只展示。

- 详情页导航
  - 详情页左侧导航包含 Session、Relations、Outline。
  - 滚动正文时，Outline 会自动高亮当前浏览到的 turn。
  - 高亮的大纲项会自动滚动到可见区域。
  - 点击大纲项可以跳转到对应 turn。

- 排版方式
  - 详情页支持 1 列、2 列、3 列布局。
  - 选择结果会保存到 `localStorage`。
  - 排版切换按钮会根据当前列数显示在合适位置。

- 远程访问权限
  - 新增 `/admin` 访问配置页。
  - 本机访问默认是管理员。
  - 远程管理员访问使用 admin token。
  - Guest 配置用于控制无 token 远程访客能看到哪些 session。
  - Viewer token 可以自动生成或手动填写，并为每个 token 配置不同可见 session。
  - Admin token 可以进入 `/admin` 并管理访问配置。
  - 开启远程限制后，列表、搜索、详情和关系数据都会按当前 token 的权限过滤。

- 搜索与阅读体验
  - 搜索覆盖标题、文件名、标签、预览问题、用户输入、助手回复和 thinking 内容。
  - 搜索结果可以跳转到匹配 turn。
  - 每个 turn 支持 Copy turn。
  - 代码块支持 Copy。
  - Thinking 保持折叠显示。
  - 长会话使用 `content-visibility:auto` 降低浏览器渲染压力。

- API 与 parser
  - `/api/sessions` 返回 sessions 和 categories。
  - `/api/categories` 支持新增、重命名、删除分类。
  - `/api/access` 支持远程策略、Guest 权限、token 生成和 token 更新。
  - `/api/session/<path>?offset=0&limit=50` 返回分页 turn、outline、relations 和 session meta。
  - guardian approval 会话会被摘要化，不再把完整 transcript 当普通用户消息展开。
  - Parser 单元测试覆盖普通 event、IDE context、guardian approval 和 tool summary。

## 功能特性

- 浏览指定目录下的所有 Codex session。
- 按日期或类别查看 session 概览。
- 使用展示名、标签、分类、置顶和归档状态整理会话。
- 以 ChatGPT 风格查看详情页。
- 查看 master、subagent、reference 关系。
- 搜索可见 session 内容。
- 在不修改原始 session 文件的前提下重命名展示名称。
- 支持深色和浅色主题。
- 使用 Guest 和 scoped token 控制远程可见范围。

## 项目结构

- `backend/app.py`：Flask API 服务、metadata 处理、访问控制和 session 接口。
- `backend/parser.py`：JSONL session 解析与格式化逻辑。
- `frontend/index.html`：单页前端界面。
- `session_metadata.json`：展示名、标签、分类、关联关系和访问权限等本地 metadata。
- `tests/test_parser.py`：parser 单元测试。

## 快速开始

1. 安装依赖

   ```bash
   pip install flask
   ```

2. 启动后端服务

   ```bash
   cd agent-sessions-viewer/backend
   python3 app.py
   ```

   默认访问地址：

   ```text
   http://127.0.0.1:9001/
   ```

3. 指定其他 session 目录

   ```bash
   cd agent-sessions-viewer/backend
   python3 app.py --session_dir /path/to/your/sessions
   ```

## 管理员与远程访问

本机打开管理员页面：

```text
http://127.0.0.1:9001/admin
```

远程管理员访问需要 admin token：

```text
http://<server-ip>:9001/admin?token=<admin-token>
```

权限模型：

- `Guest`：控制无 token 远程访客可见的 session。
- `Viewer token`：远程只读访问指定 session 集合。
- `Admin token`：可远程进入 `/admin` 并管理访问配置。

管理员会话列表提供 `Delete` 操作。为避免误删，它不会永久清除源数据：

- Codex：把选中的 JSONL 文件移动到会话根目录下的
  `.agent-sessions-viewer-trash/<批次>/`。
- Copilot CLI：把包含 `events.jsonl` 和 `workspace.yaml` 的整个会话目录移动到
  `session-state/.agent-sessions-viewer-trash/<批次>/`。
- VS Code Chat：多个会话共用 `state.vscdb`，不支持单会话删除，界面显示
  `Shared index`。

删除操作只允许本机管理员或 admin token，执行前需要二次确认。回收站不会被 Provider
再次扫描；如需恢复，可在服务停止后把对应文件或目录移回原位置。

如果远程限制关闭，远程访客可以看到所有未归档 session。如果远程限制开启，远程可见范围由 Guest 或当前 token 决定。

## Metadata

查看器会把本地 metadata 写入：

```text
agent-sessions-viewer/session_metadata.json
```

该文件可能包含：

- 展示名称
- 标签
- 分类
- 置顶和归档状态
- reference 关联
- 访问控制配置

原始 Codex `.jsonl` session 文件不会被修改。

## 测试

运行 parser 测试：

```bash
python3 -m unittest discover -s tests -v
```

检查后端文件语法：

```bash
python3 -m py_compile backend/app.py backend/parser.py backend/discovery.py
```

## VS Code 诊断（P1）

以下仅管理员可访问的接口会以只读方式扫描 VS Code 工作区数据库。它只返回
工作区 ID、工作区位置、相关 Key 名称、Value 类型和字节数，不返回 Value
原文或聊天内容。

```text
GET http://127.0.0.1:9001/api/v2/diagnostics
```

如需检查其他 VS Code 用户数据目录：

```bash
python3 backend/app.py --vscode_user_dir /path/to/Code/User
```

服务默认只监听本机。只有在确实需要网络访问并复核访问控制配置后，才显式传入
`--host 0.0.0.0`。

## 多来源索引视图（P2）

主页现在会合并展示 Codex 正文会话与经过真实格式验证的 VS Code Chat 索引。
可以按来源、工作区和正文状态筛选。VS Code 条目会明确标记为 `index only`；
打开后会说明尚未定位聊天正文，不会生成虚构消息。

会话卡片、左侧列表和详情标题会明确显示 `CODEX`、`VS CODE` 或
`COPILOT CLI` 来源。主页还提供两个独立且会自动保存的显示选项：

- 隐藏所有 VS Code `index only` 会话。
- 只隐藏标题精确为 `New chat` 的 VS Code 占位会话。

两个选项默认关闭；同时开启时，以范围更大的 `index only` 过滤为准。

```text
GET /api/v2/sessions
GET /api/v2/sessions?provider=vscode-chat&content_status=index_only
GET /api/v2/sessions/<stable-id>
```

## Codex 与 Copilot CLI 双 Provider

当前版本可同时读取 Codex JSONL 和 Copilot CLI 的
`~/.copilot/session-state/*/events.jsonl`。Copilot CLI 使用经过本机真实数据验证的
`interactionId → turnId → toolCallId` 关联规则，支持用户消息、助手回复、推理、
工具执行、附件摘要、跨来源搜索和 Markdown/JSON 导出。

```bash
python3 scripts/copilot_cli_format_inventory.py
python3 scripts/verify_dual_providers.py
```

## 说明

- Session 文件需要是配置目录下的 JSONL 文件。
- Flask 服务定位为轻量本地工具。如果需要暴露到网络，请开启远程限制，并谨慎配置 admin/viewer token。
- P0–P2 的命令、调查过程、安全规则和复用脚本集中记录在
  [`docs/p0-p2-playbook.zh-CN.md`](docs/p0-p2-playbook.zh-CN.md)。
- 最新的总体改造设计和工程实施计划见
  [`docs/README.zh-CN.md`](docs/README.zh-CN.md)。
