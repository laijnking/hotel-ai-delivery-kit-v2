# 本地分析缓存层

本项目现在支持把阿里云 MySQL 的经营数据同步到代码服务器本地，形成只读 DuckDB 分析缓存。线上问答优先查询本地缓存，缓存不可用或 SQL 不兼容时再回退到 MySQL，最后才使用 CSV / fallback。

## 1. 目标

本地分析缓存层用于解决远程数据库查询延迟和分析型查询反复打源库的问题。它不替代阿里云 MySQL，MySQL 仍是权威数据源；本地 DuckDB 只是可重建、可校验、可删除的分析副本。

当前同步对象：

- `wddm_dim_overview_cockpit_f`：经营驾驶舱宽表。
- `vw_pnl_fact`：P&L 科目明细视图。
- `dim_allhotel_slcp`：酒店维度表。

## 2. 本地文件

默认输出目录：

```text
backend/runtime/warehouse/
```

核心文件：

- `hotel_warehouse.duckdb`：本地 DuckDB 分析库。
- `sync_manifest.json`：同步清单，记录来源、同步时间、最新账期、表行数和账期范围。
- `parquet/<table>/data.parquet`：每张表的 Parquet 副本，方便后续离线分析和迁移。
- `staging/*.csv`：同步过程的中间文件，可重建。

这些文件是运行时数据，不应提交到代码仓库。

## 3. 同步命令

从阿里云 MySQL 同步：

```powershell
.\.venv\Scripts\python.exe scripts\sync_warehouse.py --source database --reset
```

从本地 CSV 构建开发缓存：

```powershell
.\.venv\Scripts\python.exe scripts\sync_warehouse.py --source csv --reset
```

同步脚本会读取 Windows User 环境变量中的数据库连接信息，不会把密码写入清单或日志。

## 4. 当前同步结果

本轮已从数据库同步成功：

- `wddm_dim_overview_cockpit_f`：8,827 行。
- `vw_pnl_fact`：169,415 行。
- `dim_allhotel_slcp`：94 行。
- 最新账期：`202603`。

服务健康检查会返回：

```json
{
  "warehouse_enabled": true,
  "warehouse_available": true,
  "warehouse_manifest": {
    "source": "database",
    "latest_month": "202603"
  }
}
```

## 5. 查询优先级

`db-executor-service` 当前查询顺序：

1. `local_warehouse`：优先使用 `hotel_warehouse.duckdb`。
2. `database`：本地仓库不可用或 SQL 不兼容时回源 MySQL。
3. `real_csv`：数据库不可用时使用真实 CSV 回退。
4. `fallback`：最后使用极简示例数据，主要用于服务不断路。

`ai-query-service` 会把 `data_source` 透传到结果和审计 metadata 中，便于追踪本次回答使用了哪层数据。

## 6. 开关

关闭本地仓库优先查询：

```powershell
$env:USE_LOCAL_WAREHOUSE="0"
```

指定仓库路径：

```powershell
$env:WAREHOUSE_DUCKDB_PATH="C:\path\hotel_warehouse.duckdb"
```

指定仓库目录：

```powershell
$env:WAREHOUSE_DIR="C:\path\warehouse"
```

## 7. 后续优化

下一步建议：

- 增加定时同步任务，例如每天早上同步一次。
- 增加同步校验：行数、账期、核心指标汇总与源库对比。
- 新增预计算 mart，如 `mart_hotel_operation_monthly`、`mart_area_operation_monthly`、`mart_brand_operation_monthly`。
- 让 `latest_period_resolver` 直接读取 `sync_manifest.json` 的 `latest_month`。
- 在 Harness 中增加数据源断言，防止误用 fallback。
