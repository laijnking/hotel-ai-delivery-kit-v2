# 第 18 轮执行记录：前端展示 analysis_blocks 证据状态

更新时间：2026-04-17

## 1. 本轮目标

第 17 轮已经让 `analysis_blocks` 携带 `metrics_used`、`evidence_fields`、`data_status`。本轮继续把这些结构化元数据接到前端展示层，让结果页不仅能展示分析内容，还能在需要时看到每个分析块的数据状态和证据来源。

## 2. 本轮完成内容

### 2.1 frontend

在结构化分析块卡片中新增：

- 数据状态胶囊
  - `available` 显示为“数据完整”
  - `partial` 显示为“部分数据”
  - `missing` 显示为“缺少数据”
- 证据字段折叠区
  - 默认收起，不打断管理层阅读
  - 展开后显示：
    - 使用指标
    - 证据字段

### 2.2 兼容逻辑

- 若后端没有返回 `data_status`，前端不显示状态胶囊。
- 若后端没有返回 `metrics_used / evidence_fields`，前端不显示证据折叠区。
- 旧的 `report_sections` 和技术调试折叠区继续保留。

## 3. 验证结果

- `frontend`
  - `npm run build` 通过

本轮仅修改前端展示层。后端在第 17 轮已完成回归：

- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`
  - `Ran 76 tests ... OK`
- `.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report`
  - `12/12 passed`

## 4. 本轮阶段性价值

- 管理层仍然看到简洁的经营分析卡片。
- 调试和验收人员可以展开查看“这段分析用了哪些指标、哪些字段”。
- 为后续做“事实块 -> 表达块”的 Agent 分层提供了前端承接能力。

## 5. 下一轮建议

下一轮建议继续推进：

1. 将 `analysis_blocks` 的生成逻辑从 `explanation-service` 主流程中抽出，形成内部 Analysis Agent 函数层。
2. 为 `partial/missing` 状态生成更精准的缺数说明。
3. 将前端的证据折叠区限制在管理层不可见或调试模式可见，进一步收口最终用户体验。
