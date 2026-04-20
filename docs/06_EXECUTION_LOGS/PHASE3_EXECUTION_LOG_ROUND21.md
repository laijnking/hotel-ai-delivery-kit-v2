# 第 21 轮执行记录：缺数说明与 Narrative Guardrail

更新时间：2026-04-17

## 1. 本轮目标

第 20 轮已经抽出了内部 `Narrative Agent` 函数层。本轮继续增强两个能力：

- 为 `partial/missing` 的 `analysis_blocks` 生成更明确的缺数说明。
- 为 `Narrative Agent` 增加第一版输出护栏元信息，避免表达层越权补事实。

## 2. 本轮完成内容

### 2.1 analysis_blocks 缺数说明

每个分析块在已有字段基础上继续增强：

- `missing_fields`
- `missing_reason`

当前重点覆盖：

- `income_quality`
- `room_efficiency`
- `profit_quality`
- `cost_efficiency`

示例：

```json
{
  "code": "room_efficiency",
  "data_status": "partial",
  "missing_fields": ["occupancy_rate_actual", "adr_actual", "revpar_actual"],
  "missing_reason": "当前分析块缺少关键字段：occupancy_rate_actual、adr_actual、revpar_actual。"
}
```

### 2.2 data_status 判定增强

过去只要 `report_sections` 里有文字，部分块可能被误判为 `available`。本轮改为结合关键字段判断：

- 关键字段完整：`available`
- 关键字段部分缺失但有解释内容：`partial`
- 无内容且无字段：`missing`

### 2.3 Narrative Guardrail

`narrative_agent` 新增：

```json
{
  "guardrail": {
    "status": "passed",
    "checks": [
      "no_unbacked_facts",
      "facts_from_analysis_blocks",
      "missing_data_not_overstated"
    ]
  }
}
```

这不是最终完整护栏，但已经把“叙事层必须基于事实块、不越权补事实”的规则显式化。

### 2.4 tests

新增并通过：

- `test_analysis_block_missing_status_includes_reason_and_narrative_guardrail`

覆盖：

- 缺少 OCC/ADR/RevPAR 时，`room_efficiency.data_status = partial`
- 返回 `missing_reason`
- 返回 `missing_fields`
- `narrative_agent.guardrail.status = passed`
- guardrail 包含 `no_unbacked_facts`

## 3. 验证结果

- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`
  - `Ran 77 tests ... OK`
- `.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report`
  - `12/12 passed`
  - report: `backend/evals/reports/eval_report_20260417-081606.md`
- `frontend`
  - `npm run build` 通过

## 4. 本轮阶段性价值

- 系统开始区分“有文字解释”和“有足够数据证据”。
- Narrative Agent 的职责边界更清晰：只能基于 `analysis_blocks` 表达，不能补不存在的事实。
- 后续可以把 guardrail 从元信息升级为真正的输出校验逻辑。

## 5. 下一轮建议

下一轮建议继续：

1. 将 `narrative_agent.guardrail` 从固定状态升级为实际检查。
2. 把缺数说明接入前端证据折叠区，让用户能看到为什么是 partial。
3. 将 agent 元信息写入 trace/audit，增强可观测性。
