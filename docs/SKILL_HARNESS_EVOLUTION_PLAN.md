# Skill / Harness 自学习架构演进方案

本文档记录下一阶段架构整改方向：从“配置驱动的经营问答系统”升级为“Skill 驱动、Harness 评测、反馈学习、受控发布”的经营 AI 助手。

## 1. 背景判断

当前系统已经具备移动端对话、真实 MySQL 查询、千问快慢模型、SQL 护栏、经营解释和可配置快捷提问等能力。但随着问题数量和指标数量增加，现有方案会遇到三个明显瓶颈：

1. 配置会持续膨胀。

   当前配置分散在 `semantic_mapping.yaml`、`metric_dictionary.yaml`、`app_settings.yaml`，语义词、指标别名、回答模板、快捷提问存在重复维护风险。

2. 业务知识仍有一部分写死在代码里。

   例如酒店名正则、区域正则、月份解析、默认预算对比、方向词等在服务代码中。它们本质是可迭代的业务知识，不应长期固化在代码里。

3. 系统还没有真正“自学习”。

   现在主要靠人工发现问题后改代码或改配置。系统还不能自动沉淀失败样本、提出候选规则、跑评测、进入待审核发布。

因此下一阶段不建议继续简单增加 YAML 配置，而应把配置重新组织成可测试、可版本化、可学习的 Skill。

## 2. 核心结论

建议采用如下演进方向：

```text
对话入口
  -> Skill Router
  -> Business Skill
  -> 数据工具 / SQL Strategy
  -> Explanation Template
  -> Feedback Learning
  -> Evaluation Harness
  -> Human Approval
  -> Skill Registry
```

关键原则：

- 大模型不直接自由生成 SQL。
- Skill 定义业务能力和参数边界。
- Harness 负责评测，不负责线上问答。
- 自学习只生成候选改进，不自动改线上规则。
- 每个高频业务问题都应沉淀为可测试的 Skill 样本。
- 经营解释不直接下“好/坏/健康/承压”等定性结论，而是围绕收入质量、客房效率、利润质量、成本效率、横向对标做客观拆解。

## 3. 当前架构评价

### 3.1 合理部分

当前架构中值得保留的部分：

- 前端移动端对话入口方向正确。
- 后端按语义、指标、SQL、数据、解释分层，职责清楚。
- 快慢模型分工合理：快模型解析，深度模型解释。
- SQL 由规则生成并经过护栏校验，比让模型直接写 SQL 更安全。
- `parse_debug` 和 SQL 计划已经提供初步可观察性。
- `app_settings.yaml` 已经把快捷提问、模型配置、回答模板、调优阶段外置。

### 3.2 不合理或待改造部分

当前需要整改的部分：

- 同义词、指标别名、快捷提问、模板分散配置。
- 部分业务规则在 Python 代码中，不利于业务人员调整。
- 模型 prompt 和规则逻辑耦合在服务代码里。
- 用户反馈没有结构化沉淀。
- 评测样本不足，缺少“改动是否退化”的自动判断。
- 8 个服务边界清晰，但本地联调成本偏高；生产部署时可以保留逻辑边界，不一定保留 8 个独立进程。

## 4. Skill 模式设计

### 4.1 Skill 是什么

在本项目中，Skill 不是简单 prompt，而是一个“业务能力包”。每个 Skill 应包含：

- 适用场景。
- 触发词和意图描述。
- 参数槽位。
- 默认参数。
- 可用指标。
- SQL 策略。
- 回答模板。
- 示例问题。
- 验收样本。
- 版本号和启用状态。

### 4.2 Skill 示例

```yaml
id: hotel_income_overview
name: 单店收入情况
version: 1
enabled: true
description: 回答单个酒店某月份收入表现，默认与预算对比。

triggers:
  - 收入情况
  - 收入怎么样
  - 营收表现
  - 总收入如何

slots:
  hotel:
    type: entity
    entity: hotel
    required: true
  month:
    type: period
    required: true
  metric:
    type: metric
    default: TOTAL_INCOME
  compare_mode:
    type: enum
    values: [budget, yoy, actual]
    default: budget

sql_strategy: overview_metric_compare
answer_template: metric_query_mobile

examples:
  - question: 广州丽思卡尔顿酒店3月的收入情况怎么样？
    expected:
      metric_code: TOTAL_INCOME
      compare_mode: budget
      time_scope: "202603"
      requested_hotels:
        - 广州丽思卡尔顿酒店
```

