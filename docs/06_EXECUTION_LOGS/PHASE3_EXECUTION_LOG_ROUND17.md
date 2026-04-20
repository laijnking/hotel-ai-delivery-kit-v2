# 第 17 轮执行记录：analysis_blocks 结构化事实元数据

更新时间：2026-04-17

## 1. 本轮目标

第 16 轮已经让 `analysis_contract.block_sequence` 开始驱动查询字段和解释块裁剪。本轮继续推进 `Analysis Agent + Narrative Agent` 的拆分基础：让 `analysis_blocks` 从“纯文本块”升级为“带事实元数据的结构化分析块”。

核心目标：

- Analysis 层负责输出事实块和证据字段。
- Narrative 层后续只负责表达，不再反向猜测哪些指标支撑了某段结论。
- 保持旧字段兼容，不影响当前前端展示。

## 2. 本轮完成内容

### 2.1 explanation-service

`analysis_blocks` 保留旧字段：

- `code`
- `type`
- `title`
- `content`
- `template_code`
- `focus`

同时新增：

- `metrics_used`
- `evidence_fields`
- `data_status`

其中：

- `metrics_used` 表示该分析块使用或依赖的业务指标，例如 `TOTAL_INCOME`、`OWNER_PROFIT`、`REVPAR`。
- `evidence_fields` 表示该分析块对应的数据字段或证据来源，例如 `total_income_actual`、`report_sections.收入质量`。
- `data_status` 表示数据可用程度，目前支持：
  - `available`
  - `partial`
  - `missing`

### 2.2 事实块覆盖范围

本轮已经为以下 block 建立事实元数据：

- `scope_overview`
- `dimension_summary`
- `income_quality`
- `room_efficiency`
- `profit_quality`
- `cost_efficiency`
- `benchmark`
- `portfolio_watchlist`

### 2.3 tests

增强回归：

- `test_explanation_returns_analysis_blocks_and_narrative_brief`
  - 新增断言：
    - `income_quality.metrics_used` 包含 `TOTAL_INCOME`
    - `income_quality.evidence_fields` 包含 `total_income_actual`
    - `income_quality.data_status = available`

## 3. 验证结果

- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`
  - `Ran 76 tests ... OK`
- `.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report`
  - `12/12 passed`
  - report: `backend/evals/reports/eval_report_20260417-074457.md`
- `frontend`
  - `npm run build` 通过
  - sandbox 内仍会遇到 `esbuild spawn EPERM`，提升权限后构建通过。

## 4. 本轮阶段性价值

- `analysis_blocks` 已经开始从展示结构升级为事实结构。
- 后续 Narrative Agent 可以基于 `metrics_used / evidence_fields / data_status` 生成文案，而不需要从自然语言段落里重新推断依据。
- 这进一步降低了“表达层编造事实”的风险。

## 5. 下一轮建议

下一轮建议继续推进：

1. 让前端在技术折叠区展示 `data_status` 和证据字段，方便调试和验收。
2. 将 `analysis_blocks` 的生成逻辑进一步抽成内部 Analysis Agent 函数，减少 `explanation-service` 主函数膨胀。
3. 为 `data_status = partial/missing` 的块生成更精准的“缺数说明”和可追问建议。
