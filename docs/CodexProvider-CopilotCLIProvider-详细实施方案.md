# CodexProvider 与 CopilotCLIProvider 详细实施方案

> 文档类型：专项工程实施设计  
> 版本：1.0  
> 日期：2026-10-23  
> 上位文档：[双 Provider 改造方案](CodexProvider-CopilotCLIProvider-双Provider改造方案.md)  
> 格式证据：[Copilot CLI 真实格式调查报告](CopilotCLI-真实格式调查报告.md)

## 1. 交付范围

本实施方案交付：

- 完整 `CodexProvider`。
- 完整 `CopilotCLIProvider`。
- Copilot CLI 流式 parser。
- 两个 Provider 共用的模型、Registry、Service、metadata、权限、搜索和导出。
- 对应测试、Fixture、诊断脚本和中英文文档。

现有 `VSCodeChatProvider` 保持可用，但不在本专项中继续扩展或作为 Copilot CLI
的依赖。

## 2. 实施前基线

开始编码前执行：

```bash
python3 scripts/verify_p0_p2.py
python3 scripts/copilot_cli_format_inventory.py
python3 -m unittest discover -s tests -v
git diff --check
git status --short
```

记录：

- 当前 Git 提交。
- `session_metadata.json` SHA-256。
- Codex 会话数。
- Copilot CLI 会话数、事件数和非法行数。
- v2 API 当前响应计数。

禁止把真实 events 内容复制到仓库。

## 3. 计划文件

```text
backend/
├── models.py
├── registry.py
├── legacy_adapter.py
├── parsers/
│   ├── __init__.py
│   ├── codex.py              # 初期可包装原 parser.py
│   └── copilot_cli.py
├── providers/
│   ├── base.py
│   ├── codex.py
│   ├── copilot_cli.py
│   └── vscode_chat.py        # 保留，不在本专项扩展
├── services/
│   ├── sessions.py
│   ├── metadata.py
│   ├── access.py
│   ├── search.py
│   └── export.py
└── api/
    └── v2.py
tests/
├── fixtures/
│   ├── codex/
│   └── copilot_cli/
├── test_models.py
├── test_codex_provider.py
├── test_copilot_cli_parser.py
├── test_copilot_cli_provider.py
├── test_registry.py
└── test_api_v2.py
scripts/
├── copilot_cli_format_inventory.py
├── build_copilot_fixture.py
└── verify_dual_providers.py
```

## 4. D0：脱敏 Fixture 和格式契约

### 4.1 Fixture 集

至少准备以下 Copilot Fixture：

| Fixture | 覆盖内容 |
|---|---|
| `simple` | 用户消息、纯文本助手回复 |
| `reasoning_tool` | reasoning、工具请求、成功结果、最终回复 |
| `tool_error` | 工具执行失败 |
| `abort` | 用户消息后中止，没有助手最终回复 |
| `resume` | shutdown/resume 后继续 |
| `attachment` | 文件附件和选区 |
| `subagent` | subagent started/completed/failed |
| `unknown_event` | 未识别事件 |
| `truncated_tail` | 最后一行不完整 |
| `identity_mismatch` | 目录、YAML、session.start ID 不一致 |

Fixture 只保留最小字段，正文使用“user text”“assistant text”等虚构内容。ID 使用
固定测试 UUID，路径使用 `/tmp/example`。

### 4.2 Fixture 生成脚本

`scripts/build_copilot_fixture.py` 必须：

- 默认 dry-run。
- 需要显式指定一个源会话和目标目录。
- 只保留选定事件类型和字段。
- 替换正文、路径、模型、ID 和时间。
- 重新映射 eventId、parentId、interactionId、turnId、toolCallId。
- 生成后运行隐私扫描，拒绝包含 home 路径、Token 模式或原始 UUID。

### 4.3 格式契约

建立 `docs/schemas/copilot-cli-v1.md`，记录：

- 顶层必填字段和允许的可选字段。
- 每种高层事件 data 字段。
- 关联键作用域。
- 未知字段前向兼容策略。
- 状态判定规则。

验收：所有 Fixture 可由结构盘点脚本读取，且不含本机真实值。

## 5. D1：统一模型

### 5.1 类型定义

实现：

