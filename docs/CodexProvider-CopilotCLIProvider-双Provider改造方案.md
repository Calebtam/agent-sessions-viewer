# CodexProvider 与 CopilotCLIProvider 双 Provider 改造方案

> 文档类型：专项总体设计  
> 版本：1.0  
> 日期：2026-10-23  
> 输入证据：[Copilot CLI 真实格式调查报告](CopilotCLI-真实格式调查报告.md)  
> 配套文档：[双 Provider 详细实施方案](CodexProvider-CopilotCLIProvider-详细实施方案.md)

## 1. 方案范围

本方案只解决两个正文来源：

1. `CodexProvider`：读取 `~/.codex/sessions/**/*.jsonl`。
2. `CopilotCLIProvider`：读取 `~/.copilot/session-state/<id>/workspace.yaml` 和
   `events.jsonl`。

现有 VS Code Chat 索引功能继续保留，但不属于本专项的设计和实施主线。不能把
Copilot CLI 会话视为 VS Code 索引正文，因为真实 ID 对比没有交集。

## 2. 目标

- 在不重写现有 Codex 解析规则的前提下，把 Codex 完整封装为 Provider。
- 根据已验证的真实格式实现独立的 Copilot CLI 解析器。
- 两个 Provider 都输出同一种 Session 和 Message 模型。
- 统一列表、详情、分页、metadata、关系、权限、搜索和导出入口。
- 保留 Codex 的 Thinking、工具调用和 subagent 能力。
- 正确显示 Copilot 的用户消息、推理、可见回复、工具执行、权限和附件摘要。
- 任何源文件始终只读。

## 3. 不采用的方案

### 3.1 不把 Codex parser 改成通用 JSONL parser

两种格式虽然都是 JSONL，但结构不同：

| 维度 | Codex | Copilot CLI |
|---|---|---|
| 顶层事件 | `event_msg`、`response_item` 等 | `user.message`、`assistant.message` 等 |
| 会话元数据 | `session_meta` | `workspace.yaml + session.start` |
| 用户/助手关联 | 事件顺序 | `interactionId` |
| 工具关联 | function/custom tool 事件 | `turnId + toolCallId` |
| 推理 | reasoning/agent_reasoning | reasoningText/reasoningBlocks |
| 子 Agent | parent_thread_id/source | subagent.*、agentId、parentToolCallId |

共享原始 parser 会把来源差异变成大量条件分支，降低可靠性。正确方式是两个
独立 parser，在统一模型层合流。

### 3.2 不先重写 Codex

现有 `parser.py` 已经过 P0 测试。CodexProvider 只负责封装发现、身份、缓存和模型
转换；除非新增 Fixture 证明有缺陷，否则不改变原始事件解析语义。

### 3.3 不用文件路径作为公共会话 ID

文件路径会泄露内部结构，也容易产生路径穿越风险。公共 API 只使用稳定 ID，
Provider 内部保存 source_id 到真实路径的白名单映射。

## 4. 双 Provider 架构

```text
                      SessionService
                ┌──────────┴──────────┐
                │                     │
         ProviderRegistry       Metadata/Access
          ┌─────┴─────┐
          │           │
  CodexProvider   CopilotCLIProvider
          │           │
  codex_parser    copilot_cli_parser
          │           │
  *.jsonl         workspace.yaml + events.jsonl
```

### 4.1 公共层

- `models.py`：SessionSummary、SessionDetail、Message、ToolCall。
- `registry.py`：Provider 注册、稳定 ID 白名单、刷新和错误隔离。
- `services/sessions.py`：metadata 合并、权限、分页和关系。
- `services/search.py`：权限先行的跨 Provider 搜索。
- `services/export.py`：统一 Markdown/JSON 导出。

### 4.2 来源层

- `providers/codex.py`：Codex 文件发现和模型适配。
- `providers/copilot_cli.py`：Copilot 会话发现和详情加载。
- `parsers/copilot_cli.py`：流式事件解析和关联。
- 原 `parser.py` 暂时保留；后续可更名为 `parsers/codex.py`。

## 5. 统一模型

### 5.1 SessionSummary

```json
{
  "id": "copilot-cli:<url-safe-id>",
  "provider": "copilot-cli",
  "title": "展示标题",
  "workspace": "/path/to/project",
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "content_status": "full",
  "has_transcript": true,
  "turn_count": 12,
  "capabilities": [
    "transcript",
    "metadata",
    "search_content",
    "export"
  ]
}
```

