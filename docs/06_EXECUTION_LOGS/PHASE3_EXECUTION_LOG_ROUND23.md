# 第 23 轮执行记录：Trace Event Contract

更新时间：2026-04-17

## 1. 本轮目标

本轮继续执行 `REMAINING_AUTONOMOUS_DELIVERY_PLAN.md` 中的 R2 可观测性任务，目标是让一次问答从“只有最终答案”升级为“可以追踪关键处理阶段”。

这轮重点不是把调试信息直接暴露给管理层用户，而是先建立稳定的后端契约，后续前端可以按角色决定是否展示：

- 管理层默认只看经营分析。
- 技术/管理员视图可以展开查看解析、SQL、安全检查、数据执行、分析 Agent、叙事 Agent、Guardrail 等阶段。
- 当结果异常、无数据、口径不清时，可以用 trace 快速定位卡在语义、SQL、数据还是表达层。

## 2. 本轮完成内容

### 2.1 新增 `build_trace_events()`

在 `ai-query-service` 中新增统一的 trace 构造函数：

```python
build_trace_events(
    timings=timings,
    parsed=parsed,
    sql_plan=sql_plan,
    explanation_payload=explanation_payload,
    warnings=warnings,
)
```

当前输出的核心阶段包括：

- `parse_intent`
- `sql_guardrail`
- `execute_sql`
- `build_analysis_blocks`
- `build_narrative_brief`
- `pipeline_warnings`，仅当本轮存在 warning 时输出

### 2.2 trace metadata

每个阶段使用统一结构：

```json
{
  "stage": "build_narrative_brief",
  "status": "completed",
  "duration_ms": 0,
  "metadata": {
    "agent": "narrative_agent",
    "contract_version": "1.0",
    "guardrail_status": "passed"
  }
}
```

当前重点元信息：

- `parse_intent`：`intent`、`metric_code`、`compare_mode`、`analysis_mode`、`analysis_focus`
- `sql_guardrail`：`safe`、`warnings`
- `execute_sql`：`row_count`、`query_route`
- `build_analysis_blocks`：`agent`、`contract_version`、`block_count`
- `build_narrative_brief`：`agent`、`contract_version`、`guardrail_status`、`guardrail_warnings`

### 2.3 ai-query 响应接入

`ai-query-service` 的最终响应新增顶层字段：

```json
{
  "trace_events": []
}
```

这让后续前端可以不再依赖零散字段拼调试视图，而是直接消费统一事件流。

### 2.4 tests

新增并通过：

- `test_build_trace_events_includes_core_pipeline_and_agent_metadata`

覆盖内容：

- trace 至少包含 5 个主阶段。
- `build_narrative_brief` 阶段能透出 `guardrail_status`。
- trace contract 不依赖真实数据库查询即可单测。

## 3. 验证结果

- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services.ServiceSmokeTests.test_build_trace_events_includes_core_pipeline_and_agent_metadata`
  - `Ran 1 test ... OK`
- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`
  - `Ran 79 tests ... OK`
- `.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report`
  - `12/12 passed`
  - report: `backend/evals/reports/eval_report_20260417-171325.md`
- `frontend`
  - `npm run build` 通过

## 4. 本轮阶段性价值

- 系统从“结果可见”进一步升级为“链路可追踪”。
- 后续用户反馈“识别错了、没数据、分析重复、口径不清”时，可以更快判断问题发生在哪一层。
- 这为下一轮前端调试视图、管理员排错视图、Learning Inbox 自动沉淀提供了基础事件源。

## 5. 下一轮建议

下一轮继续推进 R2/R5 的前端侧接入：

- 在管理层默认界面中不展示技术 trace。
- 在折叠的调试视图中展示 trace 摘要。
- 把 trace 中的阶段状态转成更易懂的提示，例如“已识别问题”“已完成口径安全检查”“已生成经营观察”。
- 为后续 Learning Inbox 标记失败样本准备入口。
