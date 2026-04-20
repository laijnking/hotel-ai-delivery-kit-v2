# 第 15 轮执行记录：结构化分析对象与 Planner 契约升级

更新时间：2026-04-17

## 1. 本轮目标

本轮继续按无人值守多 Agent 模式推进，目标从“模板驱动展示”再往前一步，开始补上更明确的 Planner 契约，以及为 `Analysis Agent + Narrative Agent` 拆分准备结构化输出接口。

本轮重点不是继续堆规则，而是让系统开始返回更稳定、可组合、可消费的结构化对象。

## 2. 本轮完成内容

### 2.1 semantic-service

- 在 `query_plan` 中新增兼容版 `analysis_contract`
- 新增字段：
  - `contract_version = 1.1`
  - `objective_code`
  - `response_shape`
  - `headline_metric`
  - `comparison_label`
  - `primary_dimensions`
  - `block_sequence`
- 保留旧字段：
  - `analysis_mode`
  - `analysis_focus`
  - `metric_bundle_code`
  - `report_template_code`
  - `dimension_axes`
  - `dimension_signature`

这意味着旧消费者仍然可以继续读旧字段，新消费者则可以开始转向 `analysis_contract`。

### 2.2 explanation-service

- 在解释结果中新增：
  - `analysis_blocks`
  - `narrative_brief`
- `analysis_blocks` 开始以 typed blocks 形式组织内容，覆盖：
  - `scope_overview`
  - `dimension_summary`
  - `income_quality`
  - `room_efficiency`
  - `profit_quality`
  - `cost_efficiency`
  - `benchmark`
  - `portfolio_watchlist`
- `narrative_brief` 输出更像管理层简报头部的结构化文案，包含：
  - `headline`
  - `lead`
  - `follow_up_text`
  - `template_code`
  - `focus`

本轮还补齐了兼容字段：

- `analysis_blocks[*].code`
- `narrative_brief.focus`

避免不同消费者读到不同命名。

### 2.3 ai-query-service

- 将 `analysis_blocks` 和 `narrative_brief` 透传到顶层响应
- 若解释层缺失结构化结果，会自动从以下来源回退生成兼容块：
  - `report_sections`
  - `management_summary`
  - `summary`

这样前端在新旧接口混用期不会出现“无可展示内容”的空白状态。

### 2.4 frontend

- 首屏优先消费 `analysis_blocks / narrative_brief`
- 结构化块存在时，结果页更像“管理层简报卡片”
- 旧的 `report_sections` 仍保留兜底
- 技术调试折叠区继续保留，没有牺牲诊断能力

### 2.5 tests

新增并通过：

- `test_semantic_query_plan_exposes_analysis_contract_for_group_dimension`
- `test_explanation_returns_analysis_blocks_and_narrative_brief`

这意味着“Planner 契约升级”和“结构化解释对象”已经正式进入回归保护范围。

## 3. 验证结果

- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`
  - `Ran 74 tests ... OK`
- `.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report`
  - `12/12 passed`
  - report: `backend/evals/reports/eval_report_20260417-072048.md`
- `frontend`
  - `npm run build` 通过

## 4. 本轮阶段性价值

- 系统不再只是“根据模板组织章节”，而是开始拥有真正可消费的结构化分析对象。
- 这为下一步拆出 `Analysis Agent` 和 `Narrative Agent` 打下了接口基础。
- 后续可以逐步把“查数”“分析”“表达”进一步解耦，而不是继续把所有逻辑堆在单个解释函数里。

## 5. 下一轮建议

下一轮建议继续推进两件事：

1. 让 `analysis_contract.block_sequence` 真正驱动查询字段和分析块生成，而不只是语义层输出提示。
2. 把 `Analysis Agent` 和 `Narrative Agent` 的职责继续拆清：
   - `Analysis Agent` 负责形成结构化事实块
   - `Narrative Agent` 负责把事实块组织成管理层阅读文案