### 5.2 Message

```json
{
  "id": "provider-message-id",
  "role": "assistant",
  "kind": "message",
  "timestamp": "ISO-8601",
  "content": "可见回复",
  "reasoning": "可显示推理",
  "tool_calls": [
    {
      "id": "tool-call-id",
      "name": "tool-name",
      "arguments_summary": "...",
      "success": true,
      "result_summary": "...",
      "file_edits": []
    }
  ],
  "attachments": [],
  "status": "complete"
}
```

### 5.3 Provider 能力

| 能力 | Codex | Copilot CLI |
|---|---:|---:|
| transcript | 是 | 是 |
| reasoning | 是 | 是 |
| tools | 是 | 是 |
| attachments | IDE context | 是 |
| automatic subagent relations | 是 | 第二阶段 |
| resume command | 是 | 需要确认 CLI 命令 |
| metadata/search/export | 是 | 是 |

前端根据能力显示按钮，不根据 Provider 名称硬编码。

## 6. CodexProvider 设计

### 6.1 发现

- 扫描配置根目录下的 `*.jsonl`。
- 使用 `load_session_meta()` 读取 session_id、cwd、parent_thread_id。
- 使用 `load_session_preview()` 生成有限预览。
- fingerprint：相对路径、size、mtime_ns、parser_version。
- 稳定 ID：Provider 前缀加 URL 安全编码的来源标识；避免绝对路径。

### 6.2 详情

- 调用现有 `load_session()`。
- 把旧 turn 映射为统一 Message。
- 保留 user_context、reasoning 和工具摘要。
- 使用现有 parent_thread_id 关系构建 subagent 树。

### 6.3 回归约束

以下行为不得改变：

- 隐藏环境消息。
- Guardian approval 摘要。
- Thinking 折叠内容。
- function/custom tool 摘要。
- master/subagent/reference 关系。

## 7. CopilotCLIProvider 设计

### 7.1 发现

候选会话目录必须同时满足：

- 目录名可作为来源标识。
- 存在 `events.jsonl`。
- 存在 `workspace.yaml`，或 events 中存在可用 `session.start`。
- `session.start.data.sessionId` 与目录身份一致；不一致则状态为 error。

Summary 取值优先级：

| 字段 | 第一来源 | 回退来源 |
|---|---|---|
| title | workspace.yaml.name | 稳定 ID 短形式 |
| workspace | workspace.yaml.cwd | session.start.context.cwd |
| created_at | workspace.yaml.created_at | session.start.startTime |
| updated_at | workspace.yaml.updated_at | events 文件 mtime |
| session ID | 三方校验结果 | 不允许猜测 |

### 7.2 流式解析

两阶段解析更可靠：

1. 第一遍建立轻量索引：event id/type、interactionId、turnId、toolCallId、偏移。
2. 第二遍按请求页构造 Message，避免长期保留所有大字段。

当前规模也可以首版单遍构造，但必须设置单行和单文件上限，并允许最后一行写入中
导致的临时 JSON 错误。

### 7.3 Interaction 构造

```text
user.message.interactionId
       │
       ├── assistant.message.interactionId
       │        ├── reasoningText
       │        ├── content
       │        └── toolRequests[*].toolCallId
       │
       └── assistant.message.turnId
                ├── tool.execution_start.turnId
                └── tool.execution_complete.turnId
```

规则：

- 每个 user.message 创建一个用户交互。
- 同 interactionId 的 assistant.message 按文件顺序加入。
- 非空 reasoningText 合并为推理片段。
- 非空 content 合并为可见助手回复。
- reasoningOpaque 只保存存在性，不直接显示。
- toolCallId 在单个会话范围内关联 request/start/complete。
- 缺少 assistant 的用户消息仍保留，状态标记 interrupted/partial。

### 7.4 工具与权限

- 工具参数和结果按字符数限制摘要，完整内容按需加载。
- 文件编辑只展示路径、kind 和有限 diff 摘要。
- 权限事件展示类型和结果，不默认展示完整命令或新文件内容。
- Hook 和 model.* 不进入正常正文，避免内容重复。

### 7.5 附件

- 保存附件类型、显示名、路径和选区摘要。
- 嵌入文本设置大小限制。
- 默认 UI 折叠；搜索是否包含附件文本由配置决定。
- 导出前提示附件可能包含私有代码。

