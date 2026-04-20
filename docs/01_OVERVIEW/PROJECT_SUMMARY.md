# 酒店经营 AI 助手项目总结

> 更新时间：2026-04-17
> 文档定位：项目整体复盘、架构演进与后续规划

---

## 一、项目目标

本项目面向酒店集团管理层，核心目标是把经营数据查询和经营分析压缩到一个移动端对话入口里：

- **用户输入**：直接用自然语言提问，例如"看一下江门嘉华酒店3月的经营情况"
- **系统自动完成**：识别酒店、区域、月份、指标、对比口径和分析意图
- **输出内容**：管理层可读的结论、核心数据、风险提示和行动建议
- **支持能力**：连续追问、快捷提问、报告模式、多角色视角

当前定位是"可本地运行、可移动端演示、可继续生产化改造"的交付包。

---

## 二、建设历程

项目从一个交付包雏形逐步演进为可连接真实数据和大模型的经营分析助手，主要经历了以下阶段：

### 阶段1：项目启动与文档梳理

- 阅读项目文档，确定本地 Windows 启动优先
- 补齐一键启动、停止和 smoke check 流程

### 阶段2：移动端对话式体验改造

- 前端从偏表单式输入收敛为移动优先的聊天界面
- 高级参数默认折叠，主入口保持一个对话框
- 补充 Playwright 移动端测试

### 阶段3：真实数据接入

- 从 CSV/SQL 资料过渡到阿里云 MySQL 数据库
- 核心数据源：
  - `wddm_dim_overview_cockpit_f`：经营概览宽表
  - `vw_pnl_fact`：利润表明细视图
  - `dim_allhotel_slcp`：酒店维度表
- 建立本地 DuckDB 分析缓存，支撑秒级响应

### 阶段4：千问大模型接入

- 通过 OpenAI 兼容接口接入阿里云 DashScope 千问模型
- 形成快慢双模型策略：
  - **快模型(qwen3.5-flash)**：负责语义解析、容错、澄清追问
  - **深度模型(qwen3.6-plus)**：负责经营解释、管理层摘要、风险和建议表达

### 阶段5：真实问题驱动修复

- "本月哪些酒店经营利润未达预算？"识别为经营利润、预算对比、低于预算方向
- "广州丽思卡尔顿酒店3月的收入情况怎么样？"区分酒店和公寓

### 阶段6：可配置化和可观察性增强

- 新增 `app_settings.yaml`，快捷提问、模型配置、回答模板、调优阶段外置
- 新增 `entity_catalog.yaml`，接入酒店、区域、品牌、管理方基础数据
- 新增 Skill Registry 和 Harness 评测框架

---

## 三、架构演进

### 当前架构（5层）

```
移动端用户 → 前端交互层(React+TypeScript+Vite)
                    ↓
           后端编排层(ai-query-service:8100)
                    ↓
    ┌───────────────┼───────────────┐
    ↓               ↓               ↓
语义与规则层   数据执行层    分析表达层
(semantic/     (db-executor)   (explanation/
 metric/        ↓               audit)
 sql-guardrail)     ↓
 (8101-8103)   DuckDB本地仓 ← MySQL权威源
                    ↓
              模型能力(Qwen Fast/Deep)
```

### 8个后端服务

| 服务 | 端口 | 核心职责 |
|------|------|----------|
| `ai-query-service` | 8100 | 对外统一入口，编排整条查询链路 |
| `semantic-service` | 8101 | 自然语言解析，输出 parsed_intent、query_plan、resolved_entities |
| `metric-service` | 8102 | 指标字典和字段映射 |
| `sql-guardrail-service` | 8103 | SQL 合规校验与口径约束 |
| `explanation-service` | 8104 | 经营观察、分析明细、风险提示、摘要生成 |
| `auth-service` | 8105 | 角色、权限、数据范围返回 |
| `db-executor-service` | 8106 | DuckDB / MySQL 查询执行 |
| `audit-service` | 8107 | 审计与链路元数据记录 |

### 架构演进阶段

#### 第一阶段：微服务 + 规则 + 模型补位

- 8个独立 FastAPI 服务拆分为清晰职责
- 语义层能识别：时间、酒店、区域、指标、对比口径
- Skill 从"理解问题的主入口"降级为"已知分析动作的执行模板"

#### 第二阶段：Planner + Semantic Graph

**语义层从"参数提取器"升级为"分析规划器"**

