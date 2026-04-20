# 剩余任务无人值守交付计划

更新时间：2026-04-17

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将酒店经营 AI 助手从当前“结构化经营分析雏形”推进到“管理层可稳定使用、可追踪、可配置、可交付”的状态。

**Architecture:** 保留当前确定性主链路：`semantic-service -> analysis_contract -> ai-query-service -> db-executor-service -> explanation-service -> analysis_blocks / narrative_brief -> frontend`。后续开发围绕 Planner/Semantic Graph、Analysis/Narrative Agent 内部分层、Learning/Harness、Trace/Guardrail、External Benchmark 和交付运维逐步增强，不用通用 Agent 替换核心 SQL/口径链路。

**Tech Stack:** Python FastAPI 微服务、DuckDB/MySQL 数据源、YAML 配置、React/Vite 前端、unittest 回归、semantic SQL eval、Docker/内网部署。

---

## 1. 当前完成状态

### 1.1 已完成主能力

- 真实数据链路接入。
- NOP 业主净利润优先口径。
- 公司全部酒店、管理公司、区域、品牌等组合维度初步解析。
- `metric_bundles.yaml` 与 `report_templates.yaml`。
- `analysis_contract`。
- `analysis_blocks`。
- `narrative_brief`。
- `metrics_used / evidence_fields / data_status`。
- `missing_fields / missing_reason`。
- 内部 `run_analysis_agent()`。
- 内部 `run_narrative_agent()`。
- 前端结构化分析块展示与证据折叠区。
- 连续追问基础链路。
- OpenAI Agents SDK 后续拓展方向已记录。

### 1.2 最近验证基线

- 后端：`.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`
  - 最近结果：`Ran 79 tests ... OK`
- Eval：`.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report`
  - 最近结果：`12/12 passed`
  - 最近报告：`backend/evals/reports/eval_report_20260417-171325.md`
- 前端：`npm run build`
  - 最近结果：通过

---

## 2. 剩余任务总览

剩余任务按 7 个阶段推进。

### 阶段 R1：Narrative Guardrail 实检查

目标：让 `narrative_agent.guardrail` 从固定元信息升级为实际检查。

任务：

1. R1.1 输出事实来源检查。
2. R1.2 缺数状态表达检查。
3. R1.3 NOP/GOP、预算/同比口径检查。
4. R1.4 guardrail 失败时降级为保守文案。

### 阶段 R2：Trace / 可观测性

目标：降低系统黑箱感，记录每次问答的关键阶段。

任务：

1. R2.1 定义 `trace_events` 结构。已完成，见第 23 轮。
2. R2.2 ai-query-service 记录 parse/sql/query/explanation 阶段事件。已完成，见第 23 轮。
3. R2.3 explanation-service 记录 analysis/narrative/guardrail 事件。已通过 `analysis_agent / narrative_agent / guardrail` metadata 透传，后续可继续细化为独立服务内 trace。
4. R2.4 前端技术折叠区展示 trace 摘要。
5. R2.5 docs 增加 trace 字段说明。第 23 轮执行日志已补充，后续需要补充接口字段说明。

### 阶段 R3：Learning / Harness 闭环

目标：让失败问题、用户纠正、低置信度样本沉淀为可审核学习材料。

任务：

1. R3.1 Learning Inbox 样本结构升级。
2. R3.2 自动生成 alias proposal。
3. R3.3 自动生成 eval case proposal。
4. R3.4 增加人工审核状态。
5. R3.5 Harness 自动扩样回归。

### 阶段 R4：Semantic Graph 深化

目标：继续强化管理公司、品牌、子品牌、区域、酒店、科目层级、月份、组合范围的稳定理解。

任务：

1. R4.1 统一实体别名词典。
2. R4.2 科目层级 PnL graph 配置化。
3. R4.3 组合范围解释增强。
4. R4.4 连续追问上下文冲突处理。
5. R4.5 增加复杂语义 eval。

### 阶段 R5：前端管理层体验收口

目标：进一步降低技术感，使移动端更像管理层经营简报。

任务：

1. R5.1 管理层视图与调试视图分层。
2. R5.2 会话历史与会话标题。
3. R5.3 快捷提问配置化入口。
4. R5.4 继续追问面板精简。
5. R5.5 移动端首屏阅读节奏优化。

### 阶段 R6：External Benchmark Provider

目标：外部行业对标作为可选增强能力接入，不混淆内部事实。

任务：

