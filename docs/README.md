# Docs Index

本目录用于统一管理项目架构、专题设计、执行记录、部署运维与交付说明。根目录只保留本文档作为入口，其余文档按编号目录归档。

## 0. 编号规则

- `01_OVERVIEW`：项目总览、代码架构、阶段总结。
- `02_ARCHITECTURE_EVOLUTION`：架构演进、报告模板、多 Agent、业务 PPT 驱动方案。
- `03_SEMANTIC_AND_MODEL`：语义层、模型边界、Skill / Harness / Hermes。
- `04_DATA_AND_BENCHMARK`：本地数据仓、外部行业对标。
- `05_PRODUCT_EXPERIENCE`：前端体验、ChatGPT 交互对齐、管理层移动端体验。
- `06_EXECUTION_LOGS`：阶段执行记录。
- `07_OPERATIONS_DELIVERY`：启动、部署、性能、交付和演示。
- `99_DOCUMENTATION_GOVERNANCE`：文档规范和治理规则。

## 1. 总览入口

- `01_OVERVIEW/PROJECT_REVIEW_AND_ARCHITECTURE.md`
  项目整体复盘、目标、建设过程和技术框架总入口。
- `01_OVERVIEW/ARCHITECTURE_OVERVIEW.md`
  当前实际代码架构、服务调用关系、数据流与后续重构重点。
- `01_OVERVIEW/PROJECT_SUMMARY.md`
  面向交接和回顾的项目阶段总结。

## 2. 架构与演进

- `02_ARCHITECTURE_EVOLUTION/HIGH_EFFICIENCY_MULTI_AGENT_ARCHITECTURE.md`
  高效率多 Agent 架构与阶段演进路线。
- `02_ARCHITECTURE_EVOLUTION/PPT_DRIVEN_FRAMEWORK_ENHANCEMENT_PLAN.md`
  结合业务汇报材料，对现有问答框架升级为经营分析编排框架的专题方案。
- `02_ARCHITECTURE_EVOLUTION/PROJECT_ITERATION_PLAN.md`
  当前项目迭代计划、阶段优先级和验收样例。
- `02_ARCHITECTURE_EVOLUTION/SEMANTIC_ROUTING_EXECUTION_CHECKLIST.md`
  语义路由重构的可实施任务清单，包含批次拆分、代码落点和验收方式。
- `02_ARCHITECTURE_EVOLUTION/REPORT_TEMPLATE_REVISION_PLAN.md`
  常用经营报告驱动的报告模板化修订方案。
- `02_ARCHITECTURE_EVOLUTION/PHASE_ROADMAP_REVIEW.md`
  当前阶段路线回顾与后续推进建议。

## 3. 语义与模型

- `03_SEMANTIC_AND_MODEL/SEMANTIC_DIMENSION_LAYER.md`
  业务维度识别层与语义维度扩展。
- `03_SEMANTIC_AND_MODEL/LLM_REASONING_BOUNDARY.md`
  规则、维度图谱与大模型推理边界。
- `03_SEMANTIC_AND_MODEL/SEMANTIC_ROUTING_REFACTOR_PLAN.md`
  面向前端自由提问场景的语义路由重构方案，重点说明为何从 `rule-first` 调整为 `LLM-first + guardrail`。
- `03_SEMANTIC_AND_MODEL/SKILL_HARNESS_EVOLUTION_PLAN.md`
  Skill / Harness 自学习架构演进方案。
- `03_SEMANTIC_AND_MODEL/SKILL_HARNESS_HERMES_REVIEW.md`
  Skill / Harness / Hermes 方向评估。

## 4. 数据与对标

- `04_DATA_AND_BENCHMARK/LOCAL_WAREHOUSE.md`
  本地 DuckDB 分析缓存说明。
- `04_DATA_AND_BENCHMARK/EXTERNAL_BENCHMARK_PROVIDER.md`
  外部行业对标 Provider 设计与当前实现进展。

## 5. 产品与体验

- `05_PRODUCT_EXPERIENCE/CHATGPT_EXPERIENCE_ALIGNMENT_PLAN.md`
  酒店经营 AI 助手对齐 ChatGPT 交互体验的差距梳理、需求清单与开发优先级。
- `05_PRODUCT_EXPERIENCE/FRONTEND_EXECUTIVE_EXPERIENCE_LOG.md`
  前端管理层体验整改记录。

## 6. 执行记录

- `06_EXECUTION_LOGS/PHASE3_EXECUTION_LOG.md`
  第三阶段最近一轮开发执行过程、验证方式与结果。

## 7. 运维与交付

- `07_OPERATIONS_DELIVERY/LOCAL_STARTUP.md`
  本地启动说明。
- `07_OPERATIONS_DELIVERY/DEPLOYMENT_NOTES.md`
  部署与环境注意事项。
- `07_OPERATIONS_DELIVERY/PERFORMANCE_TUNING.md`
  性能调优记录。
- `07_OPERATIONS_DELIVERY/DELIVERY_CHECKLIST.md`
  交付核对清单。
- `07_OPERATIONS_DELIVERY/DEMO_SCRIPT.md`
  演示脚本。

## 8. 文档规范

- `99_DOCUMENTATION_GOVERNANCE/DOCUMENTATION_STANDARDS.md`
  文档分类、命名、内容结构、更新规则与入口管理规范。
