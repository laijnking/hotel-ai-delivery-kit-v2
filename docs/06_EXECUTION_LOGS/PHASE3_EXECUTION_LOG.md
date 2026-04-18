# 第三阶段执行记录

本文档记录“`Analysis Agent + Narrative Agent` 继续向 `Learning Agent + External Benchmark Provider` 演进”这一轮的执行过程、代码落点、验证方式与当前结果。

## 1. 本轮目标

本轮目标不是直接接入真实外部行业源，而是先把第三阶段需要的两个基础底座补齐：

1. 学习闭环不再只写入 `learning_inbox`，而是要能被系统回看、统计和后续 Harness 消费。
2. 外部对标不再只有单一占位状态，而是要明确区分不同 Provider 的就绪状态和限制说明。

## 2. 执行过程

### 2.1 梳理现状

先检查了当前后端已有能力：

- `ai-query-service` 已经具备 `learning_reason()` 和 `write_learning_sample()`，说明低置信解析、空结果和澄清需求已经会落盘。
- `build_external_benchmark_stub()` 已经存在，但当时只有一个统一的 `manual_review` 风格占位返回。
- `backend/runtime/learning_inbox` 中已经积累了多天真实样本，说明学习闭环已经有输入源，只是缺少“汇总输出层”。

### 2.2 补学习汇总能力

在 `ai-query-service` 中新增了三层学习闭环辅助函数：

- `_learning_metadata()`
  统一补充 `metric_code / compare_mode / query_object_type / query_grain / analysis_mode / external_benchmark_status` 等元数据。
- `read_learning_records()`
  从 `learning_inbox` 读取最近 N 天样本。
- `summarize_learning_records()`
  汇总原因分布、指标分布、查询对象分布、阶段分布和最近样本。

同时新增接口：

- `GET /api/v1/system/learning/summary?days=7`

这个接口是 `Learning Agent` 后续接 Harness、挑样本和观察问题类型的第一层底座。

### 2.3 补外部对标 Provider 状态层

把原本单一的 `build_external_benchmark_stub()` 拆成四类 Provider：

- `manual_review`
- `uploaded_dataset`
- `industry_api`
- `web_research`

每个 Provider 都会返回：

- `provider`
- `status`
- `dimensions`
- `message`
- `disclaimers`

其中：

- `uploaded_dataset` 会检查本地外部数据目录是否已有文件。
- `industry_api` 会检查 API 是否已配置。
- `web_research` 会返回联网研究状态和允许域名配置。

这样前端在开启“外部行业对标”后，不会再误以为系统已经拿到了真实外部行业样本。

### 2.4 回写学习样本元数据

把学习元数据真正挂进写回流程：

- 澄清场景：在 `clarification_required` 写回时补齐元数据。
- 查询完成场景：在 `low_confidence_parse / empty_result / upstream_fallback_or_warning` 写回时补齐元数据。

这一步的意义是后续做 Learning Agent 汇总时，能按“问题类型、对象粒度、指标口径”看问题，而不只是按 reason 粗看。

### 2.5 文档同步

同步更新了：

- `../04_DATA_AND_BENCHMARK/EXTERNAL_BENCHMARK_PROVIDER.md`
- `../02_ARCHITECTURE_EVOLUTION/HIGH_EFFICIENCY_MULTI_AGENT_ARCHITECTURE.md`

让当前阶段不再只是架构设想，而是明确记录“已经实现到哪一步、还没做哪一步”。

## 3. 验证过程

### 3.1 单元测试

补充了两类测试：

1. 学习汇总测试

- 写入两条样本
- 调用 `system_learning_summary(days=7)`
- 断言样本数、原因分布、最近样本和指标分布正确

2. Provider 状态测试

- 临时把 provider 切到 `uploaded_dataset`
- 在空目录下调用 `build_external_benchmark_stub()`
- 断言返回 `dataset_missing`

实测结果：