- `semantic-service` 新增 `resolved_entities` 和 `query_plan`
- 已支持把"富力所有酒店"解析为 `hotel_group`（公司全部酒店）
- `query_plan` 输出结构：
  - `query_object_type` / `query_object_label`
  - `query_grain`：单店 / 组合 / 统计类
  - `analysis_mode`：总览、归因、对比、报告、追问
  - `themes`：收入质量、客房效率、利润质量、成本效率、内部对标
  - `execution_order`：执行顺序规划

**运行时 scope_graph 升级**

- 基于最新账期经营宽表和酒店维表联合生成酒店节点
- 支持把"区域/管理公司/品牌/建设来源/档次/城市等级"组合解析为 `scope_collection`
- `scope_collection` 返回 `scope_type / label / member_hotels / member_count / applied_filters`
- 统计类问题（如"目前在运营的酒店有多少家"）使用独立 `analysis_mode=scope_stat_snapshot`

#### 第三阶段：Analysis Agent + Narrative Agent

**经营分析层独立**

- 固定按经营框架组织分析：收入质量、客房效率、利润质量、成本效率、横向对标
- 经营解释不直接下"好/坏/健康/承压"等定性结论
- 使用管理层熟悉表达：量价关系、收入结构、利润转化、成本占收比、拖累/拉动

**报告式章节支持**

- 组合类问题采用报告式章节：
  - 分析范围 → 组合经营摘要 → 经营总览 → 管理公司/区域汇总 → 收入质量 → 客房效率 → 利润质量 → 成本效率 → 重点酒店与梯队 → 横向对标
- "富力所有酒店"不再退回成单点快照，而是正确识别为 `company_management_report`

#### 第四阶段：Learning Agent + External Benchmark Provider

**学习闭环底座**

- `GET /api/v1/system/learning/summary?days=7`：从 `learning_inbox` 聚合学习样本
- `GET /api/v1/system/learning/harness-candidates`：从失败样本中抽取候选回归 case
- 学习样本写入时补充元数据：`metric_code / compare_mode / query_object_type / query_grain / analysis_mode`

**外部对标 Provider 状态区分**

- `manual_review` / `uploaded_dataset` / `industry_api` / `web_research`
- 每个 Provider 返回独立的 `status / dimensions / disclaimers`
- 前端可以明确判断"外部对标是否真正就绪"

---

## 四、关键设计原则

### 1. 规则优先，模型补位

```
确定性识别 → 规则 / 维度图谱
模糊推理   → 快模型结构化判断
专业表达   → 深度模型在数据约束下生成
```

### 2. 快慢双速路径

| 路径 | 目标 | 场景 |
|------|------|------|
| Fast Path | 0.3s-1.5s | 上下文继承、时间识别、语义图谱命中、本地仓查询 |
| Deep Path | 1.5s-6s | 组合汇总、对标回退、异常识别、P&L下钻 |
| Async Path | 非阻塞 | 外部联网对标、学习沉淀、报告导出 |

### 3. Skill / Harness 自学习

```
Learning Inbox → 候选改进 → Harness评测 → 人工审核 → Skill Registry发布
```

- 大模型不直接自由生成 SQL
- Skill 定义业务能力和参数边界
- 自学习只生成候选改进，不自动改线上规则

---

## 五、当前能力

### 已具备

- 移动端对话式问答
- 单店、区域、品牌、管理公司、月份、指标识别
- 预算对比、同比查询
- 经营利润、总收入、RevPAR 指标
- 真实 MySQL + 本地 DuckDB 双层数据链路
- 管理层摘要、风险和建议
- 连续追问
- 可配置快捷提问、模型配置、回答模板
- 基础审计日志
- 49个单元测试通过
- 14项移动端 Playwright E2E 测试通过

### 仍需加强

- 权限和审计体系（角色范围仍较简化）
- 指标字典扩展（更多经营指标）
- 外部行业对标 Provider（真实联网抓取）
- 经营解释业务模板（避免复杂问题表达泛化）
- 生产化部署（统一网关、鉴权、HTTPS、密钥管理）

---

## 六、后续规划

### P0：把管理层问题先答对

**目标**：解决"问得像汇报，答得像问答"的错位问题

- 新增 `company_management_report` 和 `group_by_dimension_report` 问题类型
- query plan 增加 `group_by_dimensions`
- 输出支持"管理公司 x 区域"汇总
- 默认首屏从"酒店异常"切到"组合对比"

