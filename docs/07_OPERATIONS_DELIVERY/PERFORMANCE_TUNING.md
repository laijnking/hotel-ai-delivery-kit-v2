# 问答性能调优说明

## 1. 当前目标

管理层移动端问答需要先保证“有反馈、快出数、可追问”。普通经营查询不应每次都等待大模型完整思考，否则用户会感觉系统卡住。

当前链路采用：

1. 快模型优先做语义归一化，规则 / Skill / Harness 负责约束和补充校验。
2. 本地 DuckDB 分析缓存优先查询。
3. 本地结构化酒店经营解释模板优先生成回答。
4. 深模型在报告、归因或需要增强表达时介入。

## 2. 语义解析策略

环境变量：

```powershell
$env:QWEN_PARSE_POLICY="always"
$env:QWEN_PARSE_CONFIDENCE_THRESHOLD="0.82"
```

策略说明：

- `always`：无人值守模型默认策略。每次语义解析都调用快模型，优先适配前端自由提问。
- `auto`：兼容旧链路。规则解析高于阈值时跳过快模型；低置信或需要澄清时调用快模型。
- `off`：完全不调用快模型，只用规则、Skill 和实体目录。

## 3. 解释生成策略

环境变量：

```powershell
$env:QWEN_EXPLANATION_POLICY="auto"
```

策略说明：

- `auto`：无人值守模型默认策略。普通问答优先走结构化模板，报告、归因或显式深度解释场景调用深度模型。
- `off`：完全关闭深模型增强，普通问答使用本地结构化模板，响应最快。
- `always`：每次解释都调用深度模型，质量可能更自然，但延迟明显增加。

## 4. 前端可观测性

每次问答结果会返回 `performance` 字段，并在“技术诊断信息”中显示：

- `auth_ms`
- `semantic_ms`
- `metric_ms`
- `sql_guardrail_ms`
- `db_executor_ms`
- `explanation_ms`
- `audit_ms`
- `total_ms`

后续如果再次出现 15-20 秒延迟，优先看 `semantic_ms` 和 `explanation_ms` 是否在等待模型。

## 5. 推荐使用方式

普通移动端经营查询：

```powershell
$env:QWEN_PARSE_POLICY="always"
$env:QWEN_EXPLANATION_POLICY="auto"
```

深度经营报告或复盘材料：

```powershell
$env:QWEN_PARSE_POLICY="always"
$env:QWEN_EXPLANATION_POLICY="auto"
```

模型调优验证阶段：

```powershell
$env:QWEN_PARSE_POLICY="always"
$env:QWEN_EXPLANATION_POLICY="always"
```

验证阶段适合观察模型能力，但不建议作为移动端默认体验。
