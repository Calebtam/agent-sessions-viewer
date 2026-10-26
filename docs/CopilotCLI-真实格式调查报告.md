# Copilot CLI 本机真实会话格式调查报告

> 状态：调查完成，可进入 Provider 实现设计  
> 日期：2026-10-23  
> 环境：Ubuntu，本机 `~/.copilot/session-state`  
> 方法：只读流式扫描；只输出结构、类型、数量和关联完整性，不输出正文或 ID

## 1. 调查目标

确定 Copilot CLI 的真实会话位置、文件组织、事件模型、消息字段、工具调用关联和
会话元数据来源，为 `CopilotCLIProvider` 提供真实证据。调查不假设其格式与
Codex 相同，也不把 VS Code Chat 索引当成 Copilot CLI 正文。

## 2. 数据位置和目录结构

本机确认目录：

```text
~/.copilot/
├── session-state/
│   ├── .session-operation-locks/
│   └── <session-uuid>/
│       ├── events.jsonl
│       ├── workspace.yaml
│       ├── checkpoints/index.md
│       ├── .workspace-fork.lock
│       ├── inuse.<pid>.lock / .hold（部分会话）
│       └── files/（部分会话的工作文件快照）
├── logs/
└── ide/
```

当前发现 8 个会话目录，8 个都包含 `events.jsonl` 和 `workspace.yaml`。

| 指标 | 结果 |
|---|---:|
| 会话目录 | 8 |
| JSONL 事件行 | 31,253 |
| 无法解析的 JSON 行 | 0 |
| 最小 events 文件 | 约 212 KiB |
| 最大 events 文件 | 约 17.3 MiB |
| 单行最大长度 | 约 151 KiB |

结论：读取器必须逐行流式解析，不能一次性加载整个文件，也不能假设单行很小。

## 3. workspace.yaml

8 个文件都采用相同的顶层扁平字段：

```text
id
cwd
git_root
branch
client_name
name
user_named
summary_count
fork_count
created_at
updated_at
```

用途设计：

- `id`：会话来源 ID；需要与目录名和 `session.start.data.sessionId` 交叉验证。
- `cwd`：工作目录。
- `git_root`、`branch`：仓库上下文。
- `name`：优先展示标题。
- `user_named`：说明标题是否由用户命名。
- `created_at`、`updated_at`：会话列表排序时间。
- `summary_count`、`fork_count`：诊断信息，不直接等同消息数量。

不应把 `checkpoints/index.md` 或 `files/` 当作聊天正文；它们分别更接近检查点
索引和会话工作文件快照。

## 4. events.jsonl 顶层格式

31,253 条事件的顶层结构稳定：

```json
{
  "type": "user.message",
  "data": {},
  "id": "event-id",
  "timestamp": "timestamp",
  "parentId": "previous-or-parent-event-id"
}
```

部分子 Agent 事件额外含 `agentId`。

| 字段 | 当前类型 | 用途 |
|---|---|---|
| `type` | string | 事件类型 |
| `data` | object | 各事件载荷 |
| `id` | string | 事件标识 |
| `timestamp` | string | 事件时间 |
| `parentId` | string/null | 事件因果链 |
| `agentId` | string，可选 | 子 Agent 归属 |

每个会话第一条 `session.start.data.sessionId` 都与所在目录 UUID 一致。

## 5. 已确认的事件类型

### 5.1 会话生命周期

```text
session.start
session.resume
session.shutdown
session.error
session.info
session.model_change
session.permissions_changed
abort
```

关键字段：

- `session.start`：sessionId、格式 version、producer、copilotVersion、startTime、
  selectedModel、reasoningEffort、context.cwd。
- `session.resume`：resumeTime、context.cwd、eventCount、eventsFileSizeBytes。
- `session.shutdown`：模型、Token、API 时长、代码改动与 Agent 指标。
- `session.error`：errorType、message、statusCode。

列表元数据优先来自 `workspace.yaml`；`session.start` 用于校验身份和补充模型信息。

### 5.2 用户和系统消息

`user.message` 当前字段：

```text
content
transformedContent
attachments（部分事件）
messageId
supportedNativeDocumentMimeTypes
delivery
interactionId
turnId
parentAgentTaskId
source（少量事件）
```

调查结果：