```python
class ContentStatus(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    ERROR = "error"

class MessageStatus(str, Enum):
    COMPLETE = "complete"
    INTERRUPTED = "interrupted"
    ERROR = "error"

@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    title: str | None
    arguments_summary: str
    success: bool | None
    result_summary: str
    error_code: str | None
    file_edits: tuple[dict, ...]

@dataclass(frozen=True)
class Message:
    id: str
    role: str
    content: str
    timestamp: str | None
    reasoning: str
    tool_calls: tuple[ToolCall, ...]
    attachments: tuple[dict, ...]
    status: MessageStatus

@dataclass(frozen=True)
class SessionSummary:
    id: str
    provider: str
    source_id: str
    title: str
    workspace: str | None
    created_at: str | None
    updated_at: str | None
    content_status: ContentStatus
    has_transcript: bool
    turn_count: int | None
    capabilities: tuple[str, ...]
    source_fingerprint: str

@dataclass(frozen=True)
class SessionDetail:
    session: SessionSummary
    messages: tuple[Message, ...]
    relations: dict
    warnings: tuple[str, ...]
```

### 5.2 验证规则

- full 必须有 transcript capability。
- has_transcript=false 时 messages 必须为空。
- turn_count 不能为负。
- Provider ID 和稳定 ID 前缀必须一致。
- ToolCall success=false 时应有错误摘要或错误码。
- API 序列化不包含 source_id 和 fingerprint，除非本机管理员诊断。

### 5.3 兼容层

`legacy_adapter.py` 负责统一 Message 到旧 turn：

```python
{
    "user": "...",
    "assistant": "...",
    "reasoning": "...",
    "time": "...",
    "user_context": "...",
}
```

Provider 内禁止生成旧 turn 字段。

测试：模型组合、序列化、兼容输出、非法状态全部覆盖。

## 6. D2：CodexProvider

### 6.1 配置

```python
CodexProvider(
    session_root: Path,
    parser_version: str = "codex-v1",
    max_file_bytes: int = 100 * 1024 * 1024,
)
```

### 6.2 发现算法

伪代码：

```python
for path in sorted(session_root.rglob("*.jsonl")):
    rel = safe_relative_path(path, session_root)
    stat = path.stat()
    meta = load_session_meta(path)
    source_id = encode_codex_source_id(rel, meta.session_id)
    yield SessionSummary(
        id=stable_id("codex", source_id),
        source_id=source_id,
        title=metadata_name_or_short_filename,
        workspace=meta.cwd,
        created_at=timestamp_from_filename_or_meta,
        updated_at=mtime_to_iso(stat),
        content_status=FULL,
        has_transcript=True,
        turn_count=None,
        source_fingerprint=f"{stat.st_mtime_ns}:{stat.st_size}:codex-v1",
    )
```

发现阶段只读取 meta 和有限预览，不解析完整正文。

### 6.3 详情算法

1. Registry 把 stable ID 解析为已发现的 source ref。
2. 校验文件仍在 session_root 内。
3. 检查大小上限和 fingerprint。
4. 调用现有 `load_session(path)`。
5. 每个旧 turn 转换为用户 Message 和助手 Message。
6. reasoning 放入助手 Message.reasoning。
7. 当前工具摘要首版保留在 reasoning；后续可结构化为 ToolCall。
8. 计算真实 turn_count 并更新详情缓存。

### 6.4 关系

把当前这些函数迁入 Provider 或关系辅助类：

- `preferred_parent_map`
- `subagent_tree`
- `descendant_subagent_paths`

关系使用稳定 ID，不再使用相对文件路径。

### 6.5 Codex 测试

- 原 P0 parser 测试全部保留。
- 稳定 ID 确定性。
- session_root 路径逃逸拒绝。
- 重复 session_id 的文件级身份。
- subagent 多层树。
- 文件变更导致 fingerprint 失效。
- 超大文件和删除中的文件。

验收：旧页面可见内容与 P0 截图和 API 基线一致。

## 7. D3：Copilot CLI parser

### 7.1 解析入口

```python
parse_copilot_session(
    workspace_file: Path,
    events_file: Path,
    *,
    offset: int = 0,
    limit: int = 50,
    limits: ParseLimits,
) -> ParsedCopilotSession
```

### 7.2 安全限制

```python
ParseLimits(
    max_events_file_bytes=256 * 1024 * 1024,
    max_line_bytes=2 * 1024 * 1024,
    max_message_chars=2_000_000,
    max_tool_summary_chars=20_000,
    max_attachment_text_chars=100_000,
    max_events=2_000_000,
)
```

超过限制返回结构化 error/partial，不耗尽内存。

### 7.3 workspace.yaml 解析

优先选项：