1. R6.1 定义外部对标 provider contract。
2. R6.2 支持 uploaded dataset provider。
3. R6.3 支持联网 research provider。
4. R6.4 输出来源、时间、置信度。
5. R6.5 前端提供是否启用外部对标的清晰选择。

### 阶段 R7：交付与运维

目标：达到可部署、可启动、可验收、可交接。

任务：

1. R7.1 本地/内网/服务器启动脚本收口。
2. R7.2 Docker Compose 与端口健康检查文档。
3. R7.3 GitHub 发布流程整理。
4. R7.4 用户使用手册。
5. R7.5 管理员配置手册。
6. R7.6 最终验收清单。

---

## 3. 当前无人值守执行顺序

### 第 22 轮：Narrative Guardrail 实检查

**Files:**

- Modify: `backend/apps/explanation-service/app/main.py`
- Modify: `backend/tests/test_services.py`
- Create: `docs/06_EXECUTION_LOGS/PHASE3_EXECUTION_LOG_ROUND22.md`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_services.py` 中新增测试：

```python
def test_narrative_guardrail_flags_missing_data_overstatement(self):
    result = explanation_main.run_narrative_agent(
        result={"summary": "RevPAR表现完整可判断。"},
        parsed_intent={
            "query_plan": {
                "report_template_code": "executive_hotel_snapshot",
                "metric_bundle_code": "hotel_snapshot",
            }
        },
        template_code="executive_hotel_snapshot",
        bundle_code="hotel_snapshot",
        bundle={},
        focus_profile={},
        analysis_blocks=[
            {
                "code": "room_efficiency",
                "data_status": "partial",
                "missing_fields": ["revpar_actual"],
                "content": "当前结果未包含 RevPAR。",
            }
        ],
    )
    assert result["guardrail"]["status"] == "warning"
    assert "missing_data_overstated" in result["guardrail"]["checks"]
```

- [ ] **Step 2: 运行失败测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest backend.tests.test_services.ServiceSmokeTests.test_narrative_guardrail_flags_missing_data_overstatement
```

Expected:

```text
FAILED
```

- [ ] **Step 3: 实现 `_evaluate_narrative_guardrail()`**

在 `backend/apps/explanation-service/app/main.py` 中新增：

```python
def _evaluate_narrative_guardrail(narrative_brief: dict[str, Any], analysis_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    checks = ["no_unbacked_facts", "facts_from_analysis_blocks", "missing_data_not_overstated"]
    warnings = []
    lead = str(narrative_brief.get("lead") or "")
    for block in analysis_blocks:
        if not isinstance(block, dict):
            continue
        if block.get("data_status") in {"partial", "missing"}:
            missing_fields = block.get("missing_fields") if isinstance(block.get("missing_fields"), list) else []
            if missing_fields and any(term in lead for term in ("完整", "充分", "可判断")):
                warnings.append({
                    "code": "missing_data_overstated",
                    "block": block.get("code"),
                    "missing_fields": missing_fields,
                })
    return {
        "status": "warning" if warnings else "passed",
        "checks": checks + ([item["code"] for item in warnings] if warnings else []),
        "warnings": warnings,
    }
```

- [ ] **Step 4: 接入 `run_narrative_agent()`**

将固定 guardrail 替换为 `_evaluate_narrative_guardrail()`。

- [ ] **Step 5: 跑定向测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest backend.tests.test_services.ServiceSmokeTests.test_narrative_guardrail_flags_missing_data_overstatement
```

Expected:

```text
OK
```

- [ ] **Step 6: 跑全量验证**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest backend.tests.test_services
.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report
cd frontend
npm run build
```

Expected:

```text
backend tests OK
eval 12/12 passed
frontend build passed
```

- [ ] **Step 7: 写执行日志**

Create:

```text
docs/06_EXECUTION_LOGS/PHASE3_EXECUTION_LOG_ROUND22.md
```

内容包括：

- 本轮目标
- 变更点
- 新增 guardrail 检查
- 验证结果
- 下一轮建议

### 第 23 轮：Trace Event Contract

状态：已完成。执行记录见 `docs/06_EXECUTION_LOGS/PHASE3_EXECUTION_LOG_ROUND23.md`。

**Files:**

- Modify: `backend/apps/ai-query-service/app/main.py`
- Modify: `backend/apps/explanation-service/app/main.py`
- Modify: `backend/tests/test_services.py`
- Create: `docs/06_EXECUTION_LOGS/PHASE3_EXECUTION_LOG_ROUND23.md`

目标：

- 响应中新增 `trace_events`
- 至少记录：
  - `parse_intent`
  - `build_sql`
  - `execute_sql`
  - `build_analysis_blocks`
  - `build_narrative_brief`