- 使用项目 `.venv` 执行 `python -m unittest ...`
- `Ran 41 tests in 14.012s`
- `OK`

### 3.2 在线接口验证

重启 `ai-query-service` 后，实际验证了两条链路：

1. 学习汇总接口

- 访问：`http://127.0.0.1:8100/api/v1/system/learning/summary?days=7`
- 返回正常
- 当前 7 天学习样本数：`25`
- Top reasons：
  - `low_confidence_parse = 13`
  - `empty_result = 8`
  - `clarification_required = 4`

2. 问答主链路中的外部对标返回

- 问题：`看一下江门嘉华酒店3月的经营情况`
- 开启 `external_benchmark=true`
- 主查询仍正常返回
- `external_benchmark` 字段返回：
  - `provider = manual_review`
  - `status = awaiting_provider`
  - 同时附带免责声明和内部样本提示

这说明第三阶段新增能力没有破坏现有主问答链路。

## 4. 当前结果

本轮完成后，系统在第三阶段已经具备了下面这些可用能力：

- 学习样本可回看
- 学习样本可统计
- 学习样本已带业务元数据
- 外部对标 Provider 可分流
- 前端已可以据此判断“外部对标是否真正就绪”

## 5. 当前边界

目前仍然保留这些边界：

- `Learning Agent` 还没有自动生成候选规则、候选 Skill 或候选 Harness 样本集。
- `uploaded_dataset` 还只是状态层，尚未真正把外部样本读入统一仓。
- `industry_api` 和 `web_research` 还没有进入真实联网抓取执行链。

## 6. 下一步建议

下一步最适合继续推进三件事：

1. 基于 `learning/summary` 自动挑选 Harness 回归样本。
2. 把 `uploaded_dataset` 接入真正可读取的外部行业样本仓。
3. 把 `industry_api` 或 `web_research` 接到受控联网抓取链路，并返回来源、发布日期、口径和失败状态。

## 7. 后续续推进展

在本轮记录之后，系统又往前推进了一步：已经把学习样本开始转成 Harness 候选 case。

新增接口：

- `GET /api/v1/system/learning/harness-candidates?days=7&limit=10`

当前能力：

- 从最近学习样本中挑选候选问题
- 去重相同问题
- 生成适合 eval 使用的候选结构
- 自动补出：
  - `id`
  - `question`
  - `time_scope`
  - `expected`
  - `sql_assertions.contains`
  - `source_trace_id`
  - `reason`

这意味着学习闭环已经不只是“统计面板”，而是开始具备：

- 从真实失败样本反推回归样本
- 为后续 Harness 自动扩样提供基础入口

当前这一步仍属于候选生成层，尚未自动写回 `backend/evals/cases/semantic_sql_cases.yaml`，也还没有自动运行回归。

## 8. NOP 业主净利润优先口径修订

本轮根据业务口径补充了一项关键调整：管理层关注利润时，默认优先展示 `NOP业主净利润`，`经营利润（GOP）`作为补充口径展示。

已完成调整：

- 语义层把“经营情况、经营状况、经营表现、利润”等宽泛问法默认映射到 `OWNER_PROFIT`。
- 如果用户明确问“经营利润”或“GOP”，仍保留 `OPERATING_PROFIT`，避免覆盖明确口径。
- 指标字典新增并启用 `OWNER_PROFIT`，字段口径为 `OWNER_PROFIT_MTD_A/B/L`。
- 组合汇总和异常酒店识别中，利润强弱优先按 `owner_profit_actual` 判断。
- 解释服务的利润质量、经营总览、组合摘要均优先输出 NOP，再补充 GOP。
- 前端指标名称和维度汇总卡片显示 `NOP业主净利润`，并在必要时同时展示 GOP。

回归验证：

