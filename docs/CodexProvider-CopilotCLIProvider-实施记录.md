# CodexProvider 与 CopilotCLIProvider 实施记录

> 文档类型：实施结果与验收记录  
> 状态：核心链路已完成  
> 日期：2026-10-26  
> 设计依据：[双 Provider 改造方案](CodexProvider-CopilotCLIProvider-双Provider改造方案.md)  
> 实施依据：[详细实施方案](CodexProvider-CopilotCLIProvider-详细实施方案.md)

## 1. 本轮交付结论

Agent Sessions Viewer 已从仅依赖旧 Codex 解析链路，扩展为由 Registry 统一调度的
`CodexProvider`、`CopilotCLIProvider` 和只读 `VSCodeChatProvider`。其中前两个
Provider 均支持真实正文详情；Copilot CLI 不依赖 VS Code 索引或 VS Code 数据库。

当前核心能力：

- 发现并汇总 Codex 与 Copilot CLI 会话。
- 使用稳定、带 Provider 前缀的会话 ID 路由详情请求。
- 流式解析 Copilot CLI `events.jsonl`，关联 interaction、turn 和 tool call。
- 支持列表筛选、分页详情、跨 Provider 搜索、JSON/Markdown 导出。
- 支持名称、标签、分类、置顶和归档等统一元数据。
- 权限过滤发生在正文解析之前；普通 API 不返回本地源路径、source ID 或 fingerprint。
- Provider 级异常隔离、文件指纹缓存、解析限制和截断告警已接入。
- 验证过程只读真实会话源文件，并用前后 SHA-256 聚合值检查完整性。

## 2. 主要实现文件

| 层次 | 文件 | 作用 |
|---|---|---|
| Provider | `backend/providers/codex.py` | 包装现有 Codex parser，生成稳定 ID，提供摘要和详情缓存 |
| Provider | `backend/providers/copilot_cli.py` | 发现 Copilot CLI 会话，校验身份，生成摘要并加载详情 |
| Parser | `backend/parsers/copilot_cli.py` | 解析 workspace YAML 和 JSONL，重建消息、reasoning、附件及工具调用 |
| Registry | `backend/registry.py` | 聚合 Provider、隔离发现错误、按 ID 前缀路由 |
| API | `backend/app.py` | v2 列表、详情、元数据、搜索、导出、访问控制和响应脱敏 |
| Frontend | `frontend/index.html` | Provider/工作区/状态筛选，Copilot 详情、搜索、导出和来源标识 |
| Tests | `tests/test_copilot_cli.py` | 正常、工具、reasoning、附件、YAML、截断、限制和身份冲突 |
| Tests | `tests/test_codex_provider.py` | Codex 发现、稳定 ID、详情和缓存 |
| Tests | `tests/test_registry.py` | Provider 聚合、路由和错误隔离 |
| Verify | `scripts/verify_dual_providers.py` | 单测、编译、真实 API、脱敏、远程权限与源文件完整性验证 |

## 3. Copilot CLI 解析行为

### 3.1 输入边界

每个候选目录至少需要：

```text
~/.copilot/session-state/<session-id>/
├── workspace.yaml
└── events.jsonl
```

发现阶段读取 workspace 元数据并对事件做受限计数；详情阶段逐行读取 JSONL，不把整个
文件一次性载入内存。目录名、workspace ID 和 `session.start` 身份冲突时，该会话不会被
当作可信详情返回。

### 3.2 关联规则

```text
interactionId
└── turnId
    └── toolCallId
```

- `user.message` 建立 interaction。
- assistant 文本和 reasoning 按 interaction/turn 归组。
- tool request、start、complete 按 toolCallId 合并。
- 未知事件保持前向兼容：忽略其正文语义，不导致整会话失败。
- 不完整尾行、超出大小或事件数量限制会形成 warning/partial 状态。

## 4. API 与前端结果

新增或扩展的 v2 接口：

