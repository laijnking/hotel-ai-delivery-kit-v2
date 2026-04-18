# OpenAI Agents SDK 后续拓展方向记录

更新时间：2026-04-17

## 1. 背景

用户提出是否研究 `openai/openai-agents-python`，以及它与当前酒店经营 AI 助手是否可以结合。

本项目当前主线仍是：

```text
用户问题
 -> semantic-service
 -> analysis_contract
 -> ai-query-service
 -> db-executor-service
 -> explanation-service
 -> analysis_blocks / narrative_brief
 -> frontend
```

短期不建议把当前确定性主链路整体替换成通用 agent 框架。酒店经营分析涉及 NOP/GOP、预算/同比、管理公司、区域、品牌、科目层级等高口径场景，仍应优先保证确定性查询和可审计口径。

## 2. 可借鉴方向

OpenAI Agents SDK 的以下能力可作为后续架构参考：

- Agent 编排
- Handoffs
- Agents as tools
- Guardrails
- Sessions
- Tracing
- Sandbox Agents

## 3. 与本项目的结合方式

建议采用“局部吸收，不整体替换”的方式：

```text
保留当前确定性主链路
引入 agent 编排思想
优先在后台学习、评测、外部对标、trace 诊断中试点
谨慎进入实时问答主链路
```

## 4. 推荐试点顺序

### 4.1 Trace Event Contract

参考 Agents SDK tracing 思路，建立本项目自己的 trace event：

- `parse_intent`
- `build_analysis_contract`
- `build_sql`
- `execute_sql`
- `build_analysis_blocks`
- `build_narrative_brief`
- `frontend_render`

目标是降低用户感知中的“黑箱感”。

### 4.2 Guardrail Contract

参考 Agents SDK guardrails 思路，增强：

- 输入护栏
- SQL 护栏
- 输出护栏
- 外部对标来源护栏
- NOP/GOP 口径护栏
- 预算/同比解释护栏

### 4.3 Learning Agent 试点

最适合优先试点的 agent 是后台 Learning Agent：

- 读取失败样本
- 生成 alias proposal
- 生成 eval case proposal
- 生成 semantic mapping proposal
- 生成 report template proposal

该能力不影响前台实时问答，风险较低。

### 4.4 External Benchmark Agent

外部行业对标适合 agent 化，但必须带：

- 数据来源
- 获取时间
- 适用范围
- 置信度
- 用户确认入口

## 5. 暂不建议事项

短期不建议：

- 用通用 agent 直接替代 `semantic-service`
- 用通用 agent 自由生成 SQL
- 用通用 agent 直接输出管理层结论
- 让外部行业数据无来源地进入正式分析结果

## 6. 当前决策

本方向先作为后续可拓展能力 mark，不打断当前主线开发。

当前主线继续推进：

- Planner + Semantic Graph
- `analysis_contract`
- `analysis_blocks`
- `narrative_brief`
- Analysis Agent / Narrative Agent 内部分层
- Learning / Harness 闭环
