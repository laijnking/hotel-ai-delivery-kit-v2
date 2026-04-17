# Skill / Harness / Hermes 架构进展回顾

本文档用于回顾当前 Skill、Harness、自学习闭环的落地进展，并评估 Hermes Agent / OpenClaw 体系对本项目的参考价值。

结论先行：本项目不适合直接引入 OpenClaw / Hermes 作为线上运行时，但非常适合吸收其“Skill 化能力沉淀、持久记忆、消息入口、调度任务、工具隔离、可观察执行轨迹”的思想。酒店经营分析属于高口径风险场景，应该坚持“候选学习 + Harness 评测 + 人工审核 + 受控发布”，而不是让 agent 自动改线上规则或自动执行高权限操作。

## 1. 当前进展

### 1.1 Skill 已落地的部分

当前系统已经具备第一版 Skill Registry：

- `backend/skills/registry.yaml`：管理可用 Skill 列表、文件路径、启用状态和版本。
- `hotel_operation_overview.yaml`：覆盖“经营情况怎么样、经营状况如何、整体经营情况”等经营总览问题，默认以经营利润为锚点，同时要求带出收入质量、客房效率、利润质量、成本效率和横向对标。
- `hotel_income_overview.yaml`：覆盖“收入情况、收入怎么样、营收表现、总收入情况”等收入类问题。
- `hotel_profit_overview.yaml`：覆盖“经营情况、经营利润、利润情况、经营表现”等利润类问题。
- `semantic-service` 已经在解析结果中返回 `skill_id`、`skill_version`、`matched_skill_trigger`，说明一次用户提问已能映射到具体业务能力包。

这一步的价值是：系统不再完全依赖全局关键词和散落配置，而是开始把高频业务问题沉淀为可版本化、可评测、可扩展的 Skill。

### 1.2 Harness 已落地的部分

当前 Harness 已经具备第一版离线评测：

- `backend/evals/cases/semantic_sql_cases.yaml`：沉淀真实问题案例，包括广州丽思卡尔顿酒店、公寓、江门嘉华、北京富力万丽、海南区、广州柏悦、未达预算方向等。
- `backend/evals/run_eval.py`：离线加载语义服务、指标服务、SQL 生成逻辑，验证语义解析、SQL 关键断言和回答质量断言。
- 单元测试已集成 Harness，避免后续改 Skill、实体词库或 SQL 策略时造成明显业务退化。

当前 Harness 已覆盖“语义 + SQL + 部分回答质量”。回答质量断言已经可以检查章节是否包含收入质量、客房效率、利润质量、成本效率、横向对标，也能禁止出现过度定性结论。下一阶段需要继续扩展到真实数据结果断言和更多 answer case。

### 1.3 Learning Inbox 已落地的部分

当前系统已经具备学习样本沉淀机制：

- `ai-query-service` 会在澄清、低置信度、空结果、上游 fallback 等场景写入 learning inbox。
- 样本落在 `backend/runtime/learning_inbox/learning-YYYY-MM-DD.jsonl`。
- `backend/evals/summarize_learning_inbox.py` 可以统计失败原因、阶段分布和高频问题。

这一步已经形成“失败样本可回收”的基础，但还没有形成“候选改进自动生成”和“人工审核发布”的完整闭环。

### 1.4 两张宽表利用进展

当前数据源分工已经更清晰：

- `wddm_dim_overview_cockpit_f`：作为经营驾驶舱宽表，适合单店、多店、区域、品牌、档次等维度的经营总览。
- `vw_pnl_fact`：作为 P&L 科目明细视图，适合做收入、成本、利润的科目级穿透和原因分析。

近期已补强 `wddm_dim_overview_cockpit_f` 的使用：总览查询不再只取单指标，而是一次带回收入结构、客房效率、利润、成本、区域、品牌、档次等上下文字段，使解释服务可以基于真实字段做经营拆解。

## 2. 当前不足

### 2.1 Skill 粒度还偏少

当前已具备经营总览、收入总览和利润总览三个 Skill，但仍不足以覆盖管理层真实问题。下一批应该优先补齐：

- `multi_hotel_compare`：多酒店横向对比。
- `area_operation_overview`：区域经营表现。
- `brand_operation_overview`：品牌或子品牌表现。
- `hotel_profit_driver`：调用 `vw_pnl_fact` 做 P&L 科目穿透。
- `follow_up_rewrite`：处理“继续展开原因”“只看华南区”“换成同比”等二次追问。
- `latest_period_resolver`：自动识别最新可用账期，避免用户感知 `time_scope=202601`。

### 2.2 自学习还停在“记录样本”