### 7.6 resume、fork 和 subagent

- `session.resume` 不创建新会话，只产生生命周期事件。
- fork 会话保持独立稳定 ID；复制历史去重只在单会话内部进行。
- subagent 首版作为工具调用详情展示。
- 第二阶段使用 agentId、parentToolCallId 和 subagent.* 构建关系节点。

## 8. 状态判定

### 8.1 Codex

- 文件可解析且存在有效消息：full。
- 部分非法行但仍可恢复消息：partial。
- 文件存在但无可识别格式：error。

### 8.2 Copilot CLI

- workspace/session 身份一致，JSONL 可读，交互可构建：full。
- 最后一行临时不完整、用户交互被中止或部分事件缺失：partial。
- 不支持的 schema version、身份冲突或主体格式错误：error。

状态必须带稳定诊断码，不能只返回自由文本。

## 9. metadata、权限和关系

- metadata Key 统一使用稳定 ID。
- 两种 Provider 都允许重命名、标签、分类、置顶和归档。
- 原始文件永不写入。
- Guest、Viewer、Admin 白名单统一保存稳定 ID。
- 自动关系和人工 reference 分开。
- 权限过滤必须发生在列表、详情、搜索、导出之前。

## 10. 搜索设计

统一搜索文档字段：

```text
session_id
provider
title
workspace
metadata
user_content
assistant_content
reasoning（可配置）
tool_summary（可配置）
```

默认不索引：

- Copilot hook input/output。
- model.messages_snapshot。
- reasoningOpaque。
- 完整权限命令和 diff。
- 超长工具结果。

搜索结果显示 Provider、interaction/turn 位置、匹配字段和摘要。

## 11. 导出设计

Markdown 结构：

```text
标题和来源
工作区和时间
正文状态
用户消息
助手回复
折叠/可选推理
工具调用摘要
附件摘要
```

JSON 使用统一模型。导出不能包含访问 Token、内部缓存字段、Hook 重复内容或未选择
的完整工具输出。

## 12. 缓存和性能

### 12.1 列表缓存

- Codex fingerprint：文件 mtime_ns + size。
- Copilot fingerprint：workspace.yaml 和 events.jsonl 的 mtime_ns + size。
- Provider 版本变化强制失效。

### 12.2 详情缓存

Key：

```text
provider + stable_id + fingerprint + parser_version
```

Copilot 文件可达十几 MiB，并存在 15 万字节的单行，必须流式读取。列表发现不能
解析全部正文；turn_count 可以通过轻量事件统计缓存获得。

## 13. 安全要求

- 只读打开所有源文件。
- Registry 只接受已发现稳定 ID。
- 对工具参数、权限、附件和日志执行统一截断。
- API 错误不返回源路径或正文。
- 默认仅监听 localhost。
- 远程用户无权访问的会话不能参与搜索或生成摘要。
- 测试 Fixture 必须脱敏，不能直接提交真实 events.jsonl。

## 14. 实施阶段

```text
D0 保存 Copilot 格式证据与 Fixture
 → D1 统一模型
 → D2 CodexProvider 封装
 → D3 CopilotCLI parser
 → D4 CopilotCLIProvider
 → D5 Registry/Service 聚合
 → D6 metadata/权限稳定 ID
 → D7 前端、搜索和导出
 → D8 性能、安全与发布
```

CodexProvider 和 Copilot parser 可以在 D1 完成后并行编码，但接入统一 API 必须
经过同一 Registry 和权限层。

## 15. 验收标准

- 当前 Codex 会话的消息、Thinking、工具和关系无回归。
- 8 个真实 Copilot CLI 会话都能被发现。
- 111 条当前用户消息可以进入正确 interaction。
- 用户、助手和工具通过已验证的关联键组合。
- 中止或错误 interaction 不被静默丢弃。
- Copilot hook/model 重复内容不会进入正常消息或搜索。
- 两个 Provider 使用同一套 metadata、权限、搜索和导出接口。
- 所有自动化测试和结构盘点脚本通过。

## 16. 结论

当前已具备直接实现 CopilotCLIProvider 的真实格式证据，不再需要把 Copilot 解析
建立在猜测上。工程上应保持 Codex parser 与 Copilot CLI parser 独立，通过统一
模型、Registry 和 Service 合流。这样既保护现有 Codex 行为，也能准确表达
Copilot 的 interaction、工具链、resume 和 subagent 语义。
