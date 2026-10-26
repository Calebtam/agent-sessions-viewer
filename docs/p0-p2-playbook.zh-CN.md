# P0–P2 实施与调查运行手册

[English](p0-p2-playbook.md) | 中文

后续专项设计见
[CodexProvider 与 CopilotCLIProvider 双 Provider 改造方案](CodexProvider-CopilotCLIProvider-双Provider改造方案.md)，
具体执行步骤见
[双 Provider 详细实施方案](CodexProvider-CopilotCLIProvider-详细实施方案.md)。

本文保存 P0、P1、P2 实施过程中使用的命令、脚本、推理过程、调查结论、安全
规则和验证方法。后续研究 VS Code 聊天正文以及开展 P3–P5 时，应从本文开始。

## 1. 范围与当前成果

P0 建立了可恢复的 Codex 功能基线；P1 增加了只读的 VS Code 工作区发现和
诊断；P2 解析了经过真实数据验证的 VS Code Chat 索引格式，并把索引记录与
Codex 会话一起展示。

截至 2026-10-23 的验证结果：

| 项目 | 结果 |
|---|---:|
| VS Code `state.vscdb` 数据库 | 22 |
| 包含 `chat.ChatSessionStore.index` 的数据库 | 8 |
| 不包含该索引的数据库 | 14 |
| 解析到的 VS Code 索引记录 | 40 |
| 默认目录中的 Codex 会话 | 3 |
| 统一会话总数 | 43 |
| 已确认存在正文的 VS Code 会话 | 0 |

这 40 条 VS Code 记录是索引，不是恢复出的聊天正文。在找到真实正文来源并
证明可靠的关联规则之前，它们必须保持为 `index_only`。

## 2. 安全与隐私规则

1. 使用 `mode=ro` 打开原始 SQLite 数据库。
2. 禁止对 VS Code 数据库执行 `INSERT`、`UPDATE`、`DELETE`、表结构修改或
   SQLite 修复命令。
3. 结构诊断可以输出字段名、类型、数量和字节长度，但不得输出标题、会话 ID、
   输入状态、消息内容、Token 或完整数据库 Value。
4. 不能仅凭 Key 名称推断其内容语义。
5. 未知数量使用 `null`，不能写成 0。
6. 发现索引只能标记为 `index_only`，不能标记为 `partial` 或 `full`。
7. 所有新 API 必须复用现有授权检查。
8. 服务默认绑定 `127.0.0.1`；监听网络地址必须由用户显式指定。
9. `session_metadata.json` 可能包含访问令牌，禁止把它粘贴到 Issue 或诊断输出。

如果需要复制一个 VS Code 可能正在写入的数据库，应使用 SQLite 在线备份，
不要直接复制文件：

```bash
mkdir -p "$HOME/vscode_chat_backup"
sqlite3 "$HOME/.config/Code/User/workspaceStorage/<workspace-id>/state.vscdb" \
  ".backup '$HOME/vscode_chat_backup/workspace-state.vscdb'"
```

当前 P1/P2 实现通常不需要生成副本，因为读取器使用只读连接，并且会隔离单个
数据库的异常。

## 3. 可复用脚本

### 3.1 安全盘点与索引结构检查

运行项目内脚本：

```bash
python3 scripts/vscode_index_inventory.py
```

同时显示工作区 ID、解码后的路径、相关 Key 和索引大小：

```bash
python3 scripts/vscode_index_inventory.py --include-workspaces
```

检查非默认 VS Code 用户配置：

```bash
python3 scripts/vscode_index_inventory.py \
  --user-dir /path/to/Code/User \
  --include-workspaces
```

脚本会解析索引 JSON 以统计其结构，但有意省略所有记录 Key 和字段值。

### 3.2 完整执行 P0–P2 验证

```bash
python3 scripts/verify_p0_p2.py
```

检查其他 VS Code 用户配置：

```bash
python3 scripts/verify_p0_p2.py --user-dir /path/to/Code/User
```

验证脚本会运行单元测试、编译后端模块、调用 Flask 测试客户端、汇总 Provider
和正文状态数量，并确认未授权远程请求不能访问诊断接口。它不会启动网络监听
服务。

## 4. P0 过程：建立基线

### 4.1 检查仓库状态

```bash
git status --short
git log -1 --oneline
rg --files -g '!node_modules/**' -g '!.git/**' -g '!dist/**' -g '!build/**'
```

可恢复的源码基线是 Git 提交 `de9af4d`。原始 metadata 文件保持未修改。

确认工作区中的 metadata 仍与 Git 基线一致：

```bash
git show HEAD:session_metadata.json | sha256sum
sha256sum session_metadata.json
```

P0 记录的基线 SHA-256：