### P1：建立报告模板和指标包体系

- 建立 `report_templates.yaml`：
  - `company_overview_report`
  - `manage_corp_area_report`
  - `brand_comparison_report`
  - `regional_overview_report`
  - `single_hotel_report`
  - `ranking_and_ladder_report`
- 建立 `metric_bundles.yaml`：
  - `operation_bundle`：总收入、GOP、NOP率、含储备金利润
  - `room_efficiency_bundle`：ADR、OCC、RevPAR
  - `income_structure_bundle`：客房/餐饮/宴会/其他收入
  - `cost_efficiency_bundle`：人工、食材、能耗、固定成本
- 扩展维度图谱：管理公司、资产包、品牌层级、科目层级

### P2：引入 Planner + Semantic Graph 主导的新链路

- Planner 统一做问题分类和执行计划
- Semantic Graph 统一做实体和关系解析
- Skill 从主链路退到辅助能力
- 报告类问题按模板驱动而不是按触发词驱动

### P3：多 Agent 与学习闭环

- **Analysis Agent**：负责经营拆解
- **Narrative Agent**：负责管理层表达
- **Learning Agent**：负责失败样本和追问沉淀
- **External Benchmark Provider**：作为异步增强层接入

---

## 七、目标形态

```
当前阶段                    下一阶段                  增强阶段                  成熟阶段
微服务+规则+模型补位   →   Planner+Semantic Graph →  Analysis+Narrative Agent →  Learning+External Provider
                                                                                      ↓
                                    高效率多 Agent 酒店经营分析助手
```

**一句话总结**：

> 当前系统已经完成"移动端对话入口 + 真实数据查询 + 初步语义理解 + 管理层结果呈现"的基础架构。
> 下一步要做的是把它升级为"一个会先理解业务问题、再规划查询路径、再基于真实数据做经营拆解，并能持续学习用户表达的酒店经营分析助手"。

---

## 八、文档索引

| 文档 | 说明 |
|------|------|
| `PROJECT_REVIEW_AND_ARCHITECTURE.md` | 项目整体复盘与技术框架 |
| `ARCHITECTURE_OVERVIEW.md` | 实际代码架构、服务调用关系、数据流 |
| `../02_ARCHITECTURE_EVOLUTION/HIGH_EFFICIENCY_MULTI_AGENT_ARCHITECTURE.md` | 多 Agent 演进方案 |
| `../02_ARCHITECTURE_EVOLUTION/PPT_DRIVEN_FRAMEWORK_ENHANCEMENT_PLAN.md` | 业务汇报材料驱动的框架升级 |
| `../05_PRODUCT_EXPERIENCE/FRONTEND_EXECUTIVE_EXPERIENCE_LOG.md` | 前端管理层体验整改记录 |
| `../03_SEMANTIC_AND_MODEL/SKILL_HARNESS_EVOLUTION_PLAN.md` | Skill/Harness 自学习架构 |
| `../03_SEMANTIC_AND_MODEL/SKILL_HARNESS_HERMES_REVIEW.md` | Skill/Harness/Hermes 评估 |
| `../03_SEMANTIC_AND_MODEL/SEMANTIC_DIMENSION_LAYER.md` | 业务维度识别层说明 |
| `../03_SEMANTIC_AND_MODEL/LLM_REASONING_BOUNDARY.md` | 规则、维度图谱与大模型推理边界 |
| `../04_DATA_AND_BENCHMARK/LOCAL_WAREHOUSE.md` | 本地 DuckDB 分析缓存 |
| `../04_DATA_AND_BENCHMARK/EXTERNAL_BENCHMARK_PROVIDER.md` | 外部行业对标 Provider |
| `../06_EXECUTION_LOGS/PHASE3_EXECUTION_LOG.md` | 第三阶段执行记录 |
| `../05_PRODUCT_EXPERIENCE/CHATGPT_EXPERIENCE_ALIGNMENT_PLAN.md` | ChatGPT 交互体验对齐方案 |
| `../07_OPERATIONS_DELIVERY/LOCAL_STARTUP.md` | 本地启动说明 |
| `../07_OPERATIONS_DELIVERY/DEPLOYMENT_NOTES.md` | 部署注意事项 |
| `../07_OPERATIONS_DELIVERY/DELIVERY_CHECKLIST.md` | 交付核对清单 |
