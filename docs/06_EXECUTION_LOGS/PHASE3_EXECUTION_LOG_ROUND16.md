# 第 16 轮执行记录：analysis_contract 驱动查询与解释块裁剪

更新时间：2026-04-17

## 1. 本轮目标

上一轮已经在 `query_plan` 中新增了 `analysis_contract`，并让解释层返回 `analysis_blocks / narrative_brief`。本轮继续向前推进：让 `analysis_contract.block_sequence` 不再只是说明字段，而是真正参与后端查询字段选择和解释块生成。

核心目标：

- 用户只关心某些分析层时，查询层不要无差别取全量指标。
- 解释层应按 Planner 给出的 block sequence 组织和裁剪分析块。
- 旧的 bundle/template 逻辑继续作为兜底，不破坏现有问答链路。

## 2. 本轮完成内容

### 2.1 ai-query-service

新增 `analysis_contract.block_sequence` 到指标字段选择链路。

当前 block 到指标的基础映射为：

- `income_quality`
  - `TOTAL_INCOME`
  - `ROOM_INCOME`
  - `RESTAURANT_INCOME`
  - `BANQUET_INCOME`
- `room_efficiency`
  - `ADR`
  - `OCCUPANCY_RATE`
  - `REVPAR`
- `profit_quality`
  - `OWNER_PROFIT`
  - `OPERATING_PROFIT`
- `cost_efficiency`
  - `PEOPLE_COST`
  - `ENERGY_EXPENSES`
  - `RESTAURANT_COST`

同时，系统始终保留主指标。例如用户问经营情况时，主指标仍优先保留 `OWNER_PROFIT / NOP业主净利润`。

本轮主线程收口时做了一个更严格的策略：如果 `analysis_contract.block_sequence` 已明确提供分析块，则查询字段优先按合同块裁剪，不再继续把整个 bundle 的所有指标都带上。这样可以减少不必要字段，也让系统更贴近用户当前问题。

### 2.2 explanation-service

`analysis_blocks` 现在优先按 `analysis_contract.block_sequence` 生成和裁剪。

执行顺序为：

1. 若 `analysis_contract.block_sequence` 存在，优先按合同顺序生成 block。
2. 若合同不存在，回落到 `report_templates.yaml` 中的 `analysis_block_order`。
3. 若模板配置也缺失，回落到服务内默认顺序。

同时修复了合同读取位置：

- 支持从 `parsed_intent.query_plan.analysis_contract` 读取。
- 兼容顶层 `parsed_intent.analysis_contract`。

### 2.3 tests

新增两条回归：

- `test_build_sql_uses_analysis_contract_block_sequence_to_trim_metric_fields`
  - 验证当 block sequence 只包含 `income_quality` 和 `profit_quality` 时，SQL 包含收入与利润字段，但不包含 RevPAR 和成本字段。
- `test_explanation_analysis_blocks_follow_contract_block_sequence`
  - 验证解释层的 `analysis_blocks` 严格按合同顺序裁剪为 `scope_overview -> income_quality -> profit_quality`。

## 3. 验证结果

- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`
  - `Ran 76 tests ... OK`
- `.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report`
  - `12/12 passed`
  - report: `backend/evals/reports/eval_report_20260417-072951.md`
- `frontend`
  - `npm run build` 通过
  - 第一次在 sandbox 内运行时被 `esbuild spawn EPERM` 拦截，提升权限重跑后通过。

## 4. 本轮阶段性价值

- `analysis_contract` 开始从“计划说明”升级为“执行约束”。
- 查询层可以按用户问题裁剪字段，减少无关数据进入下游解释。
- 解释层可以按 Planner 输出的 block sequence 做块级编排，为后续真正拆分 `Analysis Agent` 和 `Narrative Agent` 奠定基础。

## 5. 下一轮建议

下一轮建议继续推进：

1. 让 `analysis_blocks` 增加结构化事实字段，例如 `metrics_used`、`evidence_fields`、`data_status`，方便 Narrative Agent 不靠自然语言二次猜测。
2. 开始拆出轻量的 Analysis Agent 内部函数层，让它只产出事实块，不直接负责最终表达。
3. 前端继续减少旧 section 与新 block 的重复展示，把首屏稳定成“简报头部 + 分析块 + 继续问”。
