# 语义路由重构执行清单

## 1. 文档目的

本文档用于把 [SEMANTIC_ROUTING_REFACTOR_PLAN.md](../03_SEMANTIC_AND_MODEL/SEMANTIC_ROUTING_REFACTOR_PLAN.md) 拆成可执行任务，便于按批次推进、验收和回写执行记录。

当前默认假设：

- 前端允许用户自由提问，而不是按固定模板输入。
- 语义主链路需要从 `rule-first` 过渡到 `LLM-first + guardrail`。
- 启动配置需要支持无人值守模型模式。

## 2. 总体目标

本轮执行目标不是一次性推翻现有链路，而是分阶段完成三件事：

1. 启用适合自由提问场景的默认模型策略。
2. 为新语义路由补齐契约、观测和开关。
3. 在不破坏现有查询能力的前提下，逐步把快模型提升为主语义入口。

## 3. 批次拆分

### R0：默认运行模式切换

目标：先把系统默认配置切到适合无人值守模型模式的组合。

任务：

- 将默认语义解析策略切到 `QWEN_PARSE_POLICY=always`。
- 将默认解释增强策略切到 `QWEN_EXPLANATION_POLICY=auto`。
- 更新启动脚本、系统设置接口和性能说明文档。
- 在前端技术诊断中暴露当前运行策略。

验收：

- 使用本地启动脚本时，不额外设置环境变量也能看到 `parse_policy=always`。
- 系统设置接口能返回新的默认策略。
- README / 运维文档与实际运行逻辑一致。

### R1：语义路由契约升级

目标：先定义新字段，不立即重写整条语义链。

任务：

- 在 `semantic-service` 输出中新增：
  - `route_mode`
  - `conversation_action`
  - `clarification_type`
  - `semantic_notes`
- 区分“对话动作识别”和“最终执行字段”。
- 为 `parsed_intent` 增加路由层和执行层的区分说明。
- 在 `ai-query-service` trace 中记录路由决策。

验收：

- 任意查询结果都能看到 `route_mode`。
- 连续追问能够记录为 `follow_up_continue` / `refine_scope` / `shift_compare_mode` 等动作。

### R2：Fast LLM First 语义草案

目标：让快模型先产出语义草案，规则改成归一化和校验层。

任务：

- 将 `call_llm_parse()` 从 fallback 升级为主入口之一。
- 新增 `semantic_draft` 概念，承接快模型原始结构化输出。
- 保留现有规则解析，但从“主解析器”调整为“guardrail normalizer”。
- 将模型输出映射回受控枚举值和实体目录。

验收：

- 自由提问命中率明显高于旧链路。
- 规则不再因为高置信误命中而直接跳过模型。
- 模型输出无法直接绕过实体目录、指标字典和权限范围。

### R3：澄清中心化

目标：把澄清从零散规则升级成统一路由。

任务：

- 统一 `clarification_type`：
  - `missing_scope`
  - `missing_metric`
  - `scope_conflict`
  - `ambiguous_entity`
  - `weak_context_anchor`
  - `insufficient_basis_for_conclusion`
- 统一澄清返回结构：
  - `clarification_question`
  - `clarification_options`
  - `missing_slots`
  - `candidate_interpretations`
- 将冲突检测接入酒店 / 区域 / 品牌 / 管理公司图谱。

验收：

- 冲突问题优先澄清，而不是直接查空。
- 简短追问在上下文不足时会明确提示缺什么。

### R4：查询与解释协同

目标：让 explanation 层真正消费语义路由标签。

任务：

- `ai-query-service` 根据 `route_mode` / `conversation_action` 调整查询策略。
- `explanation-service` 根据 `analysis_mode` / `conversation_action` 决定是否启用深模型增强。
- 将“普通查询”“管理摘要”“归因分析”“报告生成”分成更清晰的输出路径。

验收：

- 普通查询不因为默认启用无人值守模型而变成重分析链路。
- 报告 / 归因场景能比普通查询更稳定进入深模型增强。

### R5：评测与回归

目标：避免重构后语义能力不可控回退。

任务：

- 补一组自由提问 eval case，而不只保留标准问法。
- 增加连续追问、改范围、换口径、要结论、要汇报的样本。
- 对比旧链路和新链路：
  - 首轮命中率
  - 澄清率
  - 空结果率
  - 连续追问成功率
  - 平均延时

验收：

- 新链路在自由提问场景优于旧链路。
- 回归测试覆盖常见 query / report / explain / rank 路径。

## 4. 代码落点建议

### 4.1 semantic-service

责任：

- 语义草案生成
- Guardrail 归一化
- 路由决策
- 澄清输出

优先改造函数：

- `should_use_llm_parse`
- `call_llm_parse`
- `merge_rule_and_llm`
- `should_clarify`
- `parse`

### 4.2 ai-query-service

责任：

- 消费新的语义路由字段
- 记录 trace
- 分流到 query / explain / report 路径

优先改造区域：

- `/api/v1/system/settings`
- `/api/v1/ai/query`
- trace / learning sample 写入逻辑

### 4.3 explanation-service

责任：

- 根据语义路由标签决定解释深度
- 在默认启用无人值守模型时避免无意义重调用

优先改造函数：

- `should_use_llm_enhancement`
- `_apply_llm_enhancement`

## 5. 当前建议执行顺序

建议按以下顺序推进：

1. R0：先切默认运行模式。
2. R1：补路由契约和 trace 字段。
3. R2：落 Fast LLM First 语义草案。
4. R3：做统一澄清路由。
5. R4：联动查询与解释。
6. R5：补评测并切默认版本。

## 6. 当前状态

截至 2026-04-20，状态建议标记为：

- R0：进行中
- R1：待开始
- R2：待开始
- R3：待开始
- R4：待开始
- R5：待开始