1. 如果允许新增依赖，使用 `yaml.safe_load` 并限制文件大小。
2. 如果保持零新增依赖，实现只支持当前扁平标量结构的严格 parser；遇到嵌套或
   不支持语法立即报 unsupported，不自行猜测。

不能使用不安全的 YAML loader。

返回：

```python
CopilotWorkspace(
    id,
    cwd,
    git_root,
    branch,
    client_name,
    name,
    user_named,
    summary_count,
    fork_count,
    created_at,
    updated_at,
)
```

### 7.4 JSONL 流式读取

每行流程：

1. 检查字节长度。
2. UTF-8 解码和 JSON 解析。
3. 验证顶层是 object。
4. 读取 type/data/id/timestamp/parentId。
5. 未知 type 保存轻量计数，不报致命错误。
6. 非最后一行损坏：记录 warning，状态 partial。
7. 正在写入文件的最后一行损坏：标记 transient_tail，不打印内容。

### 7.5 内部索引

```python
events_by_id: dict[event_id, EventRef]
interactions: OrderedDict[interaction_id, InteractionBuilder]
turn_to_interaction: dict[turn_id, interaction_id]
tool_requests: dict[(session_id, tool_call_id), ToolBuilder]
agent_events: dict[agent_id, list[EventRef]]
```

只保存关联和构建详情所需数据。Hook 和 model.* 只统计，不保存大 payload。

### 7.6 处理顺序

第一遍：

- 读取 session.start，验证身份。
- 收集 user.message，建立 InteractionBuilder。
- 收集 assistant.message：
  - 用 interactionId 归入 interaction。
  - 记录 turnId → interactionId。
  - 建立 toolRequests。
- 收集 tool start/complete，按 toolCallId 暂存。
- 收集 abort/error/turn_end。

第二步关联：

- 用 turnId 把工具事件归入 interaction。
- 用 toolCallId 合并 request/start/complete。
- 用 parentToolCallId 构建嵌套工具关系。
- 处理缺失和重复，写 warning。

第三步输出：

- 按首个用户事件在文件中的顺序排序 interaction。
- 应用 offset/limit。
- 构造用户和助手 Message。

### 7.7 InteractionBuilder

```python
class InteractionBuilder:
    interaction_id: str
    user_events: list[Event]
    assistant_events: list[Event]
    system_events: list[Event]
    tool_calls: list[ToolBuilder]
    aborted: bool
    errors: list[ErrorEvent]
```

通常一个 interaction 有一个 user.message；出现多个时按顺序保留并记录 warning，
不能覆盖。

### 7.8 助手内容合并

按事件顺序：

- `reasoningText` 非空：追加 reasoning 片段，连续完全重复片段去重。
- `content` 非空：追加可见内容片段。
- `toolRequests`：只建立结构，不把 JSON 塞入正文。
- reasoningOpaque：仅记录存在性。
- reasoningBlocks：首版用于交叉检查；若 reasoningText 存在则不重复展示。

片段之间使用明确分隔，不盲目字符串相加。是否存在累积快照通过 Fixture 测试：
若后一个 content 完整包含前一个且事件语义证明是快照，则保留最长；否则分段保留。

### 7.9 工具合并

```python
ToolBuilder(
    request_event,
    start_event,
    complete_event,
)
```

状态：

| 条件 | 状态 |
|---|---|
| request/start/complete 且 success=true | complete |
| complete success=false 或有 error | error |
| request/start 无 complete | interrupted |
| start/complete 无 request | orphan，保留 warning |

参数摘要使用允许字段和字符上限；文件内容、diff、命令输出不默认完整返回。

### 7.10 消息状态

- 有可见助手内容且 interaction 正常结束：complete。
- 用户存在但无助手，或 abort：interrupted。
- session.error 关联到 interaction：error。
- 只有 reasoning/tool 但没有可见 content：助手 Message 仍存在，但 UI 显示
  “无最终文本回复”，不能丢弃工具过程。

### 7.11 Parser 测试

逐个 Fixture 断言：

- interaction 数量。
- 用户和助手文本。
- reasoning 去重。
- tool request/start/complete 关联。
- 工具失败。
- abort/error。
- 附件截断。
- resume 不重复产生会话。
- 未知事件向前兼容。
- 尾行截断。
- 超限保护。

## 8. D4：CopilotCLIProvider

### 8.1 配置

```python
CopilotCLIProvider(
    session_root=Path("~/.copilot/session-state").expanduser(),
    parser_version="copilot-cli-v1",
    limits=ParseLimits(...),
)
```