### 4.3 推荐的 Skill 类型

第一批建议建立以下 Skill：

| Skill ID | 名称 | 说明 |
| --- | --- | --- |
| `hotel_income_overview` | 单店收入情况 | 单店某月收入、预算、同比 |
| `hotel_profit_overview` | 单店利润情况 | 单店经营利润和预算差异 |
| `area_profit_gap_rank` | 区域利润缺口排名 | 找出未达预算酒店 |
| `area_income_yoy` | 区域收入同比 | 区域收入同比变化 |
| `hotel_profit_driver` | 单店利润归因 | 下钻 `vw_pnl_fact` 明细 |
| `management_summary` | 管理层经营摘要 | 生成移动端摘要 |
| `follow_up_rewrite` | 连续追问改写 | 处理“继续展开原因”“只看华南区” |

## 5. Skill Registry 设计

建议新增目录：

```text
backend/skills/
  registry.yaml
  hotel_income_overview.yaml
  hotel_profit_overview.yaml
  area_profit_gap_rank.yaml
  management_summary.yaml
```

`registry.yaml` 管理启用状态和版本：

```yaml
skills:
  - id: hotel_income_overview
    file: hotel_income_overview.yaml
    enabled: true
    version: 1
  - id: hotel_profit_overview
    file: hotel_profit_overview.yaml
    enabled: true
    version: 1
```

后续 `semantic-service` 不再只读 `semantic_mapping.yaml`，而是：

1. 加载所有启用 Skill。
2. 从 Skill 中构建触发词、槽位、默认值和模型提示。
3. 让快模型在 Skill 候选集中选择最合适的 Skill。
4. 输出结构化参数。

## 6. 基础数据适配计划

用户已提供基础数据目录：

```text
C:\Project\HotelAgent\basedata
```

当前文件包括：

| 文件 | 内容 | 适配用途 |
| --- | --- | --- |
| `酒店数据.txt` | 酒店名称列表 | hotel 实体词库，解决酒店全称、简称、酒店/公寓区分 |
| `区域数据.txt` | 区域名称列表 | area 实体词库，补齐海南区等区域 |
| `品牌数据.txt` | 品牌名称列表 | brand 实体词库，支持“看希尔顿品牌” |
| `管理方数据.txt` | 管理方列表 | manage_corp 实体词库，支持“国际品牌管理方” |
| `城市数据.txt` | 当前为空 | 后续补齐 city 实体词库 |

### 6.1 建议新增 Entity Catalog

建议新增：

```text
backend/configs/entity_catalog.yaml
```

结构示例：

```yaml
entities:
  hotel:
    source: C:/Project/HotelAgent/basedata/酒店数据.txt
    normalize:
      trim: true
      remove_prefix:
        - hotelNames酒店名称包括：
    alias_rules:
      - type: remove_suffix
        suffix: 酒店
        keep_precise_suffix: true
      - type: trim_space

  area:
    source: C:/Project/HotelAgent/basedata/区域数据.txt
    normalize:
      trim: true
      remove_prefix:
        - areas区域名称包括：

  brand:
    source: C:/Project/HotelAgent/basedata/品牌数据.txt
    normalize:
      trim: true
      remove_prefix:
        - hotelBrands品牌名称包括：

  manage_corp:
    source: C:/Project/HotelAgent/basedata/管理方数据.txt
    normalize:
      trim: true
      remove_prefix:
        - manageCorps管理方名称包括：
```

### 6.2 为什么基础数据应进入实体层

基础数据不建议直接硬编码到正则里。更好的方式是：

- 启动时加载基础数据。
- 生成实体词典和别名。
- 语义解析先走实体匹配。
- 快模型只在实体匹配不确定时辅助判断。
- SQL 生成使用实体标准名。