- 问题：`汇总一下这个月的经营情况`
- 语义结果：`metric_code = OWNER_PROFIT`
- 指标名称：`NOP业主净利润`
- 范围：`公司全部酒店`
- 粒度：`portfolio`
- 样本：`83` 家
- 数据结果：`data_points` 为 1 条组合汇总，不再返回 50 条酒店明细。
- SQL 检查：组合汇总 SQL 不包含 `LIMIT 50`。
- 服务健康：`3000`、`8100-8107` 均返回 `200`。
- 自动化验证：后端 9 个目标回归测试通过，前端 `npm run build` 通过。

## 9. P0 管理公司/区域分组汇总修复

本轮继续推进 P0 主链路，重点验证问题：

`请分析一下公司所有酒店3月份的经营情况，请汇总到管理公司和区域维度输出`

发现问题：

- 语义层已经能识别为 `group_by_dimension_report`。
- `query_plan.group_by_dimensions` 已包含 `manage_corp`、`area`、`manage_corp_area`。
- 区域维度可以返回真实数据。
- 但管理公司和管理公司 x 区域维度在本地仓库 SQL 执行失败后，被 `db-executor-service` 兜底成了 `示例酒店A/示例酒店B`，这是不可接受的演示数据泄漏。

根因：

- DuckDB 在 `GROUP BY manage_corp` 时优先解析到源字段名，而不是 SELECT 别名。
- 由于 SELECT 表达式为 `COALESCE(o.manage_corp, s.brand)`，DuckDB 要求 `s.brand` 也进入 GROUP BY。
- 查询失败后，执行器 fallback 返回示例数据，导致前端展示不可信。

已完成修复：

- 分组 SQL 改为 `GROUP BY 1` / `GROUP BY 1, 2`，避免别名与源字段冲突。
- `db-executor-service` 对分组 SQL 禁止返回示例 fallback；如果真实查询失败，返回空分组而不是假数据。
- 重点酒店与梯队文案继续强化 NOP 优先：利润排名和梯队优先使用 `NOP业主净利润`，GOP 作为辅助指标。
- Eval Harness 同步更新为新业务口径：宽泛“经营情况/利润情况”默认 `OWNER_PROFIT`，明确“经营利润/GOP”才走 `OPERATING_PROFIT`。

回归结果：

- 管理公司维度：真实返回 2 组，`国际品牌 32 家`、`万达品牌 51 家`。
- 区域维度：真实返回 8 组。
- 管理公司 x 区域维度：真实返回 13 组。
- 接口返回不再包含 `示例酒店A/示例酒店B`。
- 后端全量测试：`Ran 52 tests in 14.086s`，结果 `OK`。

## 10. P1 模板与指标包配置化起步

本轮开始进入 P1，把原来写死在代码里的经营摘要结构和指标包，抽成配置文件，目标是让后续业务调模板时不必继续改 Python 逻辑。

已新增配置：

- `backend/configs/metric_bundles.yaml`
- `backend/configs/report_templates.yaml`

当前已接入能力：

- `semantic-service` 在 `query_plan` 中新增：
  - `metric_bundle_code`
  - `report_template_code`
- 组合分维度问题当前会返回：
  - `metric_bundle_code = group_dimension_overview`
  - `report_template_code = executive_group_dimension`
- `query_plan.metrics` 不再只含单一指标，而是可以返回指标包里的多指标清单。
- `explanation-service` 已读取 `report_templates.yaml`，按模板里的 `section_order` 输出章节顺序。

本轮同时补了两项体验优化：

- 前端 `dimension_breakdowns` 区块增加移动端卡片样式、排序序号和差额提示，弱化调试感。
- 指标包中的显示名补齐为中文业务口径，例如 `入住率`、`人工成本`、`餐饮成本`，避免返回底层字段码。

回归结果：

- 目标问题：`请分析一下公司所有酒店3月份的经营情况，请汇总到管理公司和区域维度输出`
- 当前接口已返回：
  - `analysis_mode = group_by_dimension_report`
  - `metric_bundle_code = group_dimension_overview`
  - `report_template_code = executive_group_dimension`
