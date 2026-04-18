# 第 22 轮执行记录：Narrative Guardrail 实检查

更新时间：2026-04-17

## 1. 本轮目标

本轮开始执行 `REMAINING_AUTONOMOUS_DELIVERY_PLAN.md` 中的第 22 轮任务：将 `narrative_agent.guardrail` 从固定元信息升级为实际检查逻辑。

重点检查场景：

- 当 `analysis_blocks` 中存在 `partial/missing` 且有 `missing_fields` 时，叙事层不能使用“完整、充分、可判断、明确判断、完全”等容易造成过度表达的词。

## 2. 本轮完成内容

### 2.1 新增 `_evaluate_narrative_guardrail()`

在 `explanation-service` 中新增：

```python
_evaluate_narrative_guardrail(narrative_brief, analysis_blocks)
```

当前检查项：

- `no_unbacked_facts`
- `facts_from_analysis_blocks`
- `missing_data_not_overstated`

当发现缺数状态被过度表达时，返回：

```json
{
  "status": "warning",
  "checks": [
    "no_unbacked_facts",
    "facts_from_analysis_blocks",
    "missing_data_not_overstated",
    "missing_data_overstated"
  ],
  "warnings": [
    {
      "code": "missing_data_overstated",
      "block": "room_efficiency",
      "missing_fields": ["revpar_actual"]
    }
  ]
}
```

### 2.2 接入 `run_narrative_agent()`

`run_narrative_agent()` 现在先生成 `narrative_brief`，再调用 `_evaluate_narrative_guardrail()` 生成真实 guardrail 结果。

### 2.3 tests

新增并通过：

- `test_narrative_guardrail_flags_missing_data_overstatement`

覆盖：

- `room_efficiency.data_status = partial`
- 缺少 `revpar_actual`
- 叙事文案出现“完整可判断”
- guardrail 返回 `warning`
- checks 包含 `missing_data_overstated`

## 3. 验证结果

- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`
  - `Ran 78 tests ... OK`
- `.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report`
  - `12/12 passed`
  - report: `backend/evals/reports/eval_report_20260417-082123.md`
- `frontend`
  - `npm run build` 通过

## 4. 本轮阶段性价值

- Narrative Guardrail 不再只是“声明通过”，已经开始执行真实检查。
- 系统开始防止“缺数据但表达成足够判断”的风险。
- 这是将表达层从“生成文案”升级为“受约束生成文案”的第一步。

## 5. 下一轮建议

下一轮按计划推进第 23 轮：

- 定义 `trace_events` contract。
- 将 parse、SQL、执行、Analysis Agent、Narrative Agent 等阶段写入响应和审计链路。
- 前端后续可以基于 trace 降低用户感知中的黑箱感。