这样能解决：

- 酒店名称越来越多的问题。
- “广州丽思卡尔顿酒店”和“广州丽思卡尔顿公寓”的区分问题。
- 新区域、新品牌、新管理方不用改代码。
- 后续支持品牌/管理方/城市维度查询。

## 7. Harness 评测框架

Harness 是评测框架，不是线上业务服务。

### 7.1 Harness 目标

每次改 Skill、Prompt、实体词库、SQL 策略前后，都自动回答：

- 语义解析有没有变差？
- SQL 有没有变错？
- 结果是否仍是数据真实结果？
- 回答是否符合管理层模板？

### 7.2 建议目录

```text
backend/evals/
  cases/
    semantic_cases.yaml
    sql_cases.yaml
    answer_cases.yaml
  run_eval.py
  reports/
```

### 7.3 Case 示例

```yaml
- id: income_guangzhou_ritz_mar_2026
  question: 广州丽思卡尔顿酒店3月的收入情况怎么样？
  expected:
    skill_id: hotel_income_overview
    metric_code: TOTAL_INCOME
    compare_mode: budget
    time_scope: "202603"
    requested_hotels:
      - 广州丽思卡尔顿酒店
  sql_assertions:
    contains:
      - wddm_dim_overview_cockpit_f
      - TOTAL_INCOME_MTD_A
      - TOTAL_INCOME_MTD_B
      - "202603"
      - 广州丽思卡尔顿酒店
  answer_assertions:
    must_mention:
      - 实际
      - 预算
      - 差额
      - 建议
```

### 7.4 Harness 输出

每次运行生成报告：

```text
eval_report_2026-04-15.md
```

内容包括：

- 总通过率。
- 失败 case。
- 失败阶段：语义 / SQL / 数据 / 回答。
- 变更前后差异。
- 是否允许发布。

## 8. Feedback Learning 反馈学习

### 8.1 不建议全自动学习

经营分析系统不建议让模型自动改线上规则。原因：

- 业务口径有风险。
- 数据口径错会影响管理判断。
- 用户自然语言反馈可能不精确。
- 一次错误学习可能污染多个 Skill。

建议采用“候选学习 + 人工确认 + Harness 评测 + 发布”的模式。

### 8.2 Learning Inbox

建议新增：

```text
backend/runtime/learning_inbox/
```

每次出现以下情况时记录样本：

- `needs_clarification=true`
- 查询结果为空。
- 用户点击“结果不对”。
- 用户连续追问纠正系统。
- `parse_confidence` 低于阈值。
- SQL 被 guardrail 拦截。

样本结构：

```json
{
  "question": "广州丽思卡尔顿酒店3月的收入情况怎么样？",
  "parsed_intent": {},
  "sql": "",
  "row_count": 0,
  "user_feedback": "不应该查公寓",
  "stage": "semantic",
  "created_at": "2026-04-15T10:00:00"
}
```

### 8.3 候选改进

后台任务可定期把 Learning Inbox 汇总成候选改进：

- 新增实体别名。
- 新增 Skill 示例。
- 调整默认 compare_mode。
- 新增回答模板要求。
- 新增 eval case。

候选改进不能直接上线，必须进入待审核。

## 9. Hermes / Harness / Skill 的参考方式

这里不建议照搬某个框架，而是吸收三个思想：

### 9.1 Hermes 思想

可借鉴“任务编排和消息流”的思想，把一次问答拆成可观察步骤：

- Plan
- Route
- Parse
- Validate
- Query
- Explain
- Learn

每一步都有输入、输出、trace 和失败原因。

### 9.2 Harness 思想

可借鉴“自动化评测和发布门禁”的思想：

- 每次改动必须跑 eval。
- 不只测代码是否报错，还测业务结果是否退化。
- 评测通过后才允许发布。

### 9.3 Skill 思想

可借鉴“能力模块化”的思想：

- 一个 Skill 包含触发、参数、工具、模板、测试。
- Skill 可启用/禁用/版本化。
- 新业务问题优先沉淀为 Skill，而不是继续堆全局规则。

## 10. 推荐实施路线