- 章节顺序已按模板生效：`分析范围 -> 经营总览 -> 管理公司/区域汇总 -> 收入质量 -> ...`
- 前端 `npm run build` 通过。
- 模板/指标包相关回归测试通过。

## 11. P1 模板显示控制落地

在上一轮配置化之后，模板还只能控制章节顺序，不能真正决定“哪些章节该出现”。本轮继续推进，让模板从排序器升级为显示控制器。

新增能力：

- `report_templates.yaml` 增加 `include_sections`。
- `explanation-service` 现在会先按模板过滤章节，再按模板排序。
- 不同问题类型开始真正走不同模板，而不是共用一套章节后只改顺序。

当前验证结果：

1. 集团/组合分维度问题

- `analysis_mode = group_by_dimension_report`
- `metric_bundle_code = group_dimension_overview`
- `report_template_code = executive_group_dimension`
- 返回章节：
  - `分析范围`
  - `经营总览`
  - `管理公司/区域汇总`
  - `收入质量`
  - `客房效率`
  - `利润质量`
  - `成本效率`
  - `重点酒店与梯队`
  - `横向对标与继续追问`

2. 单店经营快照问题

- `analysis_mode = hotel_metric_snapshot`
- `metric_bundle_code = hotel_snapshot`
- `report_template_code = executive_hotel_snapshot`
- 返回章节：
  - `分析范围`
  - `收入质量`
  - `客房效率`
  - `利润质量`
  - `成本效率`
  - `横向对标`

这意味着单店问题已经不会再机械展示组合专属章节，比如：

- `经营总览`
- `重点酒店与梯队`
- `管理公司/区域汇总`

本轮价值：

- 模板开始具备真正的产品化意义，后续业务要改“集团看什么、单店看什么、组合看什么”，优先改 YAML，而不是继续改后端硬编码。

## 12. 无人值守多 Agent 第 1 轮集成

本轮按 `AUTONOMOUS_MULTI_AGENT_EXECUTION_PLAN.md` 进行了首次并行开发集成，重点把 `Semantic / Planner`、`Bundle-driven Query`、`Template-driven Explanation` 和 `Frontend Template UI` 四条主线拧在一起。

本轮完成项：

- `semantic-service`
  - 新增 `conversation_context`，开始承接“继续展开原因”、“只看华南区”这类追问。
  - `query_plan` 新增 `analysis_focus`、`follow_up_mode`，让上游开始表达“这次是展开原因、缩范围、还是切同比”。
  - 补了维度噪声过滤，降低“品牌酒店”、“汇总”被误解为酒店名或科目名的概率。

- `ai-query-service`
  - 接入 `metric_dictionary.yaml` + `metric_bundles.yaml`，不再硬编码指标上下文字段集。
  - `build_sql`、`build_portfolio_sql`、`build_dimension_breakdown_sql` 开始真正按 bundle 决定携带哪些字段，并按 `aggregation=sum/avg` 自动选择聚合方式。
  - 默认 fallback 不再只带单一主指标，而是回退到 `operation_overview` / `income_overview`。

- `explanation-service`
  - 模板层开始真正区分：`executive_portfolio`、`executive_group_dimension`、`executive_hotel_snapshot`。
  - bundle 决定“讲什么”，template 决定“怎么摆章节”。
  - 单店快照不再混入组合梯队章节，分维度报告会优先给出 `分维度经营摘要` + `管理公司/区域汇总`。

- `frontend`
  - 结果页开始按 `report_template_code` 分流，不同问题类型不再共用同一套阅读节奏。
  - 新增 `result-briefing`、`leadership-section-card`、`dimension-breakdown-card` 等样式，比之前更像管理层简报，而不是调试面板。

追加验证：

- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`
  - `Ran 62 tests ... OK`
- `python -m py_compile`
  - `ai-query-service / semantic-service / explanation-service / db-executor-service` 通过
- `frontend`
  - `npm run build` 通过

本轮阶段性结论：

- 阶段 A 里的“规则 + 模型补位”已经开始过渡到“Planner + Bundle + Template”。
- 后续将继续往下推进：让 `analysis_focus` 和 `follow_up_mode` 更深地进入查询编排、追问筛选和叙事结构。

## 13. 连续追问链路补全与回归稳定性修复

本轮继续把“连续追问更自然”这条线往下补，重点不是再加新模板，而是把上下文真正透传到后端，并让快速筛选/建议问题跟随当前追问状态变化。

本轮完成项：

- `frontend`
  - 新增 `buildSemanticConversationContext()`，把当前会话上下文映射成后端语义层能直接消费的字段：
    - `metric_code`
    - `compare_mode`
    - `time_scope`
    - `requested_hotels`
    - `requested_areas`
    - `query_plan.analysis_mode`
    - `query_plan.analysis_focus`
  - 提交问答和报告时，`context.conversation_context` 会一并发送到后端，不再只是前端本地改写追问。
  - `extractContext()` 现在把 `compare_mode` 和 `analysis_mode` 分开存储，避免把分析方式误当成口径。
  - `getFollowUpSuggestions()` 开始按当前上下文动态裁剪：
    - 已在归因态时，不重复推荐“继续展开原因”
    - 已在收入结构态时，不重复推荐“分析收入结构”
    - 已在经营摘要态时，不重复推荐“换成经营摘要”

- `ai-query-service`
  - `QueryContext` 新增 `conversation_context`。
  - 调用 `semantic-service` 时正式透传 `conversation_context`，连续追问开始走完整的后端理解链路。
  - `build_quick_filters()` 新增 `进一步` 这一组快捷筛选，结合：
    - `analysis_focus`
    - `follow_up_mode`
    - `analysis_mode`
    自动给出更贴近当前问题的下一步动作，例如：
    - `收入结构`
    - `利润成本`
    - `同比变化`
    - `继续原因`

- `tests`
  - 新增/调整快速筛选相关回归：
    - 组合问题会返回 `进一步`
    - 单店/区域模板顺序同步更新
    - 已处于 `driver` 追问态时，不再重复出现“继续原因”
  - 新增 `workspace_temp_dir()`，把测试临时目录收回到项目工作区，解决 Windows 环境下 `TemporaryDirectory` 清理权限异常的问题。

验证结果：

- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`
  - `Ran 63 tests ... OK`
- `python -m py_compile`
  - `ai-query-service / tests` 通过
- `frontend`
  - `npm run build` 通过

本轮价值：

- 连续追问不再只是“前端帮忙重写一句话”，而是开始真正进入后端语义层的上下文继承。
- “你可以继续问”与快速筛选开始具备状态感，会跟着当前问题形态变化，而不是固定一套建议。

## 14. 无人值守多 Agent 第 2 轮集成

本轮继续按无人值守多 Agent 模式推进，重点不再是“把模板做出来”，而是把 `Planner + Semantic Graph`、`analysis_focus / follow_up_mode`、叙事层和前端交互真正联成一条更自然的连续追问链路。

本轮集成结果：

- `semantic-service`
  - 新增并稳定输出：
    - `dimension_axes`
    - `dimension_signature`
    - `compare_shift`
    - `analysis_focus`
    - `follow_up_mode`
  - 支持“换成同比 / 改成预算”这一类二次追问，不再只支持“继续展开原因”。
  - 强化了品牌、子品牌、区域、酒店、月份、科目层级的联合识别。
  - 补了部门/科目去噪，降低“餐饮部”“利润”等词误入 `requested_accounts` 的概率。

- `ai-query-service`
  - 新增 `query_route`，把单店、区域、组合、分维度汇总等路径显式路由化。
  - `analysis_focus / follow_up_mode` 已下沉到：
    - SQL 排序
    - 维度汇总排序
    - quick filters 排序
    - follow-up prompts 生成
  - `build_quick_filters()` 新增：
    - `管理公司`
    - `进一步`
  - 现在单店 / 区域 / 组合问题会走不同筛选模板，追问建议也更贴当前问题形态。