验收：

- 后端测试断言 `trace_events` 存在。
- 每个 event 包含 `stage`、`status`、`duration_ms` 或 `metadata`。

### 第 24 轮：前端调试视图收口

状态：已完成。执行记录见 `docs/06_EXECUTION_LOGS/PHASE3_EXECUTION_LOG_ROUND24.md`。

**Files:**

- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `backend/tests/test_services.py` if response contract changes
- Create: `docs/06_EXECUTION_LOGS/PHASE3_EXECUTION_LOG_ROUND24.md`

目标：

- 管理层默认不显示技术字段。
- 调试折叠区集中展示：
  - trace events
  - analysis_contract
  - analysis_agent
  - narrative_agent
  - evidence fields

验收：

- `npm run test:e2e -- tests/management-chat.spec.ts`：`14 passed`
- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`：`Ran 79 tests ... OK`
- `.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report`：`12/12 passed`
- `npm run build`：通过

### 第 25 轮：Learning Inbox 升级

状态：已完成。执行记录见 `docs/06_EXECUTION_LOGS/PHASE3_EXECUTION_LOG_ROUND25.md`。

**Files:**

- Modify: `backend/apps/ai-query-service/app/main.py`
- Modify: `backend/evals/run_eval.py`
- Modify: `backend/tests/test_services.py`
- Create: `docs/06_EXECUTION_LOGS/PHASE3_EXECUTION_LOG_ROUND25.md`

目标：

- 学习样本增加：
  - `analysis_contract`
  - `analysis_blocks`
  - `guardrail`
  - `trace_events`
- 自动产出 eval proposal。

验收：

- Learning sample 已升级为 `schema_version = 2`。
- 新增 `review_status = pending_review`。
- 自动生成 `alias_proposal` 和 `eval_case_proposal`。
- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`：`Ran 80 tests ... OK`
- `npm run test:e2e -- tests/management-chat.spec.ts`：`14 passed`
- `.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report`：`12/12 passed`

### 第 26 轮：Semantic Graph 深化

**Files:**

- Modify: `backend/apps/semantic-service/app/main.py`
- Modify: `backend/configs/semantic_mapping.yaml`
- Modify: `backend/evals/cases/semantic_sql_cases.yaml`
- Modify: `backend/tests/test_services.py`
- Create: `docs/06_EXECUTION_LOGS/PHASE3_EXECUTION_LOG_ROUND26.md`

目标：

- 继续补管理公司、品牌、子品牌、科目层级、多条件组合问法。
- 增加至少 5 条复杂 eval。

### 第 27 轮：External Benchmark Provider Contract

**Files:**

- Modify: `backend/apps/ai-query-service/app/main.py`
- Create: `backend/configs/external_benchmark_providers.yaml`
- Modify: `frontend/src/App.tsx`
- Modify: `backend/tests/test_services.py`
- Create: `docs/06_EXECUTION_LOGS/PHASE3_EXECUTION_LOG_ROUND27.md`

目标：

- 外部对标必须明确来源、时间、置信度、用户启用状态。
- 不启用时不能混入正式内部经营结论。

### 第 28 轮：交付文档与验收清单

**Files:**

- Create: `docs/07_DELIVERY/USER_GUIDE.md`
- Create: `docs/07_DELIVERY/ADMIN_GUIDE.md`
- Create: `docs/07_DELIVERY/DEPLOYMENT_GUIDE.md`
- Create: `docs/07_DELIVERY/ACCEPTANCE_CHECKLIST.md`

目标：

- 形成可交付文档。
- 记录启动方式、端口、环境变量、常见问题、验收问题集。

---

## 4. 当前优先级

当前从第 22 轮开始执行。

优先级排序：

1. R1 Narrative Guardrail 实检查
2. R2 Trace / 可观测性
3. R5 前端管理层体验收口
4. R3 Learning / Harness 闭环
5. R4 Semantic Graph 深化
6. R6 External Benchmark Provider
7. R7 交付与运维

---

## 5. 无人值守执行规则

- 每轮必须包含代码、测试、文档。
- 每轮必须跑：
  - 后端 unittest
  - semantic eval
  - 前端 build，除非该轮明确不涉及前端且已有说明。
- 若出现 sandbox/权限导致的构建问题，在允许范围内重跑验证。
- 若涉及数据库结构、安全权限、外部付费服务，暂停并等待用户确认。
- 每轮完成后写入 `docs/06_EXECUTION_LOGS`。
- 继续执行下一轮，直到达到交付状态或遇到高风险决策点。