### 8.2 发现

对 `session_root/*`：

1. 忽略点目录和 lock 文件。
2. 检查 events.jsonl。
3. 读取有限大小的 workspace.yaml。
4. 流式寻找第一条 session.start，不读取完整正文。
5. 三方校验 ID。
6. 统计 user.message 数量作为 turn_count；结果可缓存。
7. 生成 fingerprint。

### 8.3 稳定 ID

```text
copilot-cli:<base64url(session-uuid)>
```

只有 Registry 保存解码后的 source ref。API 不接收绝对路径。

### 8.4 详情

- 检查当前 fingerprint。
- 调用 parser。
- 把 ParsedCopilotSession 转换为统一模型。
- 如果文件在解析时增长，允许使用开始时的 stat 快照并标记 stale；下次请求刷新。
- parser warning 映射成诊断码，不返回字段原文。

### 8.5 能力

首版：

```text
transcript
reasoning
tools
attachments
metadata
search_content
export
```

subagent_relations 在第二阶段验证后开启。

## 9. D5：Registry 与 Service

### 9.1 注册

```python
registry = SessionRegistry([
    CodexProvider(config.codex_session_root),
    CopilotCLIProvider(config.copilot_session_root),
    existing_vscode_provider,
])
```

本专项测试必须能够只注册前两个 Provider，避免 VS Code 环境依赖。

### 9.2 刷新

- Provider discover 返回 iterator。
- Registry 在临时 dict 构造完整快照。
- 检查稳定 ID 冲突。
- 成功后一次性替换当前快照。
- 单 Provider 失败保留其旧快照并标记 stale。

### 9.3 SessionService

```python
list_sessions(identity, filters, page)
get_session(identity, stable_id, page)
update_metadata(identity, stable_id, patch)
get_relations(identity, stable_id)
search(identity, query, filters)
export(identity, stable_id, format)
```

所有方法第一步都解析身份和允许 ID 集合。

## 10. D6：metadata 和权限迁移

### 10.1 Codex 旧 Key

旧相对路径通过 CodexProvider 的公开迁移函数转换为稳定 ID。找不到的路径保留在
`migration.unresolved`，不能静默删除。

### 10.2 Copilot metadata

Copilot 会话首次发现后即可写 Viewer metadata：

- 自定义名称。
- 标签和分类。
- 置顶和归档。
- 手工 reference。

这些操作只修改 Viewer metadata，不修改 workspace.yaml。

### 10.3 权限

publicSessions 和 Token session 列表都迁移成稳定 ID。搜索、详情和导出测试必须
包含“一个 Token 只能访问 Codex，另一个只能访问 Copilot”的交叉用例。

## 11. D7：API 和前端

### 11.1 API

```text
GET   /api/v2/providers
GET   /api/v2/sessions
GET   /api/v2/sessions/<id>
PATCH /api/v2/sessions/<id>/metadata
GET   /api/v2/search
GET   /api/v2/export/<id>
```

列表过滤：

```text
provider=codex|copilot-cli
workspace=<exact>
content_status=full|partial|error
category=<value>
tag=<value>
archived=0|1
offset=<int>
limit=<1..200>
```

### 11.2 前端

- 来源增加 Copilot CLI。
- 卡片显示 `CDX` 或 `CPL` 标识。
- Copilot 详情按 interaction 展示。
- reasoning 继续折叠。
- ToolCall 使用结构化折叠面板，显示成功/失败。
- 附件和权限摘要默认折叠。
- interrupted/error interaction 有显式状态。
- 操作按钮由 capabilities 控制。

### 11.3 旧 API

兼容期内：

- `/api/sessions` 返回 Codex 旧格式。
- 旧详情只支持 Codex。
- 新前端不再调用旧 API。
- 响应增加 Deprecation/Sunset 说明。

## 12. D8：搜索和导出

### 12.1 搜索构建

Codex：

- 标题、标签、用户、助手、reasoning。

Copilot：

- 标题、标签、user.content、assistant.content。
- reasoning、工具摘要是否索引由配置决定。
- 不索引 hook/model snapshot/opaque reasoning。

搜索结果必须包含 stable_id、provider、interaction/message index、match_field 和脱敏
snippet。

### 12.2 导出

Markdown 示例结构：

```markdown
# Session title

- Provider: Copilot CLI
- Workspace: ...
- Status: full

## Interaction 1

### User
...

### Assistant
...

<details><summary>Reasoning</summary>...</details>

#### Tools
- tool name: success
```