```text
GET   /api/v2/providers
GET   /api/v2/sessions
GET   /api/v2/sessions/<stable-id>
PATCH /api/v2/sessions/<stable-id>/metadata
GET   /api/v2/search?q=<query>
GET   /api/v2/export/<stable-id>?format=json|markdown
```

列表支持 `provider`、`workspace`、`content_status` 和归档过滤。详情支持 `offset`、
`limit` 分页。普通会话响应统一删除以下内部字段：

```text
source_path
source_id
sourceFingerprint
```

前端可以在同一列表中查看 Codex、Copilot CLI 和 VS Code 索引项；只有具备正文能力的
Provider 才会加载正文。Codex 原有恢复命令和关系视图仍走兼容链路，避免本轮重构改变
已有行为。

## 5. 验收方法

完整验收命令：

```bash
python3 scripts/verify_dual_providers.py
sed -n '185,1124p' frontend/index.html | node --check
git diff --check
```

其中前端是单文件 HTML 内嵌脚本，上述命令把内嵌 JavaScript 直接送给 `node --check`，
不会生成或修改项目文件。验证脚本会自动执行：

1. `python3 -m unittest discover -s tests -v`。
2. 编译 backend、Provider 和 parser Python 文件。
3. 调用真实 `/api/v2/sessions`。
4. 分别抽查一个 Codex 和 Copilot CLI 详情及分页。
5. 检查列表和详情不泄露内部源字段。
6. 模拟远程客户端，验证未授权会话不可见。
7. 对静止的真实 Codex/Copilot 源文件计算执行前后摘要，确认未被改写；最近 5 分钟仍在
   写入的当前 CLI 会话单独计数并排除，避免宿主写入造成假失败。

最近一次本机验收基线：

| 项目 | 结果 |
|---|---|
| 单元测试 | 15 项通过 |
| Python 编译 | 通过 |
| Codex 真实发现 | 3 个会话 |
| Copilot CLI 真实发现 | 8 个会话 |
| Copilot CLI 全量详情抽查 | 8/8 可解析，无 warning |
| 未授权远程可见会话 | 0 |
| API 内部字段脱敏 | 通过 |
| 静止源文件前后摘要 | 全部不变；活跃写入文件单独报告 |

会话数是本机动态状态，不应作为固定断言；固定验收条件是接口成功、目标 Provider 可发现、
详情可解析、响应已脱敏且源文件不变。

## 6. 与详细实施方案的差异

本轮优先交付可运行的端到端链路，以下结构性工作尚未拆分完成：

- 统一模型仍以兼容字典为主，尚未完全切换到 dataclass 强类型模型。
- sessions、metadata、access、search、export 仍集中在 `backend/app.py`，尚未拆分为独立 service/API 模块。
- Codex parser 继续复用 `backend/parser.py`，未迁移到独立 `backend/parsers/codex.py`。
- 尚未提供自动脱敏 Fixture 生成器和独立 schema 契约文档。
- Copilot subagent 事件尚未转换为统一关系图。
- 元数据仍复用现有 JSON 文件；尚未实施独立 v2 数据文件、迁移命令和 Token 哈希升级。
- 未执行真实浏览器端到端视觉测试；目前完成 API、单元测试和前端 JavaScript 语法验证。

这些差异不阻塞 CodexProvider 与 CopilotCLIProvider 的发现、详情、搜索和导出主链路，
但应作为下一轮工程化和安全加固任务继续处理。

## 7. 后续建议顺序

1. 增加 API v2 独立测试和浏览器端到端测试。
2. 提取 service/API 模块，并引入强类型统一模型和序列化层。
3. 建立脱敏 Fixture 生成器及 Copilot CLI schema 契约。
4. 完成 metadata v2 迁移、备份与 Token 哈希。
5. 解析 Copilot subagent 关系，并扩展统一关系图。
6. 完成性能压测、缓存淘汰和超大文件基准。

