# 第 25 轮执行记录：Learning Inbox schema v2

更新时间：2026-04-17

## 1. 本轮目标

本轮推进剩余计划中的 Learning / Harness 闭环，把系统运行中产生的失败问题、低置信度问题、无数据问题，从简单日志升级为可审核、可沉淀、可转 eval 的学习样本。

## 2. 本轮完成内容

### 2.1 Learning Inbox 升级到 schema v2

`write_learning_sample()` 写入的记录升级为：

```json
{
  "schema_version": 2,
  "review_status": "pending_review"
}
```

新增字段：

- `analysis_contract`
- `analysis_blocks`
- `guardrail`
- `trace_events`
- `alias_proposal`
- `eval_case_proposal`

### 2.2 自动生成 alias proposal

新增 `build_alias_proposal()`，从解析结果中提取可能需要进入别名词典的候选项：

- 酒店
- 区域
- 管理公司
- 子品牌
- query plan 中的对象标签

当前 proposal 只进入 `pending_review` 样本，不自动写入正式词典，避免自学习污染生产配置。

### 2.3 自动生成 eval case proposal

新增 `build_eval_case_proposal()`，为每条可学习样本生成可转入 eval 的候选结构：

- `id`
- `question`
- `time_scope`
- `reason`
- `expected`
- `sql_assertions`

`system_learning_harness_candidates()` 优先复用样本内的 `eval_case_proposal`，并补充：

- `source_trace_id`
- `review_status`
- `notes`

### 2.4 主查询链路写入 trace / blocks / guardrail

在 `ai-query-service` 主链路中，Learning sample 现在会记录：

- 本次 `trace_events`
- `analysis_contract`
- `analysis_blocks`
- `narrative_agent.guardrail`

这样后续排查“为什么识别错 / 为什么没数据 / 为什么表达保守”时，不需要只看最终 summary。

## 3. 测试覆盖

新增并通过：

- `test_learning_sample_schema_v2_includes_trace_guardrail_and_proposals`

覆盖内容：

- schema version 为 2
- review 状态为 `pending_review`
- analysis contract 写入
- analysis blocks 写入
- guardrail 写入
- trace events 写入
- alias proposal 自动生成
- eval case proposal 自动生成

## 4. 验证结果

- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`
  - `Ran 80 tests ... OK`
- `npm run test:e2e -- tests/management-chat.spec.ts`
  - `14 passed`
- `.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report`
  - `12/12 passed`
  - report: `backend/evals/reports/eval_report_20260417-193131.md`
- `frontend`
  - `npm run build` 通过

## 5. 数据源切换事项

用户已明确：

- `wddm_dim_overview_cockpit_f -> vw_overview_cockpit` 的切换后续再执行。
- 当前公网 MySQL 未加入白名单，无法读取新视图结构。
- `酒店数据字典.md` 中的日报快照和 `dim_hotel_info` 先作为后续适配参考。

本轮处理：

- 已停止数据源切换开发。
- 未启用 `vw_overview_cockpit` 默认路径。
- 避免本地仓库缺少新视图时造成查询失败。

## 6. 本轮阶段性价值

- Learning Inbox 不再只是问题日志，而是开始具备“可审查学习样本”的结构。
- 失败样本可以携带完整链路证据，减少黑箱感。
- 后续人工审核后，可以把 proposal 转成 alias、semantic mapping 或 eval case。

## 7. 下一轮建议

继续推进第 26 轮：Semantic Graph 深化。

重点建议：

- 管理公司 / 品牌 / 子品牌 / 区域 / 酒店之间的层级图谱继续增强。
- 科目层级和 PnL graph 继续配置化。
- 增加复杂语义 eval，尤其是“公司所有酒店 + 月份 + 管理公司/区域维度汇总”这类管理层常问问题。