JSON 直接使用统一模型，省略内部 source_id、fingerprint 和绝对源路径。

## 13. 自动化测试矩阵

| 测试文件 | 重点 |
|---|---|
| `test_models.py` | 状态组合、序列化、兼容层 |
| `test_codex_provider.py` | 发现、详情、关系、fingerprint、安全路径 |
| `test_copilot_cli_parser.py` | 所有事件和关联规则 |
| `test_copilot_cli_provider.py` | YAML、身份、发现、状态、缓存 |
| `test_registry.py` | 双 Provider、冲突、错误隔离、刷新 |
| `test_metadata_migration.py` | 路径到稳定 ID、幂等和回滚 |
| `test_access.py` | 跨 Provider 白名单 |
| `test_api_v2.py` | 列表、详情、筛选、分页、错误 |
| `test_search.py` | 权限先行和重复内容排除 |
| `test_export.py` | JSON/Markdown 和敏感字段排除 |

### 13.1 真实数据只读集成测试

默认跳过，通过环境变量显式开启：

```bash
RUN_LOCAL_SESSION_TESTS=1 python3 -m unittest tests/test_local_sources.py -v
```

只断言：

- 数量大于等于已知最小值。
- JSONL 可读取。
- schema 已识别。
- 不修改源文件 mtime、size 和 hash。

不在测试输出中打印标题或正文。

## 14. 验证脚本

新增 `scripts/verify_dual_providers.py`，输出：

```json
{
  "tests_ok": true,
  "compile_ok": true,
  "providers": {
    "codex": {"sessions": 3, "errors": 0},
    "copilot-cli": {"sessions": 8, "errors": 0}
  },
  "api": {
    "local_status": 200,
    "remote_unauthorized_status": 403
  },
  "source_integrity": {
    "modified_files": 0
  }
}
```

只输出计数和状态。

## 15. 性能和资源验证

针对最大约 17.3 MiB 的现有 Copilot 会话测量：

- discover 不读取全部正文。
- 首次详情解析耗时和峰值内存。
- 缓存后二次加载耗时。
- offset/limit 是否避免构造无关页面 Message。
- 15 万字节单行能在限制内安全处理。

建议目标：

| 操作 | 当前规模目标 |
|---|---:|
| 双 Provider 缓存列表 P95 | < 200 ms |
| 单个 20 MiB Copilot 首次解析 | < 3 s |
| 缓存详情 | < 200 ms |
| 峰值额外内存 | < 文件大小的 3 倍 |

目标需要在本机实测后调整，不能作为格式正确性的替代。

## 16. 实施顺序和提交边界

### D0

调查报告、结构脚本、脱敏 Fixture 和格式契约。

### D1

统一模型与 legacy adapter，不改变 API。

### D2

CodexProvider 和关系迁移，Registry 接管 Codex。

### D3

Copilot parser，仅运行 Fixture 测试，不接生产 API。

### D4

CopilotCLIProvider 和本机只读验证。

### D5

Registry/Service 双 Provider 聚合。

### D6

metadata 和访问策略稳定 ID 迁移。

### D7

API 与前端切换。

### D8

搜索、导出、性能、安全和发布文档。

每个阶段独立提交，禁止把 metadata 迁移和 Copilot parser 首次实现放在同一提交。

## 17. 回滚策略

- D1–D5：通过 Git 回滚；不涉及原始数据写入。
- D6：恢复带时间戳的 metadata/access 备份。
- D7：配置切回旧前端 API。
- D8：搜索缓存和导出产物可删除重建。
- Codex/Copilot 原始文件未修改，无需源数据回滚。

## 18. 完成定义

专项改造只有同时满足以下条件才算完成：

- CodexProvider 完全取代 app.py 中的直接扫描。
- CopilotCLIProvider 按真实格式解析全部 8 个当前会话。
- 两个 Provider 输出统一模型并由 Registry 管理。
- 111 条当前用户消息能按 interaction 构造，不因无最终回复而丢失。
- 所有当前工具调用在单会话范围正确闭环。
- Hook 和 model.* 不造成消息与搜索重复。
- metadata、权限、搜索和导出跨 Provider 一致。
- 原始数据的 mtime、size 和 hash 在集成测试前后不变。
- 自动化测试、编译、前端语法、API 权限和性能验证通过。
- 文档和脚本可由后续开发者复现。