当前 learning inbox 只是记录问题，还没有自动生成候选改进。下一步应增加候选生成器：

- 从空结果中提取可能的酒店别名问题。
- 从低置信度解析中提取新增触发词建议。
- 从用户纠错中生成 eval case。
- 从高频问题中生成候选 Skill 示例。
- 从 SQL fallback 中识别数据源或字段映射缺口。

候选改进只能进入 `proposals/` 或配置后台的“待审核”状态，不能直接上线。

### 2.3 Harness 还缺少回答质量评测

当前 Harness 已开始判断“回答是否像酒店运营专家”，但样本数量仍少。建议继续新增 answer case：

- 必须出现：收入质量、客房效率、利润质量、成本效率、横向对标。
- 禁止直接下：好/坏/健康/承压/建议立即整改等定性结论。
- 如果缺字段，必须明确说明“当前未取数/当前结果未包含”，不能编造。
- 金额必须使用千位分隔符。
- 横向对标必须说明样本范围，如同区域、同品牌、同档次。

### 2.4 配置管理还未产品化

快捷提问、模型配置、回答模板、Skill 启停、评测结果仍主要以文件形式维护。后续可以做一个移动端友好的“系统设置”入口，但第一阶段建议只做只读视图，避免业务人员误改线上配置。

## 3. Hermes / OpenClaw 体系研究

### 3.1 Hermes Agent 的可借鉴点

Hermes Agent 官方仓库将其定位为带内置学习循环的自改进 agent，强调从经验中创建 skill、使用中改进 skill、持久化记忆、跨会话搜索、消息网关、cron 调度、子代理并行、MCP 工具接入和多种终端后端。

对本项目有帮助的不是“直接换框架”，而是这些架构思想：

- Skill 是可演进的过程记忆，不只是 prompt。
- 记忆需要分层：用户偏好、业务实体、失败样本、已验证规则应分开。
- 消息网关适合移动办公，但应接企业微信/钉钉/飞书等企业入口，而不是泛化个人 IM。
- Cron 调度适合经营日报、周报、月报自动生成。
- 子代理并行适合后台评测、学习样本聚类、报表生成，不适合在线请求链路过度并行。
- MCP/工具生态适合后续接入 BI、文档库、预算系统、经营日报库。

### 3.2 OpenClaw / Hermes 迁移文档的启发

Hermes 的 OpenClaw 迁移文档显示，两者都关注 agent 行为配置、session reset、MCP servers、消息平台、审批模式、命令 allowlist、工作目录、cron、skills registry、memory backend 等能力。

这对本项目的启发是：我们也应该把配置分成几个清晰层次：

- `agent_behavior`：模型、推理强度、超时、上下文压缩。
- `skills_registry`：Skill 启停、版本、默认策略。
- `tool_policy`：SQL、文件、网络、报表导出等工具权限。
- `memory_policy`：哪些内容可长期记忆，哪些只进 learning inbox。
- `approval_policy`：哪些候选变更需要人工确认。
- `schedule_policy`：日报、周报、月报等自动任务。
- `gateway_policy`：移动端、企业 IM、Web 前端的入口配置。

### 3.3 不建议直接照搬的部分

酒店经营助手不是通用个人 agent，不能照搬 OpenClaw / Hermes 的高自治模式：

- 不应让 agent 自动修改生产 Skill 或指标口径。
- 不应让模型自由生成 SQL 直接查库。
- 不应默认开放 shell、文件、浏览器、外部网络等宽权限。
- 不应把用户反馈直接写入线上规则。
- 不应把管理层移动端对话变成复杂命令行或 slash command 体验。

更稳妥的方式是：线上问答保持窄权限、强结构、可追踪；后台学习可以更 agentic，但必须被 Harness 和审批门禁约束。

## 4. 推荐目标架构

建议目标架构如下：

```text
Mobile Chat UI
  -> Conversation Context
  -> Skill Router
  -> Slot Resolver
  -> Query Planner
  -> SQL Strategy
  -> Guardrail
  -> Data Executor
  -> Analysis Composer
  -> Explanation Template
  -> Trace / Learning Inbox

Offline Learning Loop
  -> Learning Inbox
  -> Failure Clustering
  -> Candidate Skill / Alias / Eval Proposal
  -> Harness
  -> Human Review
  -> Skill Registry Release
```

在线链路要稳定、快、可解释；离线链路可以慢一些、深一些、自动化程度高一些。

## 5. 推荐数据与能力分层

### 5.1 数据源层

