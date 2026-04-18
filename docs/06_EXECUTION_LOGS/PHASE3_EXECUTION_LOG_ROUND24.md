# 第 24 轮执行记录：前端调试视图收口

更新时间：2026-04-17

## 1. 本轮目标

本轮承接第 23 轮 `trace_events` 后端契约，目标是在前端把链路追踪信息接入“非管理层默认视图”的技术诊断区，同时继续保持集团管理层界面克制、干净，不暴露技术页签和调试内容。

## 2. 本轮完成内容

### 2.1 技术诊断区接入 `trace_events`

在非集团管理层角色下，`ResultCard` 的“技术诊断信息”现在会展示后端返回的 trace 阶段摘要：

- `parse_intent` -> 语义理解
- `sql_guardrail` -> 口径安全检查
- `execute_sql` -> 数据读取
- `build_analysis_blocks` -> 分析拆解
- `build_narrative_brief` -> 叙事生成
- `pipeline_warnings` -> 系统提示

每个阶段会展示：

- 阶段中文名
- 状态中文名
- 耗时
- Agent 名称
- Guardrail 状态
- 数据行数或指标等关键 metadata

### 2.2 管理层默认界面继续隐藏技术信息

集团管理层角色仍然不显示：

- 分析明细折叠区
- 技术诊断信息
- SQL 计划
- 权限范围
- 报告 Markdown

这样可以让管理层默认只看经营分析、当前理解、核心数据和继续追问建议。

### 2.3 修复前端启动时上下文初始化顺序问题

修复 `starterPromptGroups` 在 `conversationContext` 初始化前使用导致的运行时错误：

```text
Cannot access 'conversationContext' before initialization
```

这个问题会导致 App 在浏览器中无法渲染，是本轮前端 E2E 被挡住的根因之一。

### 2.4 前端 E2E 断言同步当前交互形态

旧测试仍在寻找已经移除的调试式交互：

- `quick-question-0`
- `follow-up-0`
- `follow-up-actions summary`
- 已隐藏的 `executive-overview`

本轮将这些断言更新为当前真实 UI：

- 首页快捷入口使用 `starter-prompts` PromptBank。
- 继续追问使用 `follow-up-actions` PromptBank。
- 管理层简报使用 `management-overview`。
- “看去年同期”也被纳入 `yoy_change` 追问识别。

## 3. 验证结果

- `npm run test:e2e -- tests/management-chat.spec.ts`
  - `14 passed`
- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`
  - `Ran 79 tests ... OK`
- `.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report`
  - `12/12 passed`
  - report: `backend/evals/reports/eval_report_20260417-192203.md`
- `frontend`
  - `npm run build` 通过

## 4. 关于新数据源事项

用户补充了后续计划：

- 将经营 overview 数据源从 `wddm_dim_overview_cockpit_f` 切换到 `vw_overview_cockpit`。
- `C:\Project\HotelAgent\real-data\酒店数据字典.md` 已提供 `dim_hotel_info` 和日报快照表说明。

当前状态：

- 公网 MySQL 暂未加入白名单，本轮无法直接读取 `vw_overview_cockpit` 字段结构。
- 本地 DuckDB 仓库当前仍只有 `wddm_dim_overview_cockpit_f`、`vw_pnl_fact`、`dim_allhotel_slcp`。
- 因此本轮没有启用新视图，避免生产查询默认指向本地不存在的数据源。

后续处理建议：

- 待 MySQL 白名单开放后，先读取 `vw_overview_cockpit` 字段结构。
- 再更新 metric dictionary、semantic entity catalog、db executor 本地同步脚本和 eval 断言。
- 若新视图已包含管理公司、品牌、区域、城市级别等字段，应减少对 `dim_allhotel_slcp` 的联表依赖。

## 5. 本轮阶段性价值

- 后端 trace contract 已经有前端落点。
- 技术诊断能力不会干扰集团管理层阅读体验。
- 前端 E2E 已重新对齐当前产品形态，避免旧调试界面断言继续拖慢回归。
- `看去年同期` 这类更自然的连续追问开始映射到 `yoy_change`，与用户期望更一致。

## 6. 下一轮建议

继续推进剩余计划中的 Learning / Harness 闭环：

- 把失败问题、低置信度问题、无数据问题沉淀到 Learning Inbox。
- 生成 alias proposal 和 eval case proposal。
- 为后续“自学习但需人工审核”的机制打基础。
