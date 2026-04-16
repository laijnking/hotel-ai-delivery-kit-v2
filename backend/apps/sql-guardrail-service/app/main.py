from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    yaml = None

app = FastAPI(title="sql-guardrail-service")
CONFIG = Path(__file__).resolve().parents[3] / "configs" / "sql_guardrails.yaml"


class Req(BaseModel):
    sql: str
    metric_code: str
    allowed_hotels: list[str] = Field(default_factory=list)
    allowed_areas: list[str] = Field(default_factory=list)
    hotel_column: str = "hotel_name"
    area_column: str = "area_name"
    require_time_filter: bool = True


@lru_cache(maxsize=1)
def _load_config() -> dict[str, Any]:
    with open(CONFIG, "r", encoding="utf-8") as f:
        if yaml is not None:
            return yaml.safe_load(f) or {}

        config: dict[str, Any] = {}
        current_key: str | None = None
        for raw_line in f:
            line = raw_line.rstrip("\n").rstrip("\r")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.endswith(":") and not stripped.startswith("- "):
                current_key = stripped[:-1]
                config[current_key] = []
                continue
            if stripped.startswith("- ") and current_key:
                config.setdefault(current_key, []).append(stripped[2:].strip().strip('"').strip("'"))
        return config


def _normalize_list(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        item = str(value).strip()
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _build_scope_predicate(payload: Req) -> str | None:
    clauses: list[str] = []
    allowed_hotels = _normalize_list(payload.allowed_hotels)
    allowed_areas = _normalize_list(payload.allowed_areas)

    if allowed_areas and allowed_areas != ["ALL"]:
        clauses.append(
            f"{payload.area_column} IN ({', '.join(_quote(item) for item in allowed_areas)})"
        )

    if allowed_hotels and allowed_hotels != ["ALL"]:
        clauses.append(
            f"{payload.hotel_column} IN ({', '.join(_quote(item) for item in allowed_hotels)})"
        )

    if not clauses:
        return None

    if len(clauses) == 1:
        return clauses[0]
    return "(" + " AND ".join(clauses) + ")"


def _inject_scope(sql: str, predicate: str | None) -> str:
    if not predicate:
        return sql

    statement = sql.strip()
    upper = statement.upper()
    boundary_pattern = re.compile(r"\b(GROUP\s+BY|ORDER\s+BY|LIMIT|HAVING|UNION|EXCEPT|INTERSECT)\b", re.IGNORECASE)
    match = boundary_pattern.search(statement)

    if re.search(r"\bWHERE\b", upper):
        if match:
            return statement[: match.start()].rstrip() + f" AND {predicate} " + statement[match.start() :].lstrip()
        return statement + f" AND {predicate}"

    if match:
        return statement[: match.start()].rstrip() + f" WHERE {predicate} " + statement[match.start() :].lstrip()

    return statement + f" WHERE {predicate}"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/sql/validate")
def validate(payload: Req):
    cfg = _load_config()
    reasons: list[str] = []
    warnings: list[str] = []
    sql = payload.sql.strip()
    sql_upper = sql.upper()
    forbidden_patterns = cfg.get("forbidden_patterns", [])
    non_additive_metrics = {str(item).upper() for item in cfg.get("non_additive_metrics", [])}
    normalized_metric = payload.metric_code.strip().upper()

    if not sql:
        reasons.append("SQL 不能为空")
    if not normalized_metric:
        reasons.append("metric_code 不能为空")
    if not re.match(r"^(SELECT|WITH)\b", sql_upper):
        reasons.append("仅允许查询语句（SELECT/WITH）")
    if ";" in sql.rstrip(";"):
        reasons.append("不允许多语句 SQL")
    if "--" in sql or "/*" in sql or "*/" in sql:
        reasons.append("不允许显式注释或注入片段")

    for pattern in forbidden_patterns:
        if str(pattern).upper() in sql_upper:
            reasons.append(f"命中禁止模式: {pattern}")

    if payload.require_time_filter and "CALMONTH" not in sql_upper and "DATE" not in sql_upper:
        reasons.append("缺少时间过滤条件")

    predicate = _build_scope_predicate(payload)

    if normalized_metric in non_additive_metrics and len(_normalize_list(payload.allowed_hotels)) > 1:
        warnings.append("非加总指标跨酒店使用时，请确认查询未做错误汇总")

    if not predicate and payload.allowed_hotels != ["ALL"] and payload.allowed_areas != ["ALL"]:
        reasons.append("缺少可注入的权限范围")

    rewritten = _inject_scope(sql, predicate)

    return {
        "safe": len(reasons) == 0,
        "reasons": reasons,
        "warnings": warnings,
        "rewritten_sql": rewritten,
        "applied_scope": {
            "predicate": predicate,
            "allowed_areas": _normalize_list(payload.allowed_areas),
            "allowed_hotels": _normalize_list(payload.allowed_hotels),
            "hotel_column": payload.hotel_column,
            "area_column": payload.area_column,
        },
        "metric_code": normalized_metric,
    }