- 111 条用户消息的 `content` 和 `transformedContent` 均非空。
- 98 条用户事件带附件，共 106 个附件。
- 附件结构出现文件路径、展示名、选区、文本或 taggedFilesEntry。
- `parentAgentTaskId` 在 111 条用户消息中均为非空字符串，但不能据此代替
  `interactionId` 进行普通对话分组。

`system.message` 字段包括 role、content、contentBlocks、interactionId、metadata。
默认 Viewer 不应把系统消息显示为普通用户问题，可作为可折叠上下文。

### 5.3 助手消息

`assistant.message` 当前字段：

```text
messageId
originatingMessageId
model
content
toolRequests
interactionId
turnId
rte
apiCallId
reasoningOpaque（部分事件）
reasoningText（部分事件）
reasoningBlocks（部分事件）
serverTools（部分事件）
parentToolCallId（子调用）
```

共 2,557 条助手消息，其中：

- 190 条 `content` 非空。
- 1,334 条 `reasoningText` 非空。
- 1,299 条 `reasoningOpaque` 非空。
- `toolRequests` 总计 3,161 条。

说明一个用户交互会产生多个助手步骤：推理、工具请求、工具结果之后的继续推理，
最后才可能出现非空可见回复。不能把每个 `assistant.message` 都当作独立用户轮次。

## 6. 正确的分组和关联规则

### 6.1 用户交互分组

`interactionId` 是用户消息与助手消息的主要关联键。

当前样本统计：

| 指标 | 数量 |
|---|---:|
| interaction 分组 | 118 |
| 含用户消息 | 111 |
| 含助手消息 | 105 |
| 同时含用户与助手消息 | 102 |

缺少助手消息的用户交互与 abort、error、未完成会话有关，因此解析器必须允许
“只有用户消息”的部分会话，不能丢弃。

### 6.2 助手步骤和工具调用

`assistant.message.turnId` 与以下事件关联：

- `assistant.turn_start`
- `assistant.turn_end`
- `tool.execution_start.turnId`
- `tool.execution_complete.turnId`

工具调用使用 `toolCallId` 串联：

```text
assistant.message.toolRequests[*].toolCallId
                │
                ▼
tool.execution_start.toolCallId
                │
                ▼
tool.execution_complete.toolCallId
```

按每个会话分别检查，所有工具请求都存在 start 和 complete，没有发现孤立请求、
缺少完成事件或无请求的执行事件。由于 fork/resume 会复制历史，`toolCallId`
不能假定在所有会话之间全局唯一；缓存和关联 Key 必须包含会话 ID。

### 6.3 parentId

`parentId` 表示事件因果链，但实际链条中穿插 hook、permission、resume、error 和
工具事件。它适合保留原始顺序、调试和恢复父子关系，不适合单独作为 UI turn
分组规则。推荐优先级：

1. `interactionId`：用户交互。
2. `turnId`：助手模型步骤及其工具执行。
3. `toolCallId`：工具请求和结果。
4. `parentId`：因果补充与异常恢复。

## 7. 工具、权限与 Hook

### 7.1 工具执行

`tool.execution_start`：

```text
toolCallId, toolName, arguments, turnId, model, toolTitle,
shellToolInfo, parentToolCallId
```

`tool.execution_complete`：

```text
toolCallId, model, interactionId, turnId, success, result,
toolTelemetry, shellExecution, fileEdits, error, parentToolCallId
```

总计 3,161 次执行：3,114 次成功并含 result，47 次含 error。Provider 应保留
success、简化结果和文件编辑摘要，并对超长输出截断；不能默认把完整工具结果
加载到列表预览。

### 7.2 权限事件

`permission.requested` 和 `permission.completed` 各 2,100 条。请求可能包含命令、
路径、diff、新文件内容或 URL，因此属于高敏感数据。默认详情页只展示权限类型和
结果；完整命令或 diff 必须遵守与工具输出相同的截断和权限策略。

### 7.3 Hook

`hook.start` 和 `hook.end` 各 6,240 条，是数量最大的事件类型之一。Hook input
可能重复 prompt、工具参数、结果和 transcriptPath。首版 Provider 不应把 Hook
渲染为消息，也不应为搜索重复索引 Hook 内容；只用于诊断和补充错误上下文。

## 8. 子 Agent 与模型事件

已确认子 Agent 事件：

