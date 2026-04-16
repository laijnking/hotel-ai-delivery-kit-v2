import os
import re
import json
import time
from functools import lru_cache
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://127.0.0.1:8105")
SEMANTIC_SERVICE_URL = os.getenv("SEMANTIC_SERVICE_URL", "http://127.0.0.1:8101")
METRIC_SERVICE_URL = os.getenv("METRIC_SERVICE_URL", "http://127.0.0.1:8102")
SQL_GUARDRAIL_SERVICE_URL = os.getenv("SQL_GUARDRAIL_SERVICE_URL", "http://127.0.0.1:8103")
EXPLANATION_SERVICE_URL = os.getenv("EXPLANATION_SERVICE_URL", "http://127.0.0.1:8104")
DB_EXECUTOR_SERVICE_URL = os.getenv("DB_EXECUTOR_SERVICE_URL", "http://127.0.0.1:8106")
AUDIT_SERVICE_URL = os.getenv("AUDIT_SERVICE_URL", "http://127.0.0.1:8107")
SERVICE_TIMEOUT = float(os.getenv("SERVICE_TIMEOUT", "45"))
EXTERNAL_BENCHMARK_PROVIDER = os.getenv("EXTERNAL_BENCHMARK_PROVIDER", "manual_review").strip() or "manual_review"
APP_SETTINGS = Path(__file__).resolve().parents[3] / "configs" / "app_settings.yaml"
LEARNING_INBOX_DIR = Path(os.getenv("LEARNING_INBOX_DIR", Path(__file__).resolve().parents[3] / "runtime" / "learning_inbox"))
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TIME_SCOPE_RE = re.compile(r"^\d{6}$")
_OVERVIEW_SOURCE_TABLES = {"ads_hotel_operation_overview_wide", "wddm_dim_overview_cockpit_f"}
_DETAIL_SOURCE_TABLE = "vw_pnl_fact"
HTTP_CLIENT = httpx.Client(timeout=SERVICE_TIMEOUT, trust_env=False)

app = FastAPI(title="ai-query-service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=r"^https?://.+(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuthInfo(BaseModel):
    user_id: str = "u001"
    role: str = "AREA_MANAGER"


class QueryContext(BaseModel):
    time_scope: str | None = None
    language: str = "zh-CN"
    external_benchmark: bool = False


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=2)
    context: QueryContext = Field(default_factory=QueryContext)
    auth: AuthInfo = Field(default_factory=AuthInfo)


class ReportRequest(BaseModel):
    question: str = Field(..., min_length=2)
    context: QueryContext = Field(default_factory=QueryContext)
    auth: AuthInfo = Field(default_factory=AuthInfo)


@app.get("/health")
def health():
    return {"status": "ok"}


@lru_cache(maxsize=1)
def load_app_settings() -> dict:
    with open(APP_SETTINGS, "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f) or {}
    return settings if isinstance(settings, dict) else {}


@app.get("/api/v1/system/settings")
def system_settings():
    settings = load_app_settings()
    model_config = dict(settings.get("model_config", {})) if isinstance(settings.get("model_config"), dict) else {}
    model_config["runtime"] = {
        "fast_model": os.getenv("QWEN_FAST_MODEL", "").strip() or os.getenv("QWEN_MODEL", "").strip() or None,
        "deep_model": os.getenv("QWEN_DEEP_MODEL", "").strip() or os.getenv("QWEN_MODEL", "").strip() or None,
        "llm_base_url": os.getenv("QWEN_API_BASE_URL", "").strip() or None,
        "timeout_seconds": os.getenv("QWEN_TIMEOUT", "").strip() or None,
        "parse_policy": os.getenv("QWEN_PARSE_POLICY", "auto").strip() or "auto",
        "parse_confidence_threshold": os.getenv("QWEN_PARSE_CONFIDENCE_THRESHOLD", "0.82").strip() or "0.82",
        "explanation_policy": os.getenv("QWEN_EXPLANATION_POLICY", "off").strip() or "off",
    }
    return {
        "quick_questions": settings.get("quick_questions", []),
        "model_config": model_config,
        "answer_templates": settings.get("answer_templates", {}),
        "tuning_stages": settings.get("tuning_stages", []),
    }


def request_json(method: str, url: str, payload: dict | None = None, stage: str = "upstream") -> dict:
    try:
        if payload is None:
            response = HTTP_CLIENT.request(method, url)
        else:
            response = HTTP_CLIENT.request(method, url, json=payload)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("response body is not a JSON object")
        return data
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "stage": stage,
                "message": "upstream service returned an error",
                "status_code": exc.response.status_code,
                "body": exc.response.text[:500],
            },
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "stage": stage,
                "message": "failed to call upstream service",
                "error": str(exc),
            },
        ) from exc


def elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def learning_reason(parsed: dict | None = None, rows: list[dict] | None = None, warnings: list[str] | None = None) -> str | None:
    parsed = parsed or {}
    warnings = warnings or []
    confidence = parsed.get("confidence")
    if parsed.get("needs_clarification"):
        return "clarification_required"
    if isinstance(confidence, (int, float)) and confidence < 0.72:
        return "low_confidence_parse"
    if rows is not None and len(rows) == 0:
        return "empty_result"
    if any("fallback" in item or "failed" in item for item in warnings):
        return "upstream_fallback_or_warning"
    return None


def write_learning_sample(
    *,
    trace_id: str,
    question: str,
    stage: str,
    reason: str,
    parsed: dict | None = None,
    sql_text: str | None = None,
    rewritten_sql: str | None = None,
    row_count: int | None = None,
    warnings: list[str] | None = None,
    extra: dict | None = None,
) -> Path:
    LEARNING_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    target = LEARNING_INBOX_DIR / f"learning-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"
    record = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "trace_id": trace_id,
        "question": question,
        "stage": stage,
        "reason": reason,
        "parsed_intent": parsed or {},
        "sql_text": sql_text,
        "rewritten_sql": rewritten_sql,
        "row_count": row_count,
        "warnings": warnings or [],
        "extra": extra or {},
    }
    with target.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return target