- `wddm_dim_overview_cockpit_f`：总览指标包，优先服务管理层“怎么看”的问题。
- `vw_pnl_fact`：科目穿透，优先服务“为什么、由哪些科目造成”的问题。
- `dim_allhotel_slcp`：酒店维度补充，包括区域、品牌、档次、城市级别、建设方等。
- `basedata`：实体词库来源，支撑自然语言里的酒店、区域、品牌、管理方识别。

### 5.2 Skill 层

每个 Skill 应包含：

- 触发词和典型问法。
- 槽位定义，如酒店、区域、品牌、时间、对比口径。
- 适用数据源。
- SQL strategy。
- 回答框架。
- eval cases。
- 版本和启用状态。

### 5.3 Harness 层

Harness 应覆盖四类断言：

- Semantic：意图、指标、时间、实体是否正确。
- SQL：表、字段、过滤条件、排序、限制是否正确。
- Data：是否返回预期样本范围，是否误用 fallback。
- Answer：是否符合酒店运营分析框架，是否避免编造和过度结论。

### 5.4 Learning 层

Learning 不直接改线上系统，只产出候选：

- `alias_proposal`：实体别名建议。
- `skill_example_proposal`：Skill 示例建议。
- `eval_case_proposal`：新增评测样本。
- `template_proposal`：回答模板修订。
- `metric_mapping_proposal`：指标字段映射修订。

## 6. 分阶段路线

### 阶段 A：补齐 Skill 覆盖

优先新增：

- `hotel_profit_driver`
- `area_operation_overview`
- `brand_operation_overview`
- `multi_hotel_compare`
- `follow_up_rewrite`
- `latest_period_resolver`

验收标准：

- 用户问单店、多店、区域、品牌、不同月份时都能命中明确 Skill。
- 解析结果包含 `skill_id`、时间、实体、对比口径和数据源策略。

### 阶段 B：补齐 Harness 四段评测

优先做：

- 扩充到 30-50 个真实问题 case。
- 继续增加 answer assertions。
- 增加数据源断言，防止真实库不可用时无声掉到示例 fallback。
- 每次开发后生成评测报告。

验收标准：

- 语义、SQL、数据、回答四类回归都能定位失败原因。
- 修改 Skill 或实体词库时，能明确看到是否退化。

### 阶段 C：候选学习闭环

优先做：

- Learning Inbox 聚类。
- 自动生成 `proposals/*.yaml`。
- 人工审核后转为 Skill 示例、实体别名或 eval case。

验收标准：

- 高频空结果能自动归类为实体别名或账期问题。
- 高频低置信度问题能自动建议新增 Skill 触发词。
- 用户纠错能沉淀为回归样本。

### 阶段 D：配置后台与发布门禁

优先做：

- 系统设置只读页：快捷提问、模型、Skill、模板、评测结果。
- Skill 编辑草稿态。
- Harness 通过后才允许发布。
- 发布记录可追踪、可回滚。

验收标准：

- 业务人员可以参与调优，但不会直接破坏线上规则。
- 每次发布都有评测报告和变更记录。

## 7. 本项目应采纳的 Hermes 化能力

建议采纳：

- Skill Registry：已开始落地，继续增强。
- Memory / Learning Inbox：保留结构化失败样本，不直接污染线上规则。
- Cron：后续用于经营日报、周报、月报自动生成。
- Gateway：后续可接企业 IM，服务管理层移动办公。
- Tool Policy：把 SQL、报表导出、外部数据源接入统一纳入工具策略。
- Trace：每次问答保留 Plan、Parse、SQL、Data、Explain、Learn 的可观察轨迹。

暂不采纳：

- 高权限 shell agent。
- 自动改线上配置。
- 自由 SQL 生成。
- 未审核的自创建 Skill 直接上线。
- 泛化个人 IM 入口。

## 8. 近期任务建议

下一轮建议按这个顺序推进：

1. 新增 `hotel_profit_driver` Skill，明确使用 `vw_pnl_fact` 做 P&L 科目穿透。
2. 新增 `latest_period_resolver`，默认取数据库最新账期，隐藏 `time_scope=202601`。
3. 扩展更多 answer assertions，覆盖单店、多店、区域、品牌和不同时间维度。
4. 建立 `learning_proposals` 目录，把 learning inbox 聚类结果转为待审核候选。
5. 新增 `area_operation_overview` 与 `brand_operation_overview`，让管理层按区域和品牌提问时也能走经营总览框架。

## 9. 参考资料

- Hermes Agent GitHub: https://github.com/NousResearch/hermes-agent
- Hermes OpenClaw migration guide: https://hermes-agent.nousresearch.com/docs/guides/migrate-from-openclaw
- ClawKeeper / OpenClaw 安全研究：建议只作为风险提醒，不作为项目依赖。