```text
c2e899918863df561ca98b534f0078981807e1c5411909f15ef8fd7f743af0cb
```

### 4.2 统计默认 Codex 会话

```bash
find "$HOME/.codex/sessions" -type f -name '*.jsonl' -printf '.' \
  2>/dev/null | wc -c
```

P0 当时发现 3 个文件。该数量取决于机器当前状态，之后可能增加。

### 4.3 基线修正与测试

P0 增加了解析器测试样本，覆盖普通事件、metadata、预览、工具调用和隐藏的
环境上下文，并把代码和文档中的默认地址统一为 `127.0.0.1:9001`。

使用的命令：

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile \
  backend/app.py \
  backend/parser.py \
  backend/discovery.py \
  backend/models.py \
  backend/registry.py \
  backend/providers/base.py \
  backend/providers/vscode_chat.py
```

## 5. P1 过程：安全发现 VS Code 数据库

### 5.1 定位候选文件

```bash
find "$HOME/.config/Code/User/workspaceStorage" -maxdepth 2 -type f \
  \( -name state.vscdb -o -name workspace.json \) -print | sort
```

### 5.2 只读取结构信息

`backend/discovery.py` 按以下步骤工作：

1. 枚举 `workspaceStorage/*/state.vscdb`。
2. 从相邻的 `workspace.json` 解码 `folder` 或 `workspace`。
3. 使用以 `?mode=ro` 结尾的 URI 建立 SQLite 连接。
4. 通过 `sqlite_master` 检查 `ItemTable`。
5. 查询 Key 名称、SQLite Value 类型和由 SQL 计算的字节长度。
6. 记录包含 `chat`、`copilot` 和 `agentSessions` 的相关 Key。
7. 分别隔离每个数据库的异常。

等价的核心 SQL：

```sql
SELECT 1
FROM sqlite_master
WHERE type = 'table' AND name = 'ItemTable';

SELECT key, typeof(value), length(CAST(value AS BLOB))
FROM ItemTable;
```

发现层不会查询完整 Value。P1 提供的仅管理员可访问接口为：

```text
GET /api/v2/diagnostics
```

验证授权行为使用的命令：

```bash
PYTHONPATH=backend python3 - <<'PY'
import app
client = app.app.test_client()
print(client.get('/api/v2/diagnostics').status_code)
print(client.get(
    '/api/v2/diagnostics',
    environ_base={'REMOTE_ADDR': '10.0.0.2'},
).status_code)
PY
```

使用当前访问配置时，预期本机返回 `200`，未授权远程请求返回 `403`。

### 5.3 P1 已覆盖的失败情况

- 缺少 `workspaceStorage`：返回空报告，不崩溃。
- 缺少 `ItemTable`：状态为 `no_item_table`。
- 数据库没有 Chat 索引：状态为 `no_chat_index`。
- 数据库损坏或锁定：单独记录为 `error`，不影响其他工作区。
- 索引 Value 是文本或二进制：不假定 JSON，仅报告类型和大小。
- `workspace.json` 缺失或格式错误：工作区路径留空。

## 6. P2 过程：验证并解析索引

### 6.1 结构发现

最初调查通过 Python 和 SQLite 只读循环，仅聚合 JSON 结构。其长期维护版本为：

```bash
python3 scripts/vscode_index_inventory.py
```

8 个索引的共同结构：

```text
顶层字段：entries、version
version：整数 1
entries：对象
记录数量：40
```

当前每条记录都包含以下字段：

```text
hasPendingEdits: bool
initialLocation: str
inputState: dict
isEmpty: bool
isExternal: bool
lastMessageDate: int
lastResponseState: int
permissionLevel: str
sessionId: str
timing: dict
title: str
```

`lastMessageDate` 始终是 13 位整数，因此实现将其按 Unix 毫秒时间戳转换，同时
生成 UTC ISO 时间和 `YYYY/MM/DD` 展示日期。

### 6.2 稳定标识

VS Code 索引记录无法映射为 Codex JSONL 路径。P2 使用以下稳定 ID：

```text
vscode-chat:<workspace-id>:<base64url(source-entry-key)>
```

Provider 前缀避免不同来源间冲突，工作区 ID 避免工作区之间冲突，Base64 URL
编码则避免把任意字符串直接构造成文件路径。安全盘点脚本不会显示来源记录 Key。

### 6.3 统一字段

Provider 返回内容包含以下规范化蛇形命名字段：

```text
id, provider, title, workspace, created_at, updated_at, source_path,
content_status, has_transcript, turn_count
```

为了兼容现有前端，当前还保留临时的驼峰命名字段。Codex 会话状态为 `full`，
VS Code 索引记录状态为 `index_only`。

### 6.4 API

```text
GET /api/v2/sessions
GET /api/v2/sessions?provider=vscode-chat
GET /api/v2/sessions?workspace=<完整工作区路径>
GET /api/v2/sessions?content_status=index_only
GET /api/v2/sessions/<stable-id>
```

旧版 Codex API 继续保留。前端使用 v2 接口获取统一列表；打开 Codex 详情时仍
调用旧版详情接口，打开 VS Code 仅索引记录时调用 v2 详情接口。

### 6.5 前端行为

- 来源筛选：全部、Codex、VS Code Chat。
- 工作区筛选：从统一会话列表动态生成。
- 正文状态筛选：`full`、`partial`、`index only`、`error`。
- VS Code 记录使用 `VSC` 卡片标识。
- 明确显示“已发现索引，但尚未定位正文”。
- 不会把空白详情伪装成真实对话。
- 在 metadata 迁移到稳定 ID 之前，VS Code 记录禁用 metadata 和关系编辑。

跨来源正文搜索不属于 P2，而是 P5 的任务。现有搜索继续覆盖 Codex 内容。

## 7. P2 完成后使用的验证命令

运行全部单元测试：

```bash
python3 -m unittest discover -s tests -v
```

无需启动浏览器即可检查前端 JavaScript 语法：

```bash
node -e "const fs=require('fs'),vm=require('vm');\
const h=fs.readFileSync('frontend/index.html','utf8');\
const s=[...h.matchAll(/<script(?: [^>]*)?>([\\s\\S]*?)<\\/script>/g)]\
.map(x=>x[1]).filter(Boolean);\
s.forEach(x=>new vm.Script(x));console.log('frontend scripts ok')"
```

API 数量和筛选冒烟测试：

```bash
PYTHONPATH=backend python3 - <<'PY'
import app
client = app.app.test_client()
for url in (
    '/api/v2/sessions',
    '/api/v2/sessions?provider=vscode-chat',
    '/api/v2/sessions?provider=codex',
    '/api/v2/sessions?content_status=index_only',
):
    response = client.get(url)
    print(url, response.status_code, len(response.get_json()['sessions']))
PY
```

检查修改：

```bash
git diff --check
git diff --stat
git status --short
```

## 8. 已积累的测试覆盖

`tests/test_parser.py`：

- Codex 会话 metadata。
- 预览提取。
- 用户和助手事件。
- 工具调用摘要。
- 隐藏环境上下文过滤。

`tests/test_discovery.py`：

- 不泄露内容的索引发现。
- 工作区 URI 正确解码。
- 损坏数据库异常隔离。
- 无索引数据库处理。
- 二进制或非 JSON 索引诊断。
- 把经过验证的版本 1 索引结构映射为 `index_only` 会话。
- 加载仅索引详情时不生成虚构 turn。

## 9. 文件导航

| 文件 | 用途 |
|---|---|
| `backend/discovery.py` | P1 不泄露内容的数据库诊断 |
| `backend/models.py` | 统一字段校验和时间戳转换 |
| `backend/registry.py` | Provider 查找与聚合 |
| `backend/providers/base.py` | Provider 接口约定 |
| `backend/providers/vscode_chat.py` | P1 诊断和 P2 索引解析 |
| `backend/app.py` | 旧版 API、v2 API、访问控制和启动参数 |
| `frontend/index.html` | 统一列表、筛选、来源标识和仅索引详情 |
| `tests/test_parser.py` | Codex 回归测试 |
| `tests/test_discovery.py` | P1/P2 测试样本和 Provider 测试 |
| `scripts/vscode_index_inventory.py` | 可复用的安全盘点与结构报告 |
| `scripts/verify_p0_p2.py` | 可重复执行的 P0–P2 验证 |
| `docs/p0-p1-baseline.zh-CN.md` | P0/P1 中文结果记录 |
| `docs/p2-index-integration.zh-CN.md` | P2 中文结果记录 |

## 10. 后续阶段交接

尝试恢复 VS Code 聊天正文前，应继续收集证据，不能凭当前索引结构推测：

1. 可以在本机私有调查中用会话 ID 搜索正文存储，但不得公开这些 ID。
2. 以只读方式检查 VS Code 全局存储和扩展私有存储。
3. 先记录文件类型、结构和关联字段，再考虑读取字段值。
4. 必须证明至少一条用户消息和一条助手消息属于同一个索引会话。
5. 添加脱敏测试样本和异常用例。
6. 满足以上条件后，才可以把对应会话从 `index_only` 提升为 `partial` 或
   `full`。

开展 P3 时，必须单独调查 Copilot CLI 的真实数据格式并实现独立 Provider；
不能因为它可能同样使用 JSONL，就直接复用 Codex 解析器。