def safe_identifier(value: str, label: str) -> str:
    candidate = value.strip()
    if not _IDENTIFIER_RE.fullmatch(candidate):
        raise HTTPException(status_code=500, detail={"message": f"invalid {label}", "value": value})
    return candidate


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sql_like_literal(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'%{escaped}%'"


def hotel_name_candidates(hotel: str) -> list[str]:
    candidate = hotel.strip()
    candidates = []
    for item in (candidate, re.sub(r"(酒店)$", "", candidate).strip()):
        if item and item not in candidates:
            candidates.append(item)
    return candidates


def hotel_scope_clause(hotel_expression: str, requested_hotels: list[str]) -> str | None:
    candidates: list[str] = []
    precise_like_terms: list[str] = []
    for hotel in requested_hotels:
        hotel_text = str(hotel).strip()
        for candidate in hotel_name_candidates(str(hotel)):
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        if hotel_text.endswith(("酒店", "公寓")) and hotel_text not in precise_like_terms:
            precise_like_terms.append(hotel_text)
    if not candidates:
        return None

    exact_clause = f"{hotel_expression} IN ({', '.join(sql_literal(item) for item in candidates)})"
    like_terms = precise_like_terms or candidates
    like_clauses = [f"{hotel_expression} LIKE {sql_like_literal(item)}" for item in like_terms if len(item) >= 2]
    return "(" + " OR ".join([exact_clause, *like_clauses]) + ")"


def dimension_scope_clause(expression: str, values: list[str]) -> str | None:
    candidates: list[str] = []
    for value in values:
        item = str(value).strip()
        if item and item not in candidates:
            candidates.append(item)
        short_item = re.sub(r"(品牌)$", "", item).strip()
        if short_item and short_item not in candidates:
            candidates.append(short_item)
    if not candidates:
        return None
    exact_clause = f"{expression} IN ({', '.join(sql_literal(item) for item in candidates)})"
    like_clauses = [f"{expression} LIKE {sql_like_literal(item)}" for item in candidates if len(item) >= 2]
    return "(" + " OR ".join([exact_clause, *like_clauses]) + ")"


def build_overview_query_parts(source_table: str) -> dict[str, str]:
    if source_table not in _OVERVIEW_SOURCE_TABLES:
        raise HTTPException(status_code=500, detail={"message": "unsupported source_table", "source_table": source_table})

    if source_table == "wddm_dim_overview_cockpit_f":
        return {
            "from_clause": "wddm_dim_overview_cockpit_f o LEFT JOIN dim_allhotel_slcp s ON s.hotel_name_f = o.hotel_name",
            "hotel_select": "COALESCE(s.hotel_name_s, o.hotel_name)",
            "hotel_filter": "COALESCE(s.hotel_name_s, o.hotel_name)",
            "hotel_search_filter": "CONCAT_WS('|', COALESCE(s.hotel_name_s, ''), COALESCE(s.hotel_name_f, ''), COALESCE(o.hotel_name, ''))",
            "area_filter": "s.area",
            "manage_corp_filter": "CONCAT_WS('|', COALESCE(o.manage_corp, ''), COALESCE(s.brand, ''))",
            "brand_child_filter": "CONCAT_WS('|', COALESCE(o.hotel_brand, ''), COALESCE(s.brand_child, ''))",
            "builder_filter": "s.Builder",
            "brand_level_filter": "s.brand_level",
            "city_level_filter": "s.city_level",
            "brand_select": "s.brand",
            "brand_child_select": "s.brand_child",
            "builder_select": "s.Builder",
            "brand_level_select": "s.brand_level",
            "city_level_select": "s.city_level",
            "rooms_select": "s.rooms",
            "build_area_select": "s.build_area",
            "time_field": "o.CALMONTH",
            "metric_prefix": "o",
        }

    return {
        "from_clause": source_table,
        "hotel_select": "HOTEL_NAME_s",
        "hotel_filter": "HOTEL_NAME_s",
        "hotel_search_filter": "HOTEL_NAME_s",
        "area_filter": "area",
        "manage_corp_filter": "brand",
        "brand_child_filter": "brand_child",
        "builder_filter": "Builder",
        "brand_level_filter": "brand_level",
        "city_level_filter": "city_level",
        "brand_select": "brand",
        "brand_child_select": "brand_child",
        "builder_select": "Builder",
        "brand_level_select": "brand_level",
        "city_level_select": "city_level",
        "rooms_select": "rooms",
        "build_area_select": "build_area",
        "time_field": "CALMONTH",
        "metric_prefix": "",
    }


def overview_context_selects(query_parts: dict[str, str]) -> list[str]:
    prefix = f"{query_parts['metric_prefix']}." if query_parts["metric_prefix"] else ""
    dimension_fields = [
        ("brand", query_parts["brand_select"]),
        ("brand_child", query_parts["brand_child_select"]),
        ("builder", query_parts["builder_select"]),
        ("brand_level", query_parts["brand_level_select"]),
        ("city_level", query_parts["city_level_select"]),
        ("rooms", query_parts["rooms_select"]),
        ("build_area", query_parts["build_area_select"]),
    ]
    metric_fields = [
        ("total_income_actual", "TOTAL_INCOME_MTD_A"),
        ("total_income_budget", "TOTAL_INCOME_MTD_B"),
        ("total_income_last_year", "TOTAL_INCOME_MTD_L"),
        ("room_income_actual", "ROOM_INCOME_MTD_A"),
        ("room_income_budget", "ROOM_INCOME_MTD_B"),
        ("room_income_last_year", "ROOM_INCOME_MTD_L"),
        ("restaurant_income_actual", "RESTAURANT_INCOME_MTD_A"),
        ("restaurant_income_budget", "RESTAURANT_INCOME_MTD_B"),
        ("restaurant_income_last_year", "RESTAURANT_INCOME_MTD_L"),
        ("banquet_income_actual", "BANQUET_INCOME_MTD_A"),
        ("banquet_income_budget", "BANQUET_INCOME_MTD_B"),
        ("banquet_income_last_year", "BANQUET_INCOME_MTD_L"),
        ("other_dept_income_actual", "OTHER_DEPT_INCOME_MTD_A"),
        ("other_rate_income_actual", "OTHER_RATE_INCOME_MTD_A"),
        ("operating_profit_actual", "OPERATING_PROFIT_MTD_A"),
        ("operating_profit_budget", "OPERATING_PROFIT_MTD_B"),
        ("operating_profit_last_year", "OPERATING_PROFIT_MTD_L"),
        ("owner_profit_actual", "OWNER_PROFIT_MTD_A"),
        ("room_profit_actual", "ROOM_PROFIT_MTD_A"),
        ("restaurant_profit_actual", "RESTAURANT_PROFIT_MTD_A"),
        ("rental_rooms_actual", "RENTAL_ROOMS_NUM_MTD_A"),
        ("adr_actual", "AVE_HOUSE_PRICE_MTD_A"),
        ("adr_budget", "AVE_HOUSE_PRICE_MTD_B"),
        ("adr_last_year", "AVE_HOUSE_PRICE_MTD_L"),
        ("occupancy_rate_actual", "OCCUPANCY_RATE_MTD_A"),
        ("occupancy_rate_budget", "OCCUPANCY_RATE_MTD_B"),
        ("occupancy_rate_last_year", "OCCUPANCY_RATE_MTD_L"),
        ("revpar_actual", "INCOME_PER_ROOM_MTD_A"),
        ("revpar_budget", "INCOME_PER_ROOM_MTD_B"),
        ("revpar_last_year", "INCOME_PER_ROOM_MTD_L"),
        ("room_cost_actual", "ROOM_COST_MTD_A"),
        ("restaurant_cost_actual", "RESTAURANT_COST_MTD_A"),
        ("food_cost_actual", "FOOD_COST_MTD_A"),
        ("wine_cost_actual", "WINE_COSE_MTD_A"),
        ("admin_expenses_actual", "ADMINI_EXPENSES_MTD_A"),
        ("energy_expenses_actual", "ENERGY_EXPENSES_MTD_A"),
        ("people_cost_actual", "PEOPLE_COST_MTD_A"),
    ]
    selects = [f"{expression} AS {alias}" for alias, expression in dimension_fields]
    selects.extend(f"{prefix}{field} AS {alias}" for alias, field in metric_fields)
    return selects


def build_sql(
    metric_def: dict,
    parsed: dict,
    allowed_hotels: list[str] | None = None,
    requested_hotels: list[str] | None = None,
    requested_areas: list[str] | None = None,
) -> str:
    source_table = safe_identifier(str(metric_def.get("source_table", "ads_hotel_operation_overview_wide")), "source_table")
    query_parts = build_overview_query_parts(source_table)
    period_fields = metric_def.get("period_fields", {})
    if not isinstance(period_fields, dict) or not period_fields:
        raise HTTPException(status_code=500, detail={"message": "metric definition is missing period_fields"})

    requested_period = str(parsed.get("period_type", "MTD")).strip() or "MTD"
    fields = period_fields.get(requested_period)
    if not isinstance(fields, dict):
        requested_period, fields = next(iter(period_fields.items()))
    actual_field_name = safe_identifier(str(fields.get("actual", "")), "actual field")
    compare_mode = str(parsed.get("compare_mode", "actual")).strip() or "actual"
    if compare_mode == "budget":
        compare_field = fields.get("budget") or fields.get("last_year") or fields.get("actual")
    elif compare_mode == "yoy":
        compare_field = fields.get("last_year") or fields.get("budget") or fields.get("actual")
    else:
        compare_field = fields.get("budget") or fields.get("last_year") or fields.get("actual")
    compare_field_name = safe_identifier(str(compare_field), "compare field")
    actual_field = f"{query_parts['metric_prefix']}.{actual_field_name}" if query_parts["metric_prefix"] else actual_field_name
    compare_field = f"{query_parts['metric_prefix']}.{compare_field_name}" if query_parts["metric_prefix"] else compare_field_name

    time_scope = str(parsed.get("time_scope", "")).strip()
    if not _TIME_SCOPE_RE.fullmatch(time_scope):
        raise HTTPException(status_code=400, detail={"message": "invalid time_scope", "time_scope": time_scope})

    where_clauses = [f"{query_parts['time_field']} = {sql_literal(time_scope)}"]
    area_scope = [str(area).strip() for area in (requested_areas or []) if str(area).strip()]
    if area_scope:
        area_clause = ", ".join(sql_literal(area) for area in area_scope)
        where_clauses.append(f"{query_parts['area_filter']} IN ({area_clause})")

    dimension_filters = [
        ("requested_manage_corps", "manage_corp_filter"),
        ("requested_brand_children", "brand_child_filter"),
        ("requested_builders", "builder_filter"),
        ("requested_brand_levels", "brand_level_filter"),
        ("requested_city_levels", "city_level_filter"),
    ]
    for parsed_key, query_key in dimension_filters:
        clause = dimension_scope_clause(query_parts[query_key], [str(item).strip() for item in parsed.get(parsed_key, []) if str(item).strip()])
        if clause:
            where_clauses.append(clause)

    explicit_hotel_scope = [str(hotel).strip() for hotel in (requested_hotels or []) if str(hotel).strip()]
    if explicit_hotel_scope:
        hotel_clause = hotel_scope_clause(query_parts.get("hotel_search_filter", query_parts["hotel_filter"]), explicit_hotel_scope)
        if hotel_clause:
            where_clauses.append(hotel_clause)

    hotel_scope = [str(hotel).strip() for hotel in (allowed_hotels or []) if str(hotel).strip()]
    if hotel_scope and hotel_scope != ["ALL"]:
        hotel_clause = ", ".join(sql_literal(hotel) for hotel in hotel_scope)
        where_clauses.append(f"{query_parts['hotel_filter']} IN ({hotel_clause})")

    variance_direction = str(parsed.get("variance_direction", "all")).strip() or "all"
    if variance_direction == "below":
        where_clauses.append(f"{actual_field} < {compare_field}")
        order_clause = f"ORDER BY ({actual_field} - {compare_field}) ASC"
    elif variance_direction == "above":
        where_clauses.append(f"{actual_field} > {compare_field}")
        order_clause = f"ORDER BY ({actual_field} - {compare_field}) DESC"
    else:
        order_clause = f"ORDER BY ABS({actual_field} - {compare_field}) DESC"

    context_select_sql = ",\n  ".join(overview_context_selects(query_parts))
    return f'''
SELECT
  {query_parts["hotel_select"]} AS hotel_name,
  {query_parts["area_filter"]} AS area,
  {context_select_sql},
  {actual_field} AS actual_value,
  {compare_field} AS compare_value,
  ({actual_field} - {compare_field}) AS diff_value,
  ({actual_field} - {compare_field}) / NULLIF({compare_field}, 0) AS diff_rate
FROM {query_parts["from_clause"]}
WHERE {" AND ".join(where_clauses)}
{order_clause}
LIMIT 50
'''.strip()


def effective_requested_hotels(parsed: dict) -> list[str]:
    query_plan = parsed.get("query_plan") if isinstance(parsed.get("query_plan"), dict) else {}
    resolved_entities = parsed.get("resolved_entities") if isinstance(parsed.get("resolved_entities"), dict) else {}
    hotel_group = resolved_entities.get("hotel_group") if isinstance(resolved_entities.get("hotel_group"), dict) else {}
    if query_plan.get("query_object_type") == "hotel_group":
        members = [str(item).strip() for item in hotel_group.get("member_hotels", []) if str(item).strip()]
        if members:
            return members
    return [str(item).strip() for item in parsed.get("requested_hotels", []) if str(item).strip()]


def build_portfolio_sql(
    metric_def: dict,
    parsed: dict,
    allowed_hotels: list[str] | None = None,
    requested_hotels: list[str] | None = None,
    requested_areas: list[str] | None = None,
) -> str:
    source_table = safe_identifier(str(metric_def.get("source_table", "ads_hotel_operation_overview_wide")), "source_table")
    query_parts = build_overview_query_parts(source_table)
    period_fields = metric_def.get("period_fields", {})
    if not isinstance(period_fields, dict) or not period_fields:
        raise HTTPException(status_code=500, detail={"message": "metric definition is missing period_fields"})

    requested_period = str(parsed.get("period_type", "MTD")).strip() or "MTD"
    fields = period_fields.get(requested_period)
    if not isinstance(fields, dict):
        requested_period, fields = next(iter(period_fields.items()))
    actual_field_name = safe_identifier(str(fields.get("actual", "")), "actual field")
    compare_mode = str(parsed.get("compare_mode", "actual")).strip() or "actual"
    if compare_mode == "budget":
        compare_field = fields.get("budget") or fields.get("last_year") or fields.get("actual")
    elif compare_mode == "yoy":
        compare_field = fields.get("last_year") or fields.get("budget") or fields.get("actual")
    else:
        compare_field = fields.get("budget") or fields.get("last_year") or fields.get("actual")
    compare_field_name = safe_identifier(str(compare_field), "compare field")
    actual_field = f"{query_parts['metric_prefix']}.{actual_field_name}" if query_parts["metric_prefix"] else actual_field_name
    compare_field = f"{query_parts['metric_prefix']}.{compare_field_name}" if query_parts["metric_prefix"] else compare_field_name

    time_scope = str(parsed.get("time_scope", "")).strip()
    if not _TIME_SCOPE_RE.fullmatch(time_scope):
        raise HTTPException(status_code=400, detail={"message": "invalid time_scope", "time_scope": time_scope})

    where_clauses = [f"{query_parts['time_field']} = {sql_literal(time_scope)}"]
    area_scope = [str(area).strip() for area in (requested_areas or []) if str(area).strip()]
    if area_scope:
        area_clause = ", ".join(sql_literal(area) for area in area_scope)
        where_clauses.append(f"{query_parts['area_filter']} IN ({area_clause})")

    dimension_filters = [
        ("requested_manage_corps", "manage_corp_filter"),
        ("requested_brand_children", "brand_child_filter"),
        ("requested_builders", "builder_filter"),
        ("requested_brand_levels", "brand_level_filter"),
        ("requested_city_levels", "city_level_filter"),
    ]
    for parsed_key, query_key in dimension_filters:
        clause = dimension_scope_clause(query_parts[query_key], [str(item).strip() for item in parsed.get(parsed_key, []) if str(item).strip()])
        if clause:
            where_clauses.append(clause)

    explicit_hotel_scope = [str(hotel).strip() for hotel in (requested_hotels or []) if str(hotel).strip()]
    if explicit_hotel_scope:
        hotel_clause = hotel_scope_clause(query_parts.get("hotel_search_filter", query_parts["hotel_filter"]), explicit_hotel_scope)
        if hotel_clause:
            where_clauses.append(hotel_clause)

    hotel_scope = [str(hotel).strip() for hotel in (allowed_hotels or []) if str(hotel).strip()]
    if hotel_scope and hotel_scope != ["ALL"]:
        hotel_clause = ", ".join(sql_literal(hotel) for hotel in hotel_scope)
        where_clauses.append(f"{query_parts['hotel_filter']} IN ({hotel_clause})")

    object_label = str(
        (parsed.get("query_plan") or {}).get("query_object_label")
        or "组合汇总"
    ).strip() or "组合汇总"
    prefix = f"{query_parts['metric_prefix']}." if query_parts["metric_prefix"] else ""
    return f'''
SELECT
  {sql_literal(object_label)} AS hotel_name,
  {sql_literal(str((parsed.get("query_plan") or {}).get("query_object_type") or "portfolio"))} AS area,
  COUNT(*) AS portfolio_member_count,
  SUM({prefix}TOTAL_INCOME_MTD_A) AS total_income_actual,
  SUM({prefix}TOTAL_INCOME_MTD_B) AS total_income_budget,
  SUM({prefix}TOTAL_INCOME_MTD_L) AS total_income_last_year,
  SUM({prefix}ROOM_INCOME_MTD_A) AS room_income_actual,
  SUM({prefix}ROOM_INCOME_MTD_B) AS room_income_budget,
  SUM({prefix}ROOM_INCOME_MTD_L) AS room_income_last_year,
  SUM({prefix}RESTAURANT_INCOME_MTD_A) AS restaurant_income_actual,
  SUM({prefix}RESTAURANT_INCOME_MTD_B) AS restaurant_income_budget,
  SUM({prefix}RESTAURANT_INCOME_MTD_L) AS restaurant_income_last_year,
  SUM({prefix}BANQUET_INCOME_MTD_A) AS banquet_income_actual,
  SUM({prefix}BANQUET_INCOME_MTD_B) AS banquet_income_budget,
  SUM({prefix}BANQUET_INCOME_MTD_L) AS banquet_income_last_year,
  SUM({prefix}OTHER_DEPT_INCOME_MTD_A) AS other_dept_income_actual,
  SUM({prefix}OTHER_RATE_INCOME_MTD_A) AS other_rate_income_actual,
  SUM({prefix}OPERATING_PROFIT_MTD_A) AS operating_profit_actual,
  SUM({prefix}OPERATING_PROFIT_MTD_B) AS operating_profit_budget,
  SUM({prefix}OPERATING_PROFIT_MTD_L) AS operating_profit_last_year,
  SUM({prefix}OWNER_PROFIT_MTD_A) AS owner_profit_actual,
  SUM({prefix}ROOM_PROFIT_MTD_A) AS room_profit_actual,
  SUM({prefix}RESTAURANT_PROFIT_MTD_A) AS restaurant_profit_actual,
  SUM({prefix}RENTAL_ROOMS_NUM_MTD_A) AS rental_rooms_actual,
  AVG({prefix}AVE_HOUSE_PRICE_MTD_A) AS adr_actual,
  AVG({prefix}AVE_HOUSE_PRICE_MTD_B) AS adr_budget,
  AVG({prefix}AVE_HOUSE_PRICE_MTD_L) AS adr_last_year,
  AVG({prefix}OCCUPANCY_RATE_MTD_A) AS occupancy_rate_actual,
  AVG({prefix}OCCUPANCY_RATE_MTD_B) AS occupancy_rate_budget,
  AVG({prefix}OCCUPANCY_RATE_MTD_L) AS occupancy_rate_last_year,
  AVG({prefix}INCOME_PER_ROOM_MTD_A) AS revpar_actual,
  AVG({prefix}INCOME_PER_ROOM_MTD_B) AS revpar_budget,
  AVG({prefix}INCOME_PER_ROOM_MTD_L) AS revpar_last_year,
  SUM({prefix}ROOM_COST_MTD_A) AS room_cost_actual,
  SUM({prefix}RESTAURANT_COST_MTD_A) AS restaurant_cost_actual,
  SUM({prefix}FOOD_COST_MTD_A) AS food_cost_actual,
  SUM({prefix}WINE_COSE_MTD_A) AS wine_cost_actual,
  SUM({prefix}ADMINI_EXPENSES_MTD_A) AS admin_expenses_actual,
  SUM({prefix}ENERGY_EXPENSES_MTD_A) AS energy_expenses_actual,
  SUM({prefix}PEOPLE_COST_MTD_A) AS people_cost_actual,
  SUM({actual_field}) AS actual_value,
  SUM({compare_field}) AS compare_value,
  (SUM({actual_field}) - SUM({compare_field})) AS diff_value,
  (SUM({actual_field}) - SUM({compare_field})) / NULLIF(SUM({compare_field}), 0) AS diff_rate
FROM {query_parts["from_clause"]}
WHERE {" AND ".join(where_clauses)}
'''.strip()


def build_portfolio_breakdown(
    metric_def: dict,
    parsed: dict,
    allowed_hotels: list[str] | None = None,
    requested_hotels: list[str] | None = None,
    requested_areas: list[str] | None = None,
) -> list[dict]:
    detail_sql = build_sql(
        metric_def,
        parsed,
        allowed_hotels,
        requested_hotels,
        requested_areas,
    )
    try:
        detail_result = request_json(
            "POST",
            f"{DB_EXECUTOR_SERVICE_URL}/api/v1/db/query",
            {"sql": detail_sql},
            stage="db-executor-portfolio-breakdown",
        )
    except HTTPException:
        return []
    detail_rows = detail_result.get("rows", [])
    if not isinstance(detail_rows, list):
        return []
    return detail_rows[:5]


def _unique_non_empty(rows: list[dict], key: str) -> list[str]:
    values: list[str] = []
    for row in rows:
        item = str(row.get(key) or "").strip()
        if item and item not in values:
            values.append(item)
    return values


def build_portfolio_benchmark_sql(metric_def: dict, parsed: dict, breakdown_rows: list[dict]) -> str | None:
    if not breakdown_rows:
        return None
    source_table = safe_identifier(str(metric_def.get("source_table", "wddm_dim_overview_cockpit_f")), "source_table")
    if source_table not in _OVERVIEW_SOURCE_TABLES:
        return None
    query_parts = build_overview_query_parts(source_table)
    time_scope = str(parsed.get("time_scope", "")).strip()
    if not _TIME_SCOPE_RE.fullmatch(time_scope):
        return None

    areas = _unique_non_empty(breakdown_rows, "area")
    brand_levels = _unique_non_empty(breakdown_rows, "brand_level")
    city_levels = _unique_non_empty(breakdown_rows, "city_level")
    group_hotels = _unique_non_empty(breakdown_rows, "hotel_name")

    where_clauses = [f"{query_parts['time_field']} = {sql_literal(time_scope)}"]
    if areas:
        where_clauses.append(f"{query_parts['area_filter']} IN ({', '.join(sql_literal(item) for item in areas)})")
    if brand_levels:
        where_clauses.append(f"{query_parts['brand_level_filter']} IN ({', '.join(sql_literal(item) for item in brand_levels)})")
    if city_levels:
        where_clauses.append(f"{query_parts['city_level_filter']} IN ({', '.join(sql_literal(item) for item in city_levels)})")
    hotel_exclusion = hotel_scope_clause(query_parts.get("hotel_search_filter", query_parts["hotel_filter"]), group_hotels)
    if hotel_exclusion:
        where_clauses.append(f"NOT {hotel_exclusion}")

    prefix = f"{query_parts['metric_prefix']}." if query_parts["metric_prefix"] else ""
    cost_total = " + ".join(
        [
            f"COALESCE({prefix}PEOPLE_COST_MTD_A, 0)",
            f"COALESCE({prefix}ENERGY_EXPENSES_MTD_A, 0)",
            f"COALESCE({prefix}RESTAURANT_COST_MTD_A, 0)",
            f"COALESCE({prefix}ROOM_COST_MTD_A, 0)",
            f"COALESCE({prefix}ADMINI_EXPENSES_MTD_A, 0)",
        ]
    )
    return f'''
SELECT
  COUNT(*) AS peer_count,
  AVG({prefix}TOTAL_INCOME_MTD_A) AS avg_total_income,
  AVG({prefix}INCOME_PER_ROOM_MTD_A) AS avg_revpar,
  AVG({prefix}OPERATING_PROFIT_MTD_A) AS avg_operating_profit,
  AVG({prefix}OPERATING_PROFIT_MTD_A / NULLIF({prefix}TOTAL_INCOME_MTD_A, 0)) AS avg_profit_margin,
  AVG(({cost_total}) / NULLIF({prefix}TOTAL_INCOME_MTD_A, 0)) AS avg_cost_rate
FROM {query_parts["from_clause"]}
WHERE {" AND ".join(where_clauses)}
'''.strip()


def build_portfolio_internal_benchmark(rows: list[dict], breakdown_rows: list[dict], metric_def: dict, parsed: dict) -> dict[str, object] | None:
    if not rows or not breakdown_rows:
        return None
    benchmark_sql = build_portfolio_benchmark_sql(metric_def, parsed, breakdown_rows)
    if not benchmark_sql:
        return None
    benchmark_result = request_json(
        "POST",
        f"{DB_EXECUTOR_SERVICE_URL}/api/v1/db/query",
        {"sql": benchmark_sql},
        stage="db-executor-portfolio-benchmark",
    )
    benchmark_rows = benchmark_result.get("rows", [])
    if not isinstance(benchmark_rows, list) or not benchmark_rows:
        return None
    benchmark = benchmark_rows[0]
    peer_count = benchmark.get("peer_count")
    if not isinstance(peer_count, (int, float)) or int(peer_count) <= 0:
        return None
    current = rows[0]
    total_income = current.get("total_income_actual")
    operating_profit = current.get("operating_profit_actual")
    return {
        "peer_count": int(peer_count),
        "scope_used": "组合同区域同档次样本",
        "scope": {
            "area": " / ".join(_unique_non_empty(breakdown_rows, "area")),
            "brand_level": " / ".join(_unique_non_empty(breakdown_rows, "brand_level")),
            "city_level": " / ".join(_unique_non_empty(breakdown_rows, "city_level")),
        },
        "current": {
            "hotel_name": current.get("hotel_name"),
            "total_income": total_income,
            "revpar": current.get("revpar_actual"),
            "operating_profit": operating_profit,
            "profit_margin": (
                (operating_profit / total_income)
                if isinstance(total_income, (int, float)) and total_income not in (0, 0.0) and isinstance(operating_profit, (int, float))
                else None
            ),
            "cost_rate": (
                (
                    sum(
                        value
                        for value in [
                            current.get("people_cost_actual"),
                            current.get("energy_expenses_actual"),
                            current.get("restaurant_cost_actual"),
                            current.get("room_cost_actual"),
                            current.get("admin_expenses_actual"),
                        ]
                        if isinstance(value, (int, float))
                    )
                    / total_income
                )
                if isinstance(total_income, (int, float)) and total_income not in (0, 0.0)
                else None
            ),
        },
        "peer_avg": {
            "total_income": benchmark.get("avg_total_income"),
            "revpar": benchmark.get("avg_revpar"),
            "operating_profit": benchmark.get("avg_operating_profit"),
            "profit_margin": benchmark.get("avg_profit_margin"),
            "cost_rate": benchmark.get("avg_cost_rate"),
        },
    }


def build_portfolio_outliers(rows: list[dict]) -> dict[str, dict[str, object]] | None:
    if not rows:
        return None

    def pick_max(items: list[dict], key: str) -> dict | None:
        valid = [item for item in items if isinstance(item.get(key), (int, float))]
        return max(valid, key=lambda item: item.get(key)) if valid else None

    def pick_min(items: list[dict], key: str) -> dict | None:
        valid = [item for item in items if isinstance(item.get(key), (int, float))]
        return min(valid, key=lambda item: item.get(key)) if valid else None

    return {
        "income": {
            "best": pick_max(rows, "diff_value"),
            "worst": pick_min(rows, "diff_value"),
        },
        "profit": {
            "best": pick_max(rows, "operating_profit_actual"),
            "worst": pick_min(rows, "operating_profit_actual"),
        },
        "cost": {
            "best": pick_min(rows, "people_cost_actual"),
            "worst": pick_max(rows, "people_cost_actual"),
        },
    }


def build_explain_sql(
    parsed: dict,
    allowed_hotels: list[str] | None = None,
    requested_hotels: list[str] | None = None,
    requested_areas: list[str] | None = None,
) -> str:
    time_scope = str(parsed.get("time_scope", "")).strip()
    if not _TIME_SCOPE_RE.fullmatch(time_scope):
        raise HTTPException(status_code=400, detail={"message": "invalid time_scope", "time_scope": time_scope})

    where_clauses = [
        f"CALMONTH = {sql_literal(time_scope)}",
        "(is_total = 0 OR is_total = '0' OR is_total IS NULL)",
    ]
    area_scope = [str(area).strip() for area in (requested_areas or []) if str(area).strip()]
    if area_scope:
        area_clause = ", ".join(sql_literal(area) for area in area_scope)
        where_clauses.append(f"area IN ({area_clause})")

    explain_dimension_filters = [
        ("requested_manage_corps", "brand"),
        ("requested_brand_children", "brand_child"),
        ("requested_builders", "Builder"),
        ("requested_departments", "Dept"),
        ("requested_accounts", "CONCAT_WS('|', COALESCE(account_name, ''), COALESCE(account_nameF01, ''), COALESCE(account_nameF02, ''), COALESCE(accountName, ''))"),
    ]
    for parsed_key, expression in explain_dimension_filters:
        clause = dimension_scope_clause(expression, [str(item).strip() for item in parsed.get(parsed_key, []) if str(item).strip()])
        if clause:
            where_clauses.append(clause)

    explicit_hotel_scope = [str(hotel).strip() for hotel in (requested_hotels or []) if str(hotel).strip()]
    if explicit_hotel_scope:
        hotel_clause = hotel_scope_clause("hotel_name_s", explicit_hotel_scope[:1])
        if hotel_clause:
            where_clauses.append(hotel_clause)

    hotel_scope = [str(hotel).strip() for hotel in (allowed_hotels or []) if str(hotel).strip()]
    if hotel_scope and hotel_scope != ["ALL"]:
        hotel_clause = ", ".join(sql_literal(hotel) for hotel in hotel_scope[:1])
        where_clauses.append(f"hotel_name_s IN ({hotel_clause})")

    compare_field = "mtd_B" if parsed.get("compare_mode") == "budget" else "mtd_L"
    variance_direction = str(parsed.get("variance_direction", "all")).strip() or "all"
    if variance_direction == "below":
        where_clauses.append(f"mtd_a < {compare_field}")
    elif variance_direction == "above":
        where_clauses.append(f"mtd_a > {compare_field}")
    return f'''
SELECT
  hotel_name_s AS hotel_name,
  Dept AS dept,
  account_name,
  mtd_a AS actual_value,
  {compare_field} AS compare_value,
  (mtd_a - {compare_field}) AS diff_value,
  (mtd_a - {compare_field}) / NULLIF({compare_field}, 0) AS diff_rate
FROM {_DETAIL_SOURCE_TABLE}
WHERE {" AND ".join(where_clauses)}
ORDER BY ABS(mtd_a - {compare_field}) DESC
LIMIT 20
'''.strip()


def build_internal_benchmark_sql(metric_def: dict, parsed: dict, focus_row: dict, dimensions: list[tuple[str, str]]) -> str | None:
    source_table = safe_identifier(str(metric_def.get("source_table", "wddm_dim_overview_cockpit_f")), "source_table")
    if source_table not in _OVERVIEW_SOURCE_TABLES:
        return None

    query_parts = build_overview_query_parts(source_table)
    time_scope = str(parsed.get("time_scope", "")).strip()
    if not _TIME_SCOPE_RE.fullmatch(time_scope):
        return None

    hotel_name = str(focus_row.get("hotel_name") or "").strip()
    if not hotel_name:
        return None

    where_clauses = [f"{query_parts['time_field']} = {sql_literal(time_scope)}"]
    for field_name, query_key in dimensions:
        value = str(focus_row.get(field_name) or "").strip()
        if value:
            where_clauses.append(f"{query_parts[query_key]} = {sql_literal(value)}")

    hotel_exclusion = hotel_scope_clause(query_parts.get("hotel_search_filter", query_parts["hotel_filter"]), [hotel_name])
    if hotel_exclusion:
        where_clauses.append(f"NOT {hotel_exclusion}")

    prefix = f"{query_parts['metric_prefix']}." if query_parts["metric_prefix"] else ""
    total_income = f"{prefix}TOTAL_INCOME_MTD_A"
    revpar = f"{prefix}INCOME_PER_ROOM_MTD_A"
    operating_profit = f"{prefix}OPERATING_PROFIT_MTD_A"
    cost_total = " + ".join(
        [
            f"COALESCE({prefix}PEOPLE_COST_MTD_A, 0)",
            f"COALESCE({prefix}ENERGY_EXPENSES_MTD_A, 0)",
            f"COALESCE({prefix}RESTAURANT_COST_MTD_A, 0)",
            f"COALESCE({prefix}ROOM_COST_MTD_A, 0)",
            f"COALESCE({prefix}ADMINI_EXPENSES_MTD_A, 0)",
        ]
    )

    return f'''
SELECT
  COUNT(*) AS peer_count,
  AVG({total_income}) AS avg_total_income,
  AVG({revpar}) AS avg_revpar,
  AVG({operating_profit}) AS avg_operating_profit,
  AVG({operating_profit} / NULLIF({total_income}, 0)) AS avg_profit_margin,
  AVG(({cost_total}) / NULLIF({total_income}, 0)) AS avg_cost_rate
FROM {query_parts["from_clause"]}
WHERE {" AND ".join(where_clauses)}
'''.strip()


def summarize_rows(parsed: dict, rows: list[dict]) -> str:
    metric_name = parsed.get("metric_name") or parsed.get("metric_code", "指标")
    time_scope = parsed.get("time_scope", "当前期间")
    if not rows:
        return f"{metric_name} 在 {time_scope} 未查询到结果。"
    first_row = rows[0]
    query_plan = parsed.get("query_plan") if isinstance(parsed.get("query_plan"), dict) else {}
    if query_plan.get("query_grain") == "portfolio":
        object_label = query_plan.get("query_object_label") or first_row.get("hotel_name") or "当前组合"
        member_count = first_row.get("portfolio_member_count")
        actual_value = first_row.get("actual_value")
        compare_value = first_row.get("compare_value")
        return (
            f"{object_label} 在 {time_scope} 已完成组合汇总分析，"
            f"样本 {member_count or 'N/A'} 家，实际值 {actual_value}，对比值 {compare_value}。"
        )
    hotel_name = first_row.get("hotel_name")
    actual_value = first_row.get("actual_value")
    compare_value = first_row.get("compare_value")
    return f"{metric_name} 在 {time_scope} 返回 {len(rows)} 条结果，首条为 {hotel_name}，实际值 {actual_value}，对比值 {compare_value}。"


def extract_internal_benchmark(rows: list[dict], benchmark_rows: list[dict]) -> dict[str, object] | None:
    if not rows or not benchmark_rows:
        return None
    focus = rows[0]
    benchmark = benchmark_rows[0] if benchmark_rows else {}
    peer_count = benchmark.get("peer_count")
    if not isinstance(peer_count, (int, float)):
        return None
    return {
        "peer_count": int(peer_count),
        "scope": {
            "area": focus.get("area"),
            "brand": focus.get("brand"),
            "brand_child": focus.get("brand_child"),
            "brand_level": focus.get("brand_level"),
            "city_level": focus.get("city_level"),
        },
        "current": {
            "hotel_name": focus.get("hotel_name"),
            "total_income": focus.get("total_income_actual"),
            "revpar": focus.get("revpar_actual"),
            "operating_profit": focus.get("operating_profit_actual"),
            "profit_margin": (
                (focus.get("operating_profit_actual") / focus.get("total_income_actual"))
                if isinstance(focus.get("operating_profit_actual"), (int, float)) and isinstance(focus.get("total_income_actual"), (int, float)) and focus.get("total_income_actual") not in (0, 0.0)
                else None
            ),
            "cost_rate": (
                (
                    sum(
                        value
                        for value in [
                            focus.get("people_cost_actual"),
                            focus.get("energy_expenses_actual"),
                            focus.get("restaurant_cost_actual"),
                            focus.get("room_cost_actual"),
                            focus.get("admin_expenses_actual"),
                        ]
                        if isinstance(value, (int, float))
                    )
                    / focus.get("total_income_actual")
                )
                if isinstance(focus.get("total_income_actual"), (int, float)) and focus.get("total_income_actual") not in (0, 0.0)
                else None
            ),
        },
        "peer_avg": {
            "total_income": benchmark.get("avg_total_income"),
            "revpar": benchmark.get("avg_revpar"),
            "operating_profit": benchmark.get("avg_operating_profit"),
            "profit_margin": benchmark.get("avg_profit_margin"),
            "cost_rate": benchmark.get("avg_cost_rate"),
        },
    }


def build_internal_benchmark(rows: list[dict], metric_def: dict, parsed: dict) -> dict[str, object] | None:
    if not rows:
        return None
    focus = rows[0]
    benchmark_tiers = [
        ("同区域同品牌同档次同城市等级", [("area", "area_filter"), ("brand_child", "brand_child_filter"), ("brand_level", "brand_level_filter"), ("city_level", "city_level_filter")]),
        ("同区域同品牌同档次", [("area", "area_filter"), ("brand_child", "brand_child_filter"), ("brand_level", "brand_level_filter")]),
        ("同区域同品牌", [("area", "area_filter"), ("brand_child", "brand_child_filter")]),
        ("同区域", [("area", "area_filter")]),
    ]
    for scope_label, dimensions in benchmark_tiers:
        benchmark_sql = build_internal_benchmark_sql(metric_def, parsed, focus, dimensions)
        if not benchmark_sql:
            continue
        try:
            benchmark_result = request_json(
                "POST",
                f"{DB_EXECUTOR_SERVICE_URL}/api/v1/db/query",
                {"sql": benchmark_sql},
                stage="db-executor-benchmark",
            )
        except HTTPException:
            continue
        benchmark_rows = benchmark_result.get("rows", [])
        if not isinstance(benchmark_rows, list):
            continue
        benchmark = extract_internal_benchmark(rows, benchmark_rows)
        if benchmark and int(benchmark.get("peer_count") or 0) > 0:
            benchmark["scope_used"] = scope_label
            return benchmark
    fallback = extract_internal_benchmark(rows, [{"peer_count": 0}])
    if fallback:
        fallback["scope_used"] = "未找到内部同类样本"
    return fallback


def build_external_benchmark_stub(parsed: dict, internal_benchmark: dict[str, object] | None, enabled: bool) -> dict[str, object] | None:
    if not enabled:
        return None
    dimensions: list[str] = []
    mappings = [
        ("requested_areas", "区域"),
        ("requested_manage_corps", "管理公司"),
        ("requested_brand_children", "子品牌"),
        ("requested_brand_levels", "品牌档次"),
        ("requested_city_levels", "城市等级"),
        ("requested_hotels", "酒店"),
    ]
    for key, label in mappings:
        values = [str(item).strip() for item in parsed.get(key, []) if str(item).strip()]
        if values:
            dimensions.append(f"{label}：{' / '.join(values[:3])}")

    sample_hint = None
    if isinstance(internal_benchmark, dict) and int(internal_benchmark.get("peer_count") or 0) > 0:
        sample_hint = f"内部已找到 {internal_benchmark.get('scope_used') or '同口径'} 样本 {int(internal_benchmark.get('peer_count') or 0)} 家，可先作为管理口径基准。"

    return {
        "requested": True,
        "provider": EXTERNAL_BENCHMARK_PROVIDER,
        "status": "awaiting_provider",
        "dimensions": dimensions,
        "message": "你已开启外部行业对标。当前系统会先返回内部经营对标，外部行业数据需按所选 Provider 联网补充后再展示。",
        "disclaimers": [
            "外部行业样本的口径、更新频率和覆盖范围可能与公司内部口径不完全一致，结果需要结合来源说明一起阅读。",
            "建议把外部行业数据作为相对位置参考，不直接替代内部经营考核口径。",
            sample_hint or "若当前问题已有内部同口径样本，建议优先参考内部对标，再决定是否补充外部行业样本。",
        ],
    }


def shift_month_label(time_scope: str | None, offset: int) -> str | None:
    text = str(time_scope or "").strip()
    if not re.fullmatch(r"\d{6}", text):
        return None
    year = int(text[:4])
    month = int(text[4:6])
    month_index = (year * 12 + (month - 1)) + offset
    target_year = month_index // 12
    target_month = month_index % 12 + 1
    return f"{target_year}年{target_month}月"


def build_quick_filters(parsed: dict, rows: list[dict], portfolio_breakdown: list[dict]) -> list[dict[str, object]]:
    display_rows = portfolio_breakdown or rows
    query_plan = parsed.get("query_plan") if isinstance(parsed.get("query_plan"), dict) else {}
    query_object_label = str(query_plan.get("query_object_label") or "").strip()

    def unique_values(values: list[object], limit: int = 3) -> list[str]:
        items: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if not text or text in items:
                continue
            items.append(text)
            if len(items) >= limit:
                break
        return items

    areas = unique_values(list(parsed.get("requested_areas", [])) + [row.get("area") for row in display_rows])
    hotels = unique_values(
        [
            row.get("hotel_name")
            for row in display_rows
            if str(row.get("hotel_name") or "").strip() and str(row.get("hotel_name") or "").strip() != query_object_label
        ]
    )
    brands = unique_values(list(parsed.get("requested_brand_children", [])) + [row.get("brand_child") for row in display_rows])
    months = unique_values(
        [
            shift_month_label(parsed.get("time_scope"), -1),
            shift_month_label(parsed.get("time_scope"), 0),
            shift_month_label(parsed.get("time_scope"), 1),
        ]
    )
    compare_mode = str(parsed.get("compare_mode") or "actual").strip()
    analysis_mode = str(query_plan.get("analysis_mode") or "").strip()
    compare_items = [
        item
        for item in [
            {"label": "预算对比", "prompt": "切换成预算对比", "active": compare_mode == "budget"},
            {"label": "同比变化", "prompt": "切换成同比变化", "active": compare_mode == "yoy"},
            {"label": "实际表现", "prompt": "切换成实际表现", "active": compare_mode == "actual"},
        ]
        if not item["active"]
    ][:2]
    mode_items = [
        item
        for item in [
            {"label": "组合总览", "prompt": "改看组合总览", "active": analysis_mode == "portfolio_overview"},
            {"label": "归因分析", "prompt": "继续展开原因", "active": analysis_mode == "driver_analysis"},
            {"label": "经营摘要", "prompt": "换成经营摘要", "active": analysis_mode == "management_report"},
        ]
        if not item["active"]
    ][:2]
    groups_by_label = {
        "区域": {"label": "区域", "items": [{"label": item, "prompt": f"只看{item}"} for item in areas]},
        "酒店": {"label": "酒店", "items": [{"label": item, "prompt": f"只看{item}"} for item in hotels]},
        "月份": {"label": "月份", "items": [{"label": item, "prompt": f"切到{item}"} for item in months]},
        "品牌": {"label": "品牌", "items": [{"label": item, "prompt": f"只看{item}品牌"} for item in brands]},
        "口径": {"label": "口径", "items": [{"label": item["label"], "prompt": item["prompt"]} for item in compare_items]},
        "分析方式": {"label": "分析方式", "items": [{"label": item["label"], "prompt": item["prompt"]} for item in mode_items]},
    }

    object_type = str(query_plan.get("query_object_type") or "").strip()
    requested_hotels = parsed.get("requested_hotels") if isinstance(parsed.get("requested_hotels"), list) else []
    requested_areas = parsed.get("requested_areas") if isinstance(parsed.get("requested_areas"), list) else []
    is_single_hotel = object_type == "single_hotel" or (len(requested_hotels) == 1 and query_plan.get("query_grain") != "portfolio")
    is_area_scope = object_type == "area_scope" or bool(requested_areas)
    is_portfolio = query_plan.get("query_grain") == "portfolio" or object_type in {"hotel_group", "manage_corp_scope", "brand_scope"}

    if is_single_hotel:
        template = ["月份", "口径", "分析方式", "品牌", "区域"]
    elif is_area_scope and not is_single_hotel:
        template = ["酒店", "品牌", "月份", "分析方式", "口径"]
    elif is_portfolio:
        template = ["区域", "品牌", "酒店", "分析方式", "月份", "口径"]
    else:
        template = ["月份", "口径", "分析方式", "区域", "酒店", "品牌"]

    ordered_groups = [groups_by_label[label] for label in template if groups_by_label.get(label, {}).get("items")]
    remaining_groups = [
        group for label, group in groups_by_label.items()
        if label not in template and group.get("items")
    ]
    return ordered_groups + remaining_groups


@app.post("/api/v1/ai/query")
def ai_query(payload: QueryRequest):
    request_started = time.perf_counter()
    timings: dict[str, int] = {}
    trace_id = f"trace_{uuid4().hex[:12]}"
    warnings: list[str] = []
    stage_started = time.perf_counter()
    auth_scope = request_json(
        "POST",
        f"{AUTH_SERVICE_URL}/api/v1/auth/context",
        {"user_id": payload.auth.user_id, "role": payload.auth.role},
        stage="auth",
    )
    timings["auth_ms"] = elapsed_ms(stage_started)
    stage_started = time.perf_counter()
    parsed = request_json(
        "POST",
        f"{SEMANTIC_SERVICE_URL}/api/v1/semantic/parse",
        {"question": payload.question, "time_scope": payload.context.time_scope},
        stage="semantic",
    )
    timings["semantic_ms"] = elapsed_ms(stage_started)
    if parsed.get("needs_clarification"):
        timings["total_ms"] = elapsed_ms(request_started)
        clarification_question = str(parsed.get("clarification_question") or "我先确认一下你的分析范围。")
        clarification_options = parsed.get("clarification_options") if isinstance(parsed.get("clarification_options"), list) else []
        write_learning_sample(
            trace_id=trace_id,
            question=payload.question,
            stage="semantic",
            reason="clarification_required",
            parsed=parsed,
            row_count=0,
            warnings=["clarification_required"],
            extra={"clarification_options": clarification_options},
        )
        return {
            "trace_id": trace_id,
            "summary": clarification_question,
            "interaction_mode": "clarification",
            "clarification": {
                "question": clarification_question,
                "options": [str(item) for item in clarification_options if str(item).strip()],
            },
            "parsed_intent": parsed,
            "data_points": [],
            "warnings": ["clarification_required"],
            "performance": timings,
        }
    stage_started = time.perf_counter()
    metric_def = request_json(
        "GET",
        f"{METRIC_SERVICE_URL}/api/v1/metrics/{parsed['metric_code']}",
        stage="metric",
    )
    timings["metric_ms"] = elapsed_ms(stage_started)

    resolved_requested_hotels = effective_requested_hotels(parsed)
    query_plan = parsed.get("query_plan") if isinstance(parsed.get("query_plan"), dict) else {}
    sql_text = (
        build_explain_sql(
            parsed,
            auth_scope.get("allowed_hotels", []),
            resolved_requested_hotels,
            parsed.get("requested_areas", []),
        )
        if parsed.get("intent") == "explain"
        else build_portfolio_sql(
            metric_def,
            parsed,
            auth_scope.get("allowed_hotels", []),
            resolved_requested_hotels,
            parsed.get("requested_areas", []),
        )
        if query_plan.get("query_grain") == "portfolio"
        else build_sql(
            metric_def,
            parsed,
            auth_scope.get("allowed_hotels", []),
            resolved_requested_hotels,
            parsed.get("requested_areas", []),
        )
    )
    stage_started = time.perf_counter()
    sql_plan = request_json(
        "POST",
        f"{SQL_GUARDRAIL_SERVICE_URL}/api/v1/sql/validate",
        {
            "sql": sql_text,
            "metric_code": parsed["metric_code"],
            "allowed_hotels": auth_scope.get("allowed_hotels", []),
            "allowed_areas": auth_scope.get("allowed_areas", []),
            "hotel_column": auth_scope.get("sql_scope", {}).get("hotel_column", "HOTEL_NAME_s"),
            "area_column": auth_scope.get("sql_scope", {}).get("area_column", "area"),
        },
        stage="sql-guardrail",
    )
    timings["sql_guardrail_ms"] = elapsed_ms(stage_started)
    if not sql_plan.get("safe", True):
        raise HTTPException(
            status_code=400,
            detail={
                "trace_id": trace_id,
                "stage": "sql-guardrail",
                "message": "sql validation failed",
                "reasons": sql_plan.get("reasons", []),
            },
        )
    warnings.extend([str(item) for item in sql_plan.get("warnings", []) if str(item).strip()])

    stage_started = time.perf_counter()
    db_result = request_json(
        "POST",
        f"{DB_EXECUTOR_SERVICE_URL}/api/v1/db/query",
        {"sql": sql_plan["rewritten_sql"]},
        stage="db-executor",
    )
    timings["db_executor_ms"] = elapsed_ms(stage_started)
    data_source = {
        "source": db_result.get("source"),
        "warehouse_manifest": db_result.get("warehouse_manifest"),
    }
    rows = db_result.get("rows", [])
    if not isinstance(rows, list):
        raise HTTPException(
            status_code=502,
            detail={"trace_id": trace_id, "stage": "db-executor", "message": "invalid rows payload"},
        )
    if query_plan.get("query_grain") == "portfolio" and rows:
        first_portfolio_row = rows[0] if isinstance(rows[0], dict) else {}
        if int(first_portfolio_row.get("portfolio_member_count") or 0) <= 0:
            rows = []
    row_count = len(rows)
    internal_benchmark = None
    portfolio_breakdown: list[dict] = []
    portfolio_outliers: dict[str, dict[str, object]] | None = None
    if query_plan.get("query_grain") == "portfolio" and resolved_requested_hotels:
        try:
            portfolio_breakdown = build_portfolio_breakdown(
                metric_def,
                parsed,
                auth_scope.get("allowed_hotels", []),
                resolved_requested_hotels,
                parsed.get("requested_areas", []),
            )
        except HTTPException as exc:
            warnings.append(f"portfolio breakdown fallback: {exc.detail}")
        portfolio_outliers = build_portfolio_outliers(portfolio_breakdown)
        if rows and portfolio_breakdown:
            try:
                internal_benchmark = build_portfolio_internal_benchmark(rows, portfolio_breakdown, metric_def, parsed)
            except HTTPException as exc:
                warnings.append(f"portfolio benchmark fallback: {exc.detail}")
    if parsed.get("intent") != "explain" and rows and query_plan.get("query_grain") != "portfolio":
        try:
            internal_benchmark = build_internal_benchmark(rows, metric_def, parsed)
        except HTTPException as exc:
            warnings.append(f"benchmark fallback: {exc.detail}")
    external_benchmark = build_external_benchmark_stub(parsed, internal_benchmark, payload.context.external_benchmark)

    summary = summarize_rows({**parsed, "metric_name": metric_def.get("name_cn")}, rows)
    try:
        stage_started = time.perf_counter()
        explained = request_json(
            "POST",
            f"{EXPLANATION_SERVICE_URL}/api/v1/explain/metric",
            {
                "question": payload.question,
                "parsed_intent": parsed,
                "rows": rows,
                "portfolio_breakdown": portfolio_breakdown,
                "portfolio_outliers": portfolio_outliers,
                "peer_benchmark": internal_benchmark,
                "external_benchmark_requested": payload.context.external_benchmark,
            },
            stage="explanation",
        )
        timings["explanation_ms"] = elapsed_ms(stage_started)
        summary = str(explained.get("summary") or summary)
        explanation_payload = explained
    except HTTPException as exc:
        timings["explanation_ms"] = elapsed_ms(stage_started)
        explanation_payload = {}
        warnings.append(f"explanation fallback: {exc.detail}")

    reason = learning_reason(parsed, rows, warnings)
    if reason:
        write_learning_sample(
            trace_id=trace_id,
            question=payload.question,
            stage="query",
            reason=reason,
            parsed=parsed,
            sql_text=sql_text,
            rewritten_sql=sql_plan.get("rewritten_sql"),
            row_count=row_count,
            warnings=warnings,
        )

    try:
        stage_started = time.perf_counter()
        request_json(
            "POST",
            f"{AUDIT_SERVICE_URL}/api/v1/audit/log",
            {
                "trace_id": trace_id,
                "user_id": payload.auth.user_id,
                "role": payload.auth.role,
                "question": payload.question,
                "endpoint": "/api/v1/ai/query",
                "parsed_intent": parsed,
                "sql_text": sql_text,
                "rewritten_sql": sql_plan["rewritten_sql"],
                "sql_safe": sql_plan.get("safe"),
                "sql_reasons": sql_plan.get("reasons", []),
                "result_summary": summary,
                "scope": auth_scope.get("sql_scope", {}),
                "metadata": {
                    "warnings": warnings,
                    "data_source": data_source,
                    "external_benchmark_requested": payload.context.external_benchmark,
                    "external_benchmark": external_benchmark,
                },
            },
            stage="audit",
        )
        timings["audit_ms"] = elapsed_ms(stage_started)
    except HTTPException as exc:
        timings["audit_ms"] = elapsed_ms(stage_started)
        warnings.append(f"audit fallback: {exc.detail}")

    timings["total_ms"] = elapsed_ms(request_started)
    portfolio_member_count = None
    if rows and isinstance(rows[0], dict):
        portfolio_member_count = rows[0].get("portfolio_member_count")
    if portfolio_member_count in (None, "", 0) and isinstance(parsed.get("query_plan"), dict):
        portfolio_member_count = parsed["query_plan"].get("resolved_hotel_count")
    quick_filters = build_quick_filters(parsed, rows, portfolio_breakdown)

    return {
        "trace_id": trace_id,
        "summary": summary,
        "parsed_intent": parsed,
        "metric_definition": metric_def,
        "sql_plan": sql_plan,
        "auth_scope": auth_scope,
        "data_source": data_source,
        "data_points": rows,
        "portfolio_member_count": portfolio_member_count,
        "portfolio_breakdown": portfolio_breakdown,
        "portfolio_outliers": portfolio_outliers,
        "quick_filters": quick_filters,
        "internal_benchmark": internal_benchmark,
        "external_benchmark": external_benchmark,
        "external_benchmark_requested": payload.context.external_benchmark,
        "explanation": explanation_payload,
        "warnings": warnings,
        "performance": timings,
    }


@app.post("/api/v1/ai/report")
def ai_report(payload: ReportRequest):
    result = ai_query(QueryRequest(question=payload.question, context=payload.context, auth=payload.auth))
    explanation = result.get("explanation", {})
    sections = explanation.get("report_sections") or []
    if not sections:
        sections = [
            {"title": "核心结论", "content": result.get("summary", "")},
            {"title": "数据概览", "content": f"返回 {len(result.get('data_points', []))} 条记录。"},
        ]

    markdown_lines = [f"## {section['title']}\n{section['content']}" for section in sections]
    return {
        "trace_id": result.get("trace_id"),
        "summary": result.get("summary"),
        "report_sections": sections,
        "report_markdown": "\n\n".join(markdown_lines),
        "source_query": {
            "question": payload.question,
            "parsed_intent": result.get("parsed_intent", {}),
        },
        "warnings": result.get("warnings", []),
    }
