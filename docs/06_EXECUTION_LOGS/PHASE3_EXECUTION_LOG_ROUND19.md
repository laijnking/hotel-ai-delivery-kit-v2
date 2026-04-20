# 第 19 轮执行记录：内部 Analysis Agent 函数层抽取

更新时间：2026-04-17

## 1. 本轮目标

根据用户要求，`openai-agents-python` 暂作为后续可拓展方向记录，不打断当前主线。本轮继续原计划：在不改变外部接口的前提下，将 `explanation-service` 内部的结构化分析块生成逻辑抽成轻量 `Analysis Agent` 函数层。

## 2. 本轮完成内容

### 2.1 OpenAI Agents SDK 拓展方向记录

新增文档：

- `docs/02_ARCHITECTURE_EVOLUTION/OPENAI_AGENTS_SDK_EXTENSION_NOTES.md`

记录内容包括：

- 可借鉴能力：
  - Agent 编排
  - Handoffs
  - Agents as tools
  - Guardrails
  - Sessions
  - Tracing
  - Sandbox Agents
- 当前决策：
  - 不替换确定性主链路
  - 后续优先在 Learning Agent、External Benchmark Agent、Trace/Guardrail 中试点

### 2.2 内部 Analysis Agent 函数层

在 `explanation-service` 中新增：

```python
run_analysis_agent(result, parsed_intent, template_code)
```

该函数当前负责：

- 生成 `analysis_blocks`
- 返回 agent 元信息：
  - `agent = analysis_agent`
  - `contract_version = 1.0`

`_attach_structured_outputs()` 现在通过 `run_analysis_agent()` 获取结构化事实块，再继续生成 `narrative_brief`。

### 2.3 外部接口保持兼容

旧字段继续保留：

- `summary`
- `management_summary`
- `risks`
- `suggestions`
- `report_sections`
- `analysis_blocks`
- `narrative_brief`

新增：

- `analysis_agent`

示例：

```json
{
  "analysis_agent": {
    "agent": "analysis_agent",
    "contract_version": "1.0"
  }
}
```

## 3. 验证结果

- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`
  - `Ran 76 tests ... OK`
- `.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report`
  - `12/12 passed`
  - report: `backend/evals/reports/eval_report_20260417-080137.md`
- `frontend`
  - `npm run build` 通过

## 4. 本轮阶段性价值

- `Analysis Agent` 不再只是架构概念，已经开始以内部函数边界存在。
- 结构化事实块生成和管理层表达生成开始分离。
- 后续可以继续把 Narrative Agent 也抽成类似边界，最终形成：

```text
metric rows
 -> Analysis Agent
 -> analysis_blocks
 -> Narrative Agent
 -> narrative_brief / report_sections
```

## 5. 下一轮建议

下一轮建议继续：

1. 抽取内部 `Narrative Agent` 函数层。
2. 将 `data_status = partial/missing` 的块生成更明确的缺数说明。
3. 为前端区分“管理层视图”和“调试视图”做准备。
