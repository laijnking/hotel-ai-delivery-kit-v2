# 第 26 轮执行记录：Semantic Graph 实体别名与复杂 Planner Eval

更新时间：2026-04-19

## 1. 本轮目标

本轮承接第 25 轮建议，推进 Semantic Graph 深化中的实体别名和复杂语义回归能力，重点覆盖管理层高频问题：

- 公司全部酒店经营情况，按管理公司和区域维度输出。
- 管理公司短名问题，例如“万达所有酒店”，稳定归一到标准管理方“万达品牌”。

## 2. 本轮完成内容

### 2.1 统一实体别名配置

在 `backend/configs/entity_catalog.yaml` 中新增 `aliases` 区域：

- `manage_corp.万达品牌 -> 万达`

语义服务新增：

- `load_entity_aliases()`
- `entity_alias_norms()`

实体匹配不再只依赖完整标准名，后续酒店、品牌、管理方等别名可以继续沉淀到同一配置结构中。

### 2.2 管理公司短名解析

补充回归：

- “请分析一下万达所有酒店3月份经营情况，按区域维度输出”

期望结果：

- `requested_manage_corps = ["万达品牌"]`
- `query_object_type = manage_corp_scope`
- `analysis_mode = group_by_dimension_report`
- `group_by_dimensions = ["area"]`
- `metric_bundle_code = group_dimension_overview`

### 2.3 Semantic Eval 支持 Planner 嵌套字段

`backend/evals/run_eval.py` 新增：

- `expected_paths`
- dot path 检查，例如 `query_plan.group_by_dimensions`

同时 eval 中 portfolio 问题会按真实查询路由调用 `build_portfolio_sql()`，使 eval 更贴近主链路。

### 2.4 新增复杂语义 eval case

新增 2 条 case：

- `company_manage_area_grouped_overview`
- `manage_corp_alias_area_grouped_overview`

当前 semantic SQL eval 从 12 条扩展到 14 条。

## 3. 验证结果

- 定向测试：
  - `2 passed`
- Semantic SQL eval：
  - `14/14 passed`

## 4. 本轮价值

- 管理公司别名进入配置化沉淀路径，减少硬编码特例。
- 管理层复杂问题的 Planner 输出开始进入 eval 约束，不再只校验顶层语义字段。
- “公司全集 + 管理公司/区域分组”和“万达短名 + 区域分组”两条高频链路有了回归保护。

## 5. 下一轮建议

继续推进 R4 / R5：

- 扩展 `entity_catalog.yaml` 中品牌、子品牌、酒店简称别名。
- 将科目层级 PnL graph 从规则识别进一步配置化。
- 前端管理层视图与调试视图分层，降低默认页面技术感。
