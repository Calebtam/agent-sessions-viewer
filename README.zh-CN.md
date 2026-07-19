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
   http://127.0.0.1:9000/
   ```

3. 指定其他 session 目录

   ```bash
   cd agent-sessions-viewer/backend
   python3 app.py --session_dir /path/to/your/sessions
   ```

## 管理员与远程访问

本机打开管理员页面：

```text
http://127.0.0.1:9000/admin
```

远程管理员访问需要 admin token：

```text
http://<server-ip>:9000/admin?token=<admin-token>
```

权限模型：

- `Guest`：控制无 token 远程访客可见的 session。
- `Viewer token`：远程只读访问指定 session 集合。
- `Admin token`：可远程进入 `/admin` 并管理访问配置。

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
python3 -m unittest tests/test_parser.py
```

检查后端文件语法：

```bash
python3 -m py_compile agent-sessions-viewer/backend/app.py agent-sessions-viewer/backend/parser.py
```

## 说明

- Session 文件需要是配置目录下的 JSONL 文件。
- Flask 服务定位为轻量本地工具。如果需要暴露到网络，请开启远程限制，并谨慎配置 admin/viewer token。
