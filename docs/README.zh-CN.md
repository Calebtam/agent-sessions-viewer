# Agent Sessions Viewer 文档导航

## 当前专项改造设计（推荐）

1. [Copilot CLI 真实格式调查报告](CopilotCLI-真实格式调查报告.md)
   - 本机 8 个真实会话、31,253 条事件的脱敏结构调查。
2. [CodexProvider 与 CopilotCLIProvider 双 Provider 改造方案](CodexProvider-CopilotCLIProvider-双Provider改造方案.md)
   - 聚焦两个正文 Provider 的总体架构和解析规则。
3. [CodexProvider 与 CopilotCLIProvider 详细实施方案](CodexProvider-CopilotCLIProvider-详细实施方案.md)
   - 文件级任务、关联算法、Fixture、测试、性能、提交和回滚。
4. [CodexProvider 与 CopilotCLIProvider 实施记录](CodexProvider-CopilotCLIProvider-实施记录.md)
   - 已完成能力、验证结果、设计差异和后续工程化任务。

建议按“调查报告 → 总体设计 → 详细实施 → 实施记录”的顺序阅读。

## 调查和阶段记录

- [原始 VSCode AI 会话存储分析与改造初稿](../VSCode%20AI%20会话存储分析与%20Agent%20Sessions%20Viewer%20改造方案.md)
- [P0/P1 基线与诊断记录](p0-p1-baseline.zh-CN.md)
- [P2 VS Code Chat 索引集成记录](p2-index-integration.zh-CN.md)
- [P0–P2 实施与调查运行手册](p0-p2-playbook.zh-CN.md)
- [前端可回退功能开关](前端可回退功能开关.md)
  - Sessions 来源圆点和 Agent 内容宽度模式的 feature gate、搜索锚点与撤销步骤。
- [Session 双栏对比功能](Session双栏对比功能.md)
  - 两阶段会话选择、1/2/3 column 映射、双 Outline 和按序号同步滚动。

## 可复用脚本

```bash
python3 scripts/vscode_index_inventory.py
python3 scripts/copilot_cli_format_inventory.py
python3 scripts/verify_p0_p2.py
python3 scripts/verify_dual_providers.py
```

脚本用途和安全边界见 P0–P2 运行手册。