### 阶段一：基础数据实体化

目标：

- 读取 `basedata` 文件。
- 生成 `entity_catalog.yaml`。
- semantic-service 使用实体词库替代硬编码区域和酒店正则。

当前进展：

- 已新增 `backend/configs/entity_catalog.yaml`。
- 已接入 `酒店数据.txt`、`区域数据.txt`、`品牌数据.txt`、`管理方数据.txt`、`城市数据.txt`。
- `semantic-service` 已优先使用实体词库识别酒店和区域，并保留旧正则作为兜底。
- 已补充回归测试，覆盖 `海南区` 识别和“广州丽思卡尔顿酒店/公寓”区分。

验收：

- 能识别所有酒店。
- 能识别所有区域，包括海南区。
- “酒店/公寓”不混淆。

### 阶段二：Skill Registry

目标：

- 新建 `backend/skills`。
- 抽出 5-7 个高频 Skill。
- semantic-service 按 Skill 输出结构化参数。

当前进展：

- 已新增 `backend/skills/registry.yaml`。
- 已新增 `hotel_income_overview.yaml`，覆盖“收入情况、营收表现、总收入怎么样”等问法。
- 已新增 `hotel_profit_overview.yaml`，覆盖“经营情况、利润情况、经营利润表现”等问法。
- `semantic-service` 已加载启用的 Skill，并把命中的 `skill_id`、`skill_version`、`matched_skill_trigger` 写入解析结果。
- 已补充回归测试，覆盖“广州柏悦3月营收表现”和“江门嘉华3月利润情况”。

验收：

- 原有高频问题全部通过。
- 新增问题只需新增 Skill 示例，不需要改代码。

### 阶段三：Harness

目标：

- 建立 30-50 个 eval case。
- 覆盖语义、SQL、数据、回答。
- 每次变更自动生成评测报告。

当前进展：

- 已新增 `backend/evals/cases/semantic_sql_cases.yaml`。
- 已新增 `backend/evals/run_eval.py`。
- 第一批沉淀 7 个真实问题 case，覆盖广州丽思卡尔顿酒店、公寓、江门嘉华、海南区、广州柏悦、未达预算方向等场景。
- 当前 Harness 覆盖语义解析和 SQL 关键断言，先离线运行，不依赖真实大模型和线上服务。
- 已将 Harness 接入后端单测，避免后续 Skill、实体词库、SQL 策略改动造成业务退化。

验收：

- 能定位失败阶段。
- 能阻止明显退化上线。

### 阶段四：Learning Inbox

目标：

- 记录失败样本和用户反馈。
- 定期生成候选改进。
- 候选进入待审核队列。

当前进展：

- 已在 `ai-query-service` 中新增 Learning Inbox 写入机制。
- 当前会记录 `clarification_required`、`low_confidence_parse`、`empty_result`、`upstream_fallback_or_warning` 四类样本。
- 样本写入 `backend/runtime/learning_inbox/learning-YYYY-MM-DD.jsonl`。
- 已新增 `backend/evals/summarize_learning_inbox.py`，用于统计样本总量、原因分布、阶段分布和高频问题。
- 已补充单测，验证学习原因判断和 JSONL 写入格式。

验收：

- 高频失败问题能自动归类。
- 能自动建议新增同义词、Skill 示例或 eval case。

### 阶段五：配置管理后台

目标：

- 前端提供系统设置页面。
- 管理快捷提问、Skill、模型、模板、评测结果。

验收：

- 业务人员可以查看但不能随意破坏线上配置。
- 所有变更可追踪、可回滚。

## 11. 短期建议

下一轮可以优先做以下三件事：

1. 建立 `entity_catalog.yaml`，接入 `basedata` 的酒店、区域、品牌、管理方。
2. 新建 `backend/skills`，先落地 `hotel_income_overview` 和 `hotel_profit_overview` 两个 Skill。
3. 新建 `backend/evals/cases/semantic_cases.yaml`，把最近真实暴露的问题全部变成回归样本。

这样做完后，系统会从“靠配置补丁修问题”转向“靠 Skill 和评测沉淀能力”。
