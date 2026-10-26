# P2 VS Code Chat 索引集成记录

[English](p2-index-integration.md) | 中文

完成日期：2026-10-23。

## 已验证的数据源格式

当前 8 个 `chat.ChatSessionStore.index` 的 Value 都采用 JSON 版本 1，顶层字段
为 `version` 和 `entries`。`entries` 是一个对象，其 Key 是来源特定的会话标识。
8 个工作区中共发现 40 条记录。每条记录都具有相同的字段集合，其中包括
`sessionId`、`title` 和 13 位的 `lastMessageDate`。

P2 阶段没有确认聊天正文的位置。因此，全部 40 条 VS Code 记录都表示为
`index_only`，并设置 `has_transcript=false`、`turn_count=null`。

## 实现内容

- VS Code 索引解析隔离在 `VSCodeChatProvider` 中。
- 稳定 ID 由 Provider、工作区 ID 和来源特定索引 Key 的 URL 安全编码组成。
- 统一的 v2 列表把原有 Codex 会话与 VS Code 索引会话合并，同时保留旧版
  Codex API。
- `GET /api/v2/sessions` 支持 `provider`、`workspace` 和 `content_status`
  查询过滤条件。
- `GET /api/v2/sessions/<id>` 对仅索引会话返回明确的“尚未定位正文”说明。
- 前端提供来源、工作区和正文状态筛选，并显示来源标识和仅索引详情页。
- 在稳定 ID metadata 迁移完成之前，VS Code 记录的 metadata 编辑与关系编辑
  功能保持禁用。原始数据始终只读。

## 验证结果

- 统一返回的会话：43 个
- Codex / `full`：3 个
- VS Code Chat / `index_only`：40 个
- 非空工作区：8 个
- 自动化测试：6 项通过
- 前端 JavaScript 语法检查：通过
