# 第 20 轮执行记录：内部 Narrative Agent 函数层抽取

更新时间：2026-04-17

## 1. 本轮目标

第 19 轮已经抽出了内部 `Analysis Agent` 函数层。本轮继续补齐表达层边界：新增内部 `Narrative Agent` 函数层，使结构变为：

```text
metric rows
 -> run_analysis_agent()
 -> analysis_blocks
 -> run_narrative_agent()
 -> narrative_brief
```

## 2. 本轮完成内容

### 2.1 explanation-service

新增：

```python
run_narrative_agent(
    result,
    parsed_intent,
    template_code,
    bundle_code,
    bundle,
    focus_profile,
    analysis_blocks,
)
```

该函数当前负责：

- 生成 `narrative_brief`
- 返回 agent 元信息：
  - `agent = narrative_agent`
  - `contract_version = 1.0`
  - `input_blocks`

### 2.2 外部响应新增元信息

解释服务响应中新增：

```json
{
  "narrative_agent": {
    "agent": "narrative_agent",
    "contract_version": "1.0",
    "input_blocks": ["scope_overview", "income_quality", "profit_quality"]
  }
}
```

原有字段保持兼容：

- `summary`
- `management_summary`
- `report_sections`
- `analysis_blocks`
- `analysis_agent`
- `narrative_brief`

### 2.3 tests

增强回归：

- `test_explanation_returns_analysis_blocks_and_narrative_brief`
  - 新增断言：
    - `narrative_agent.agent = narrative_agent`
    - `narrative_agent.contract_version = 1.0`

## 3. 验证结果

- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`
  - `Ran 76 tests ... OK`
- `.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report`
  - `12/12 passed`
  - report: `backend/evals/reports/eval_report_20260417-080658.md`
- `frontend`
  - `npm run build` 通过

## 4. 本轮阶段性价值

- `Analysis Agent` 和 `Narrative Agent` 已经从架构概念变成内部函数边界。
- 当前还不是独立微服务，也不是外部 SDK agent，但已经具备清晰接口：
  - Analysis 负责事实块
  - Narrative 负责表达块
- 后续可以继续把这两个函数层迁移成更独立的模块、类或 agent runtime。

## 5. 下一轮建议

下一轮建议继续：

1. 为 `partial/missing` 的 `analysis_blocks` 生成更明确的缺数说明。
2. 给 `narrative_agent` 增加输出护栏，防止表达层越权补事实。
3. 将 agent 元信息写入 trace/audit，增强可观测性。