```text
subagent.started
subagent.configured
subagent.selected
subagent.deselected
subagent.completed
subagent.failed
```

事件包含 toolCallId、Agent 名称/类型、模型、执行模式、耗时和工具调用数。
`parentToolCallId` 和顶层 `agentId` 可以用于生成子 Agent 关系。首版可以先保留
为工具调用详情，第二步再映射为关系树。

仅一个会话出现 `model.*` 低层事件，包括模型调用、响应、消息快照和 Token 使用。
这些事件可能包含请求消息快照，容易与高层 `assistant.message` 重复。正常会话
正文应使用高层事件；`model.*` 仅用于诊断，不能重复展示或索引。

## 9. 与 VS Code Chat 索引的关系

调查对比了：

- 8 个 Copilot CLI 会话目录 ID。
- 当前 VS Code Chat 索引中的 sessionId。
- VS Code 索引来源 Key 的末段标识。

交集均为 0。因此当前没有证据表明 `~/.copilot/session-state` 中的 8 个会话就是
P2 展示的 40 条 VS Code Chat 索引正文。

设计结论：

- `CopilotCLIProvider` 和 `VSCodeChatProvider` 必须独立。
- 不得依据标题、工作区或时间相近自动合并。
- 未来如发现显式映射字段，应以测试验证后增加“reference/duplicate”关系，而
  不是直接覆盖稳定 ID。

VS Code 扩展目录中的 `session-store.db` 当前 sessions、turns、session_files 和
session_refs 表均为空，不能作为本机 Copilot CLI 正文来源。

## 10. CopilotCLIProvider 的确定性解析规则

### 10.1 会话摘要

- source_id：经三方一致性校验后的会话 UUID。
- title：`workspace.yaml.name`；缺失时使用脱敏的短 ID。
- workspace：`workspace.yaml.cwd`。
- created_at / updated_at：workspace.yaml 时间。
- content_status：
  - events 可读且存在用户/助手内容：`full`。
  - events 截断、存在非法行或未闭合关键事件：`partial`。
  - 文件存在但不支持版本：`error`。
- turn_count：用户 `interactionId` 数量；未完成用户交互仍计入。

### 10.2 消息构造

对每个 interaction：

1. 创建用户 Message，使用 `content` 作为显示内容。
2. `transformedContent` 与 content 不同时作为折叠的转换上下文，不替换原问题。
3. 按原始事件顺序收集属于该 interaction 的助手步骤。
4. `reasoningText` 映射为 reasoning；`reasoningOpaque` 不直接展示。
5. 非空 `content` 按顺序合并为助手可见回复。
6. 通过 turnId/toolCallId 附加工具请求、结果和错误。
7. abort/error 产生结构化状态，不伪造助手回复。

### 10.3 默认忽略或诊断专用

- `hook.*`：不显示、不搜索。
- `model.*`：避免与高层消息重复。
- `system.message`：默认折叠。
- `permission.*`：摘要显示。
- `session.*`：提供元数据和错误状态。

## 11. 仍需通过 Fixture 验证的边界

- 一个 interaction 内多个非空 assistant content 是拼接还是分段展示。
- resume/fork 后复制历史如何去重。
- 子 Agent 的 interaction 是否应进入主会话正文或独立关系节点。
- transformedContent 的隐私和展示策略。
- attachments 中嵌入文本的大小限制与导出策略。
- reasoningBlocks 与 reasoningText 的优先级。
- events 正在写入时最后一行不完整的容错。

这些问题不阻止首版实现，但必须通过脱敏 Fixture 覆盖，不能在解析器中静默假设。

## 12. 可复用调查命令

```bash
python3 scripts/copilot_cli_format_inventory.py
python3 scripts/copilot_cli_format_inventory.py --full-schema
```

脚本只输出事件数量、字段名、字段类型和关联完整性，不输出会话 ID、标题、正文、
工具参数或 Token。

## 13. 调查结论

Copilot CLI 的真实正文格式已得到足够证据：每个会话由 `workspace.yaml` 和
`events.jsonl` 组成，事件顶层结构稳定，用户/助手/工具分别可以通过
`interactionId → turnId → toolCallId` 可靠关联。该格式与 Codex JSONL 明显不同，
必须实现独立的 `CopilotCLIProvider`；二者只在统一领域模型之后合流。
