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