- `explanation-service`
  - 新增 `focus_profiles` 和 `focus_section_order` 机制。
  - 同一模板下，章节优先级可以随 `analysis_focus` 变化：
    - 收入结构优先看 `收入质量`
    - 利润成本优先看 `利润质量` + `成本效率`
    - 分维度比较优先看 `分维度经营摘要` + `管理公司/区域汇总`
  - 单店、多店、区域、分维度的摘要口吻进一步拉开，但仍保持客观克制，不做过度武断结论。

- `frontend`
  - 顶部入口升级为：
    - `常用切入`
    - `快速筛选`
  - 结果卡底部的“你可以继续问”升级为更显式的续聊面板。
  - 增加了更清晰的状态反馈：
    - `当前已选`
    - `正在处理`
  - 保持模板化结果页风格的同时，进一步降低了技术感。

- `tests`
  - 新增并通过的覆盖项包括：
    - `query_route` 分类
    - `analysis_focus` 影响 SQL 排序
    - `compare_shift` 追问
    - `dimension_axes / dimension_signature`
    - `pnl_hierarchy` 语义回归
    - `build_quick_filters` 的单店 / 区域 / 组合模板排序
    - `focus_profiles` 对章节顺序和追问提示的影响
  - 测试临时目录已收回到项目工作区，修复 Windows 环境下 `TemporaryDirectory` 清理权限异常。

本轮验证结果：

- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`
  - `Ran 72 tests ... OK`
- `.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report`
  - `12/12 passed`
- `frontend`
  - `npm run build` 通过

本轮阶段性价值：

- 连续追问已经从“前端帮忙改写一句话”升级为“前后端共同理解并重新编排查询与表达”。
- 系统开始从“模板化展示”进一步进入“问题类型驱动的查询编排 + 叙事编排”阶段。

## 15. 第 23 轮：Trace Event Contract

本轮继续推进剩余无人值守交付计划中的 R2 可观测性任务，重点是先建立后端统一 trace 契约，让一次问答可以被拆成可追踪的处理阶段。

本轮完成内容：

- `ai-query-service`
  - 新增 `build_trace_events()`。
  - 最终响应新增顶层 `trace_events` 字段。
  - 当前 trace 阶段包括：
    - `parse_intent`
    - `sql_guardrail`
    - `execute_sql`
    - `build_analysis_blocks`
    - `build_narrative_brief`
    - `pipeline_warnings`，仅在存在 warning 时输出
  - `build_narrative_brief` 阶段会透出 `narrative_agent.guardrail.status`，为后续定位叙事层是否过度表达提供依据。

- `tests`
  - 新增 `test_build_trace_events_includes_core_pipeline_and_agent_metadata`。
  - 覆盖 trace 主阶段存在性和 Narrative Agent guardrail 元信息透传。

本轮验证结果：

- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services.ServiceSmokeTests.test_build_trace_events_includes_core_pipeline_and_agent_metadata`
  - `Ran 1 test ... OK`
- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`
  - `Ran 79 tests ... OK`
- `.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report`
  - `12/12 passed`
  - report: `backend/evals/reports/eval_report_20260417-171325.md`
- `frontend`
  - `npm run build` 通过

阶段性价值：

- 系统从“只看最终答案”开始升级为“可追踪处理链路”。
- 后续排查“识别错、没数据、口径不明、表达重复”等问题时，可以更快定位发生在语义、SQL、数据执行、分析块还是叙事层。
- 下一轮可以在前端增加折叠式调试视图，同时不打扰管理层默认阅读体验。

## 16. 第 24 轮：前端调试视图收口

本轮承接第 23 轮 `trace_events` 后端契约，把 trace 信息接入前端非集团角色的技术诊断区，同时保持集团管理层默认界面隐藏技术细节。

本轮完成内容：

- `frontend`
  - 技术诊断信息新增 `trace_events` 阶段摘要展示。
  - trace 阶段中文化：
    - `parse_intent`：语义理解
    - `sql_guardrail`：口径安全检查
    - `execute_sql`：数据读取
    - `build_analysis_blocks`：分析拆解
    - `build_narrative_brief`：叙事生成
  - 诊断区展示阶段状态、耗时、Agent、Guardrail 状态、数据行数等 metadata。
  - 修复 `conversationContext` 初始化顺序导致的前端运行时错误。
  - `看去年同期` 已纳入 `yoy_change` 连续追问识别。

- `tests`
  - 前端 E2E 更新为当前 PromptBank 交互形态：
    - `starter-prompts`
    - `follow-up-actions`
    - `management-overview`
  - 移除对旧调试式按钮编号和折叠 summary 的依赖。
  - 新增/增强非集团角色可查看 trace 阶段摘要的断言。

本轮验证结果：

- `npm run test:e2e -- tests/management-chat.spec.ts`
  - `14 passed`
- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`
  - `Ran 79 tests ... OK`
- `.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report`
  - `12/12 passed`
  - report: `backend/evals/reports/eval_report_20260417-192203.md`
- `frontend`
  - `npm run build` 通过

补充记录：

- 用户提出后续将 overview 数据源从 `wddm_dim_overview_cockpit_f` 切换到 `vw_overview_cockpit`。
- 当前公网 MySQL 未开放白名单，本轮无法确认新视图字段结构。
- 本地 DuckDB 仓库当前尚无 `vw_overview_cockpit`，因此本轮未启用新数据源，避免引入不可验证的默认查询路径。

阶段性价值：

- Trace 已从后端契约进入前端可查看视图。
- 管理层阅读体验继续保持干净，技术细节只在非集团角色下折叠展示。
- 前端回归测试重新对齐当前产品形态，后续 UI 收口更稳。

## 17. 第 25 轮：Learning Inbox schema v2

本轮推进 Learning / Harness 闭环，把失败、低置信度、无数据等样本升级为可审核、可追踪、可转 eval 的学习材料。

本轮完成内容：

- `ai-query-service`
  - `write_learning_sample()` 升级到 `schema_version = 2`。
  - 新增 `review_status = pending_review`。
  - Learning sample 新增：
    - `analysis_contract`
    - `analysis_blocks`
    - `guardrail`
    - `trace_events`
    - `alias_proposal`
    - `eval_case_proposal`
  - 新增 `build_alias_proposal()`，从解析结果中提取候选酒店、区域、管理公司、子品牌和 query object label。
  - 新增 `build_eval_case_proposal()`，为学习样本生成可转 eval 的候选结构。
  - `system_learning_harness_candidates()` 优先使用样本内的 `eval_case_proposal`。
  - 主查询链路会在写入学习样本时带上 trace、analysis blocks 和 narrative guardrail。

- `tests`
  - 新增 `test_learning_sample_schema_v2_includes_trace_guardrail_and_proposals`。
  - Learning summary 和 harness candidates 旧能力保持兼容。

本轮验证结果：

- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_services`
  - `Ran 80 tests ... OK`
- `npm run test:e2e -- tests/management-chat.spec.ts`
  - `14 passed`
- `.\.venv\Scripts\python.exe backend/evals/run_eval.py --cases backend/evals/cases/semantic_sql_cases.yaml --write-report`
  - `12/12 passed`
  - report: `backend/evals/reports/eval_report_20260417-193131.md`
- `frontend`
  - `npm run build` 通过

补充记录：

- 用户确认 `vw_overview_cockpit` 数据源切换后续再执行。
- 当前公网 MySQL 未加入白名单，无法验证新视图字段结构。
- 本轮没有启用新数据源，避免引入不可验证的数据路径。

阶段性价值：

- 系统开始形成“运行失败 -> 样本沉淀 -> 人工审核 -> alias/eval 配置演进”的闭环。
- 自学习仍保持可控，不自动污染正式语义配置。
