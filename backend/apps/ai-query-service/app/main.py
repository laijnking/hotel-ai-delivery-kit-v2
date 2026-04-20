import os
import re
import json
import time
from collections import Counter
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
EXTERNAL_BENCHMARK_DATASET_DIR = Path(
    os.getenv("EXTERNAL_BENCHMARK_DATASET_DIR", Path(__file__).resolve().parents[3] / "runtime" / "external_benchmark")
)
EXTERNAL_BENCHMARK_API_BASE_URL = os.getenv("EXTERNAL_BENCHMARK_API_BASE_URL", "").strip()
EXTERNAL_BENCHMARK_API_KEY = os.getenv("EXTERNAL_BENCHMARK_API_KEY", "").strip()
EXTERNAL_BENCHMARK_ALLOWED_DOMAINS = [
    item.strip() for item in os.getenv("EXTERNAL_BENCHMARK_ALLOWED_DOMAINS", "").split(",") if item.strip()
]
APP_SETTINGS = Path(__file__).resolve().parents[3] / "configs" / "app_settings.yaml"
METRIC_DICTIONARY_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "metric_dictionary.yaml"
METRIC_BUNDLE_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "metric_bundles.yaml"
LEARNING_INBOX_DIR = Path(os.getenv("LEARNING_INBOX_DIR", Path(__file__).resolve().parents[3] / "runtime" / "learning_inbox"))
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TIME_SCOPE_RE = re.compile(r"^\d{6}$")
_OVERVIEW_SOURCE_TABLES = {"ads_hotel_operation_overview_wide", "wddm_dim_overview_cockpit_f"}
_DETAIL_SOURCE_TABLE = "vw_pnl_fact"
_HOTEL_INFO_SOURCE_TABLE = "dim_hotel_info"
_SCOPE_QUERY_OBJECT_TYPES = {"area_scope", "manage_corp_scope", "brand_scope", "filtered_scope"}
_ANALYSIS_CONTRACT_BLOCK_METRICS: dict[str, list[str]] = {
    "income_quality": ["TOTAL_INCOME", "ROOM_INCOME", "RESTAURANT_INCOME", "BANQUET_INCOME"],
    "room_efficiency": ["ADR", "OCCUPANCY_RATE", "REVPAR"],
    "profit_quality": ["OWNER_PROFIT", "OPERATING_PROFIT"],
    "cost_efficiency": ["PEOPLE_COST", "ENERGY_EXPENSES", "RESTAURANT_COST"],
}
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
    analysis_focus: str | None = None
    conversation_context: dict | None = None


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=2)
    context: QueryContext = Field(default_factory=QueryContext)
    auth: AuthInfo = Field(default_factory=AuthInfo)


class ReportRequest(BaseModel):
    question: str = Field(..., min_length=2)
    context: QueryContext = Field(default_factory=QueryContext)
    auth: AuthInfo = Field(default_factory=AuthInfo)


class IntentPreviewRequest(BaseModel):
    question: str = Field(..., min_length=2)
    context: QueryContext = Field(default_factory=QueryContext)


@app.get("/health")
def health():
    return {"status": "ok"}


@lru_cache(maxsize=1)
def load_app_settings() -> dict:
    with open(APP_SETTINGS, "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f) or {}
    return settings if isinstance(settings, dict) else {}


@lru_cache(maxsize=1)
def load_metric_catalog() -> dict[str, dict]:
    if not METRIC_DICTIONARY_CONFIG.exists():
        return {}
    with open(METRIC_DICTIONARY_CONFIG, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    items = data.get("metrics", []) if isinstance(data, dict) else []
    if not isinstance(items, list):
        return {}
    catalog: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        metric_code = str(item.get("metric_code") or "").strip()
        if metric_code:
            catalog[metric_code] = item
    return catalog


@lru_cache(maxsize=1)
def load_metric_bundles() -> dict[str, dict]:
    if not METRIC_BUNDLE_CONFIG.exists():
        return {}
    with open(METRIC_BUNDLE_CONFIG, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    bundles = data.get("bundles", {}) if isinstance(data, dict) else {}
    return bundles if isinstance(bundles, dict) else {}


@app.get("/api/v1/system/settings")
def system_settings():
    settings = load_app_settings()
    model_config = dict(settings.get("model_config", {})) if isinstance(settings.get("model_config"), dict) else {}
    model_config["runtime"] = {
        "fast_model": os.getenv("QWEN_FAST_MODEL", "").strip() or os.getenv("QWEN_MODEL", "").strip() or None,
        "deep_model": os.getenv("QWEN_DEEP_MODEL", "").strip() or os.getenv("QWEN_MODEL", "").strip() or None,
        "llm_base_url": os.getenv("QWEN_API_BASE_URL", "").strip() or None,
        "timeout_seconds": os.getenv("QWEN_TIMEOUT", "").strip() or None,
        "parse_policy": os.getenv("QWEN_PARSE_POLICY", "always").strip() or "always",
        "parse_confidence_threshold": os.getenv("QWEN_PARSE_CONFIDENCE_THRESHOLD", "0.82").strip() or "0.82",
        "explanation_policy": os.getenv("QWEN_EXPLANATION_POLICY", "auto").strip() or "auto",
    }
    return {
        "quick_questions": settings.get("quick_questions", []),
        "model_config": model_config,
        "answer_templates": settings.get("answer_templates", {}),
        "tuning_stages": settings.get("tuning_stages", []),
    }


@app.get("/api/v1/system/learning/summary")
def system_learning_summary(days: int = 7):
    window_days = max(1, min(int(days or 7), 30))
    records = read_learning_records(window_days)
    return {
        "window_days": window_days,
        "inbox_dir": str(LEARNING_INBOX_DIR),
        "summary": summarize_learning_records(records),
    }


@app.get("/api/v1/system/learning/harness-candidates")
def system_learning_harness_candidates(days: int = 7, limit: int = 10):
    window_days = max(1, min(int(days or 7), 30))
    candidate_limit = max(1, min(int(limit or 10), 50))
    records = read_learning_records(window_days)
    candidates = build_harness_candidates(records, candidate_limit)
    return {
        "window_days": window_days,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def _preview_metric_label(metric_code: str) -> str:
    metric = load_metric_catalog().get(metric_code, {})
    if isinstance(metric, dict):
        name = str(metric.get("name_cn") or "").strip()
        if name:
            return name
    return metric_code or "待识别指标"


def _preview_compare_label(compare_mode: str) -> str:
    return {
        "actual": "当前口径",
        "budget": "预算对比",
        "yoy": "同比观察",
    }.get(compare_mode, compare_mode or "系统默认")


def _preview_intent_label(intent: str) -> str:
    return {
        "query": "经营问答",
        "report": "经营摘要",
        "explain": "原因分析",
        "rank": "排名观察",
    }.get(intent, intent or "待识别意图")


def _semantic_draft_stats(parsed: dict) -> tuple[str | None, int]:
    draft = parsed.get("semantic_draft") if isinstance(parsed.get("semantic_draft"), dict) else {}
    source = str(draft.get("source") or "").strip() or None
    candidates = draft.get("candidates") if isinstance(draft.get("candidates"), dict) else {}
    return source, len(candidates)


def _preview_analysis_mode_label(query_plan: dict) -> str:
    analysis_mode = str(query_plan.get("analysis_mode") or "").strip()
    return {
        "portfolio_overview": "组合总览",
        "management_report": "管理摘要",
        "driver_analysis": "归因分析",
        "group_by_dimension_report": "分维度汇总",
        "hotel_metric_snapshot": "单点快照",
    }.get(analysis_mode, analysis_mode or "系统判断")


def _preview_conversation_action(parsed: dict, question: str) -> str:
    conversation_action = str(parsed.get("conversation_action") or "").strip()
    if conversation_action == "follow_up_continue":
        return "继续原因" if str(parsed.get("intent") or "").strip() == "explain" else "承接追问"
    if conversation_action == "refine_scope":
        return "缩小范围"
    if conversation_action == "shift_compare_mode":
        return "切换口径"
    if conversation_action == "management_summary":
        return "生成摘要"
    follow_up_mode = str(parsed.get("follow_up_mode") or "").strip()
    if follow_up_mode == "driver":
        return "继续原因"
    if follow_up_mode == "refine_scope":
        return "缩小范围"
    if follow_up_mode == "compare_shift":
        return "切换口径"
    if follow_up_mode == "continue":
        return "承接追问"
    if str(parsed.get("intent") or "").strip() == "report":
        return "生成摘要"
    if str(parsed.get("intent") or "").strip() == "explain":
        return "展开分析"
    return "发起新问题" if question.strip() else "等待输入"


def _preview_scope_label(parsed: dict) -> str:
    query_plan = parsed.get("query_plan") if isinstance(parsed.get("query_plan"), dict) else {}
    label = str(query_plan.get("query_object_label") or "").strip()
    if label:
        return label
    for field in ("requested_hotels", "requested_areas", "requested_manage_corps", "requested_brand_children"):
        values = parsed.get(field)
        if isinstance(values, list) and values:
            cleaned = [str(item).strip() for item in values if str(item).strip()]
            if cleaned:
                return " / ".join(cleaned[:2])
    return "当前管理范围"


def build_intent_preview(parsed: dict, question: str) -> dict:
    query_plan = parsed.get("query_plan") if isinstance(parsed.get("query_plan"), dict) else {}
    parse_debug = parsed.get("parse_debug") if isinstance(parsed.get("parse_debug"), dict) else {}
    clarification_options = parsed.get("clarification_options") if isinstance(parsed.get("clarification_options"), list) else []
    route_mode = str(parsed.get("route_mode") or "").strip() or ("fast_llm_parse" if parse_debug.get("llm_used") else "deterministic")
    preview = {
        "intent": _preview_intent_label(str(parsed.get("intent") or "").strip()),
        "metric": _preview_metric_label(str(parsed.get("metric_code") or "").strip()),
        "scope": _preview_scope_label(parsed),
        "time_scope": parsed.get("time_scope") if isinstance(parsed.get("time_scope"), str) else "",
        "compare_mode": _preview_compare_label(str(parsed.get("compare_mode") or "").strip()),
        "analysis_mode": _preview_analysis_mode_label(query_plan),
        "conversation_action": _preview_conversation_action(parsed, question),
    }
    summary = (
        str(parsed.get("clarification_question") or "").strip()
        if parsed.get("needs_clarification")
        else f"我理解你是想看 {preview['scope']} 的 {preview['metric']}，按 {preview['compare_mode']} 来做 {preview['analysis_mode']}。"
    )
    return {
        "question": question,
        "route_mode": route_mode,
        "needs_clarification": bool(parsed.get("needs_clarification")),
        "clarification_type": str(parsed.get("clarification_type") or "").strip() or None,
        "clarification_question": str(parsed.get("clarification_question") or "").strip() or None,
        "clarification_options": [str(item).strip() for item in clarification_options if str(item).strip()][:4],
        "summary": summary,
        "semantic_notes": [str(item).strip() for item in parsed.get("semantic_notes", []) if str(item).strip()] if isinstance(parsed.get("semantic_notes"), list) else [],
        "preview": preview,
        "parsed_intent": parsed,
    }


@app.post("/api/v1/ai/intent-preview")
def intent_preview(payload: IntentPreviewRequest):
    parsed = request_json(
        "POST",
        f"{SEMANTIC_SERVICE_URL}/api/v1/semantic/parse",
        {
            "question": payload.question,
            "time_scope": payload.context.time_scope,
            "conversation_context": payload.context.conversation_context,
        },
        stage="semantic-preview",
    )
    if payload.context.analysis_focus:
        parsed["analysis_focus"] = payload.context.analysis_focus
    return build_intent_preview(parsed, payload.question)


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
    analysis_contract: dict | None = None,
    analysis_blocks: list[dict] | None = None,
    guardrail: dict | None = None,
    trace_events: list[dict] | None = None,
) -> Path:
    LEARNING_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    target = LEARNING_INBOX_DIR / f"learning-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"
    parsed_payload = parsed or {}
    query_plan = parsed_payload.get("query_plan") if isinstance(parsed_payload.get("query_plan"), dict) else {}
    resolved_analysis_contract = analysis_contract or (
        query_plan.get("analysis_contract") if isinstance(query_plan.get("analysis_contract"), dict) else {}
    )
    record = {
        "schema_version": 2,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "trace_id": trace_id,
        "question": question,
        "stage": stage,
        "reason": reason,
        "review_status": "pending_review",
        "parsed_intent": parsed_payload,
        "sql_text": sql_text,
        "rewritten_sql": rewritten_sql,
        "row_count": row_count,
        "warnings": warnings or [],
        "analysis_contract": resolved_analysis_contract,
        "analysis_blocks": analysis_blocks or [],
        "guardrail": guardrail or {},
        "trace_events": trace_events or [],
        "alias_proposal": build_alias_proposal(question, parsed_payload, reason),
        "eval_case_proposal": build_eval_case_proposal(question, parsed_payload, reason),
        "extra": extra or {},
    }
    with target.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return target


def _learning_metadata(
    parsed: dict | None,
    *,
    external_benchmark_requested: bool = False,
    external_benchmark: dict | None = None,
    internal_benchmark: dict | None = None,
) -> dict[str, object]:
    parsed = parsed or {}
    query_plan = parsed.get("query_plan") if isinstance(parsed.get("query_plan"), dict) else {}
    metadata: dict[str, object] = {
        "metric_code": parsed.get("metric_code"),
        "compare_mode": parsed.get("compare_mode"),
        "intent": parsed.get("intent"),
        "time_scope": parsed.get("time_scope"),
        "query_object_type": query_plan.get("query_object_type"),
        "query_grain": query_plan.get("query_grain"),
        "analysis_mode": query_plan.get("analysis_mode"),
        "query_object_label": query_plan.get("query_object_label"),
        "requested_hotels": parsed.get("requested_hotels", []),
        "requested_areas": parsed.get("requested_areas", []),
        "requested_manage_corps": parsed.get("requested_manage_corps", []),
        "requested_brand_children": parsed.get("requested_brand_children", []),
        "external_benchmark_requested": external_benchmark_requested,
        "semantic_draft_source": _semantic_draft_stats(parsed)[0],
        "semantic_draft_candidate_count": _semantic_draft_stats(parsed)[1],
    }
    if isinstance(internal_benchmark, dict):
        metadata["internal_benchmark_scope"] = internal_benchmark.get("scope_used")
        metadata["internal_peer_count"] = internal_benchmark.get("peer_count")
    if isinstance(external_benchmark, dict):
        metadata["external_benchmark_provider"] = external_benchmark.get("provider")
        metadata["external_benchmark_status"] = external_benchmark.get("status")
    return metadata


def read_learning_records(days: int = 7) -> list[dict]:
    LEARNING_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    for path in sorted(LEARNING_INBOX_DIR.glob("learning-*.jsonl")):
        try:
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                created_at = str(record.get("created_at_utc") or "").strip()
                if days > 0 and created_at:
                    try:
                        created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                        age_seconds = (datetime.now(timezone.utc) - created_dt).total_seconds()
                        if age_seconds > days * 86400:
                            continue
                    except ValueError:
                        pass
                records.append(record)
        except OSError:
            continue
    return records


def summarize_learning_records(records: list[dict]) -> dict[str, object]:
    reason_counter: Counter[str] = Counter()
    metric_counter: Counter[str] = Counter()
    object_counter: Counter[str] = Counter()
    stage_counter: Counter[str] = Counter()
    latest_samples: list[dict[str, object]] = []

    def top_items(counter: Counter[str], label_key: str) -> list[dict[str, object]]:
        return [{label_key: key, "count": count} for key, count in counter.most_common(5)]

    sorted_records = sorted(
        (record for record in records if isinstance(record, dict)),
        key=lambda item: str(item.get("created_at_utc") or ""),
        reverse=True,
    )
    for record in sorted_records:
        reason_counter[str(record.get("reason") or "unknown")] += 1
        stage_counter[str(record.get("stage") or "unknown")] += 1
        parsed = record.get("parsed_intent") if isinstance(record.get("parsed_intent"), dict) else {}
        extra = record.get("extra") if isinstance(record.get("extra"), dict) else {}
        metric_counter[str(extra.get("metric_code") or parsed.get("metric_code") or "unknown")] += 1
        object_counter[str(extra.get("query_object_type") or parsed.get("query_plan", {}).get("query_object_type") or "unknown")] += 1
        if len(latest_samples) < 5:
            latest_samples.append(
                {
                    "created_at_utc": record.get("created_at_utc"),
                    "trace_id": record.get("trace_id"),
                    "reason": record.get("reason"),
                    "question": record.get("question"),
                    "metric_code": extra.get("metric_code") or parsed.get("metric_code"),
                    "query_object_type": extra.get("query_object_type") or parsed.get("query_plan", {}).get("query_object_type"),
                }
            )

    return {
        "sample_count": len(records),
        "reason_breakdown": top_items(reason_counter, "reason"),
        "metric_breakdown": top_items(metric_counter, "metric_code"),
        "query_object_breakdown": top_items(object_counter, "query_object_type"),
        "stage_breakdown": top_items(stage_counter, "stage"),
        "latest_samples": latest_samples,
    }


def _case_id_from_question(question: str, index: int) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", question.lower()).strip("_")
    if len(normalized) >= 6:
        return normalized[:48] + f"_{index}"
    return f"learning_case_{index}"


def _metric_sql_contains(metric_code: str | None) -> list[str]:
    mapping = {
        "TOTAL_INCOME": ["wddm_dim_overview_cockpit_f", "TOTAL_INCOME_MTD_A"],
        "OPERATING_PROFIT": ["wddm_dim_overview_cockpit_f", "OPERATING_PROFIT_MTD_A"],
        "OWNER_PROFIT": ["wddm_dim_overview_cockpit_f", "OWNER_PROFIT_MTD_A"],
        "OPERATING_HOTEL_COUNT": ["dim_hotel_info", "status = 1"],
    }
    return mapping.get(str(metric_code or "").strip(), [])


def build_alias_proposal(question: str, parsed: dict | None, reason: str) -> dict[str, object]:
    parsed = parsed or {}
    terms: list[dict[str, object]] = []
    candidates = [
        ("hotel", parsed.get("requested_hotels", [])),
        ("area", parsed.get("requested_areas", [])),
        ("manage_corp", parsed.get("requested_manage_corps", [])),
        ("brand_child", parsed.get("requested_brand_children", [])),
    ]
    for entity_type, values in candidates:
        if not isinstance(values, list):
            continue
        for value in values:
            text = str(value or "").strip()
            if text:
                terms.append({"term": text, "entity_type": entity_type, "source": "parsed_intent"})
    if not terms:
        query_plan = parsed.get("query_plan") if isinstance(parsed.get("query_plan"), dict) else {}
        label = str(query_plan.get("query_object_label") or "").strip()
        if label:
            terms.append({"term": label, "entity_type": str(query_plan.get("query_object_type") or "scope"), "source": "query_plan"})
    return {
        "status": "proposed" if terms else "not_applicable",
        "reason": reason,
        "question": question,
        "terms": terms,
    }


def build_eval_case_proposal(question: str, parsed: dict | None, reason: str, index: int = 1) -> dict[str, object]:
    parsed = parsed or {}
    query_plan = parsed.get("query_plan") if isinstance(parsed.get("query_plan"), dict) else {}
    metric_code = str(parsed.get("metric_code") or "").strip()
    expected: dict[str, object] = {
        "metric_code": metric_code,
        "compare_mode": parsed.get("compare_mode"),
        "time_scope": parsed.get("time_scope"),
        "requested_hotels": parsed.get("requested_hotels", []),
        "requested_areas": parsed.get("requested_areas", []),
    }
    for key in ("skill_id",):
        if parsed.get(key):
            expected[key] = parsed.get(key)
    for key in ("query_object_type", "query_grain", "analysis_mode"):
        if query_plan.get(key):
            expected[key] = query_plan.get(key)
    return {
        "id": _case_id_from_question(question, index),
        "question": question,
        "time_scope": str(parsed.get("time_scope") or "202601"),
        "reason": reason,
        "expected": {key: value for key, value in expected.items() if value not in (None, "", [])},
        "sql_assertions": {"contains": _metric_sql_contains(metric_code)},
    }


def build_harness_candidates(records: list[dict], limit: int = 10) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    seen_questions: set[str] = set()
    sorted_records = sorted(
        (record for record in records if isinstance(record, dict)),
        key=lambda item: str(item.get("created_at_utc") or ""),
        reverse=True,
    )
    for index, record in enumerate(sorted_records, start=1):
        question = str(record.get("question") or "").strip()
        if not question or question in seen_questions:
            continue
        parsed = record.get("parsed_intent") if isinstance(record.get("parsed_intent"), dict) else {}
        extra = record.get("extra") if isinstance(record.get("extra"), dict) else {}
        metric_code = str(extra.get("metric_code") or parsed.get("metric_code") or "").strip() or None
        if not metric_code:
            continue
        proposal = record.get("eval_case_proposal") if isinstance(record.get("eval_case_proposal"), dict) else {}
        if proposal:
            candidate = {
                **proposal,
                "reason": proposal.get("reason") or record.get("reason"),
                "source_trace_id": record.get("trace_id"),
                "review_status": record.get("review_status", "pending_review"),
                "notes": [
                    f"generated_from_learning_reason={record.get('reason')}",
                    f"generated_at={record.get('created_at_utc')}",
                ],
            }
            candidates.append(candidate)
            seen_questions.add(question)
            if len(candidates) >= limit:
                break
            continue
        expected: dict[str, object] = {
            "metric_code": metric_code,
            "compare_mode": parsed.get("compare_mode"),
            "time_scope": parsed.get("time_scope"),
            "requested_hotels": parsed.get("requested_hotels", []),
            "requested_areas": parsed.get("requested_areas", []),
        }
        if parsed.get("skill_id"):
            expected["skill_id"] = parsed.get("skill_id")
        query_plan = parsed.get("query_plan") if isinstance(parsed.get("query_plan"), dict) else {}
        if query_plan.get("query_object_type"):
            expected["query_object_type"] = query_plan.get("query_object_type")
        if query_plan.get("query_grain"):
            expected["query_grain"] = query_plan.get("query_grain")

        candidate = {
            "id": _case_id_from_question(question, index),
            "question": question,
            "time_scope": str(parsed.get("time_scope") or extra.get("time_scope") or "202601"),
            "reason": record.get("reason"),
            "source_trace_id": record.get("trace_id"),
            "expected": {key: value for key, value in expected.items() if value not in (None, "", [])},
            "sql_assertions": {"contains": _metric_sql_contains(metric_code)},
            "notes": [
                f"generated_from_learning_reason={record.get('reason')}",
                f"generated_at={record.get('created_at_utc')}",
            ],
        }
        candidates.append(candidate)
        seen_questions.add(question)
        if len(candidates) >= limit:
            break
    return candidates


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
        elif len(hotel_text) >= 2 and hotel_text not in precise_like_terms:
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


def build_hotel_count_sql(
    parsed: dict,
    allowed_hotels: list[str] | None = None,
    requested_hotels: list[str] | None = None,
    requested_areas: list[str] | None = None,
) -> str:
    where_clauses = ["status = 1"]

    area_scope = [str(area).strip() for area in (requested_areas or []) if str(area).strip()]
    if area_scope:
        area_clause = ", ".join(sql_literal(area) for area in area_scope)
        where_clauses.append(f"area IN ({area_clause})")

    dimension_filters = [
        ("requested_manage_corps", "manage_corp"),
        ("requested_brand_children", "hotel_brand"),
        ("requested_builders", "Builder"),
        ("requested_brand_levels", "brand_level"),
        ("requested_city_levels", "city_level"),
    ]
    for parsed_key, column in dimension_filters:
        clause = dimension_scope_clause(column, [str(item).strip() for item in parsed.get(parsed_key, []) if str(item).strip()])
        if clause:
            where_clauses.append(clause)

    explicit_hotel_scope = [str(hotel).strip() for hotel in (requested_hotels or []) if str(hotel).strip()]
    if explicit_hotel_scope:
        clauses: list[str] = []
        for hotel in explicit_hotel_scope:
            for candidate in hotel_name_candidates(hotel):
                like_sql = sql_like_literal(candidate)
                clauses.append(f"hotel_fname LIKE {like_sql}")
                clauses.append(f"hotel_sname LIKE {like_sql}")
        if clauses:
            where_clauses.append("(" + " OR ".join(dict.fromkeys(clauses)) + ")")

    hotel_scope = [str(hotel).strip() for hotel in (allowed_hotels or []) if str(hotel).strip()]
    if hotel_scope and hotel_scope != ["ALL"]:
        clauses: list[str] = []
        for hotel in hotel_scope:
            for candidate in hotel_name_candidates(hotel):
                like_sql = sql_like_literal(candidate)
                clauses.append(f"hotel_fname LIKE {like_sql}")
                clauses.append(f"hotel_sname LIKE {like_sql}")
        if clauses:
            where_clauses.append("(" + " OR ".join(dict.fromkeys(clauses)) + ")")

    scope_label = " / ".join(area_scope) if area_scope else "全部范围"
    return f"""
SELECT
  '在营酒店数' AS hotel_name,
  {sql_literal(scope_label)} AS area,
  COUNT(DISTINCT hotel_code) AS actual_value,
  NULL AS compare_value,
  NULL AS diff_value,
  NULL AS diff_rate
FROM {_HOTEL_INFO_SOURCE_TABLE}
WHERE {" AND ".join(where_clauses)}
""".strip()


def build_monthly_hotel_count_sql(
    parsed: dict,
    allowed_hotels: list[str] | None = None,
    requested_hotels: list[str] | None = None,
    requested_areas: list[str] | None = None,
) -> str:
    query_parts = build_overview_query_parts("wddm_dim_overview_cockpit_f")
    time_scope = str(parsed.get("time_scope", "")).strip()
    if not _TIME_SCOPE_RE.fullmatch(time_scope):
        raise HTTPException(status_code=400, detail={"message": "monthly hotel count requires YYYYMM time_scope"})

    where_clauses = [f"o.CALMONTH = {sql_literal(time_scope)}"]
    area_scope = [str(area).strip() for area in (requested_areas or []) if str(area).strip()]
    area_clause = dimension_scope_clause(query_parts["area_filter"], area_scope)
    if area_clause:
        where_clauses.append(area_clause)

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
    hotel_clause = hotel_scope_clause(query_parts["hotel_search_filter"], explicit_hotel_scope)
    if hotel_clause:
        where_clauses.append(hotel_clause)

    hotel_scope = [str(hotel).strip() for hotel in (allowed_hotels or []) if str(hotel).strip()]
    if hotel_scope and hotel_scope != ["ALL"]:
        scope_clause = hotel_scope_clause(query_parts["hotel_search_filter"], hotel_scope)
        if scope_clause:
            where_clauses.append(scope_clause)

    scope_label = " / ".join(area_scope) if area_scope else "全部范围"
    hotel_identity = "COALESCE(s.hotel_name_s, s.hotel_name_f, o.hotel_name)"
    return f"""
SELECT
  '在营酒店数' AS hotel_name,
  {sql_literal(scope_label)} AS area,
  COUNT(DISTINCT {hotel_identity}) AS actual_value,
  NULL AS compare_value,
  NULL AS diff_value,
  NULL AS diff_rate
FROM {query_parts["from_clause"]}
WHERE {" AND ".join(where_clauses)}
""".strip()


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
            "manage_corp_select": "COALESCE(o.manage_corp, s.brand)",
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
        "manage_corp_select": "brand",
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


def _query_plan(parsed: dict) -> dict:
    query_plan = parsed.get("query_plan") if isinstance(parsed.get("query_plan"), dict) else {}
    return query_plan if isinstance(query_plan, dict) else {}


def _analysis_focus(parsed: dict) -> str:
    query_plan = _query_plan(parsed)
    return str(parsed.get("analysis_focus") or query_plan.get("analysis_focus") or "").strip()


def _follow_up_mode(parsed: dict) -> str:
    query_plan = _query_plan(parsed)
    return str(query_plan.get("follow_up_mode") or "").strip()


def _query_bundle_code(parsed: dict) -> str:
    query_plan = _query_plan(parsed)
    bundle_code = (
        query_plan.get("metric_bundle_code")
        or query_plan.get("report_template_code")
        or query_plan.get("analysis_mode")
        or ""
    )
    return str(bundle_code).strip()


def _primary_metric_code(parsed: dict) -> str:
    metric_code = str(parsed.get("metric_code") or "").strip()
    return metric_code or "OWNER_PROFIT"


def _analysis_contract_block_sequence(parsed: dict) -> list[str]:
    query_plan = _query_plan(parsed)
    analysis_contract = query_plan.get("analysis_contract") if isinstance(query_plan.get("analysis_contract"), dict) else {}
    block_sequence = analysis_contract.get("block_sequence") if isinstance(analysis_contract, dict) else []
    if not isinstance(block_sequence, list):
        return []
    blocks: list[str] = []
    for item in block_sequence:
        block = ""
        if isinstance(item, dict):
            block = str(
                item.get("block")
                or item.get("block_code")
                or item.get("code")
                or item.get("name")
                or ""
            ).strip()
        else:
            block = str(item or "").strip()
        block = block.casefold()
        if block and block not in blocks:
            blocks.append(block)
    return blocks


def _analysis_contract_metric_codes(parsed: dict) -> list[str]:
    codes: list[str] = []
    for block in _analysis_contract_block_sequence(parsed):
        for metric_code in _ANALYSIS_CONTRACT_BLOCK_METRICS.get(block, []):
            code = str(metric_code).strip()
            if code and code not in codes:
                codes.append(code)
    return codes


def _query_route(parsed: dict) -> str:
    query_plan = _query_plan(parsed)
    query_object_type = str(query_plan.get("query_object_type") or "").strip()
    query_grain = str(query_plan.get("query_grain") or "").strip()
    if str(parsed.get("intent") or "").strip() == "explain":
        return "explain_detail"
    if str(parsed.get("metric_code") or "").strip() == "OPERATING_HOTEL_COUNT":
        return "hotel_count_snapshot"
    if query_grain == "portfolio":
        if query_plan.get("group_by_dimensions"):
            return "portfolio_group_breakdown"
        if query_object_type in _SCOPE_QUERY_OBJECT_TYPES:
            return "portfolio_scope_overview"
        return "portfolio_overview"
    if query_object_type in _SCOPE_QUERY_OBJECT_TYPES:
        return "scope_detail"
    if query_object_type == "single_hotel" or query_grain == "hotel":
        return "single_hotel_detail"
    return "detail"


def _bundle_metric_codes(parsed: dict) -> list[str]:
    primary = _primary_metric_code(parsed)
    codes: list[str] = []
    if primary:
        codes.append(primary)

    for metric_code in _analysis_contract_metric_codes(parsed):
        if metric_code and metric_code not in codes:
            codes.append(metric_code)
    if len(codes) > (1 if primary else 0):
        return codes

    bundle_code = _query_bundle_code(parsed)
    if not bundle_code:
        bundle_code = "income_overview" if primary == "TOTAL_INCOME" else "operation_overview"
    bundle = load_metric_bundles().get(bundle_code)
    metrics = bundle.get("metrics", []) if isinstance(bundle, dict) else []
    for item in metrics:
        metric_code = str(item).strip()
        if metric_code and metric_code not in codes:
            codes.append(metric_code)
    return codes


def _bundle_metric_profiles(parsed: dict) -> list[dict[str, str]]:
    profiles: list[dict[str, str]] = []
    catalog = load_metric_catalog()
    for metric_code in _bundle_metric_codes(parsed):
        metric = catalog.get(metric_code)
        if not isinstance(metric, dict):
            continue
        context_key = str(metric.get("context_key") or "").strip().lower()
        if not context_key:
            continue
        period_fields = metric.get("period_fields", {})
        period = str(parsed.get("period_type", "MTD")).strip() or "MTD"
        fields = period_fields.get(period) if isinstance(period_fields, dict) else None
        if not isinstance(fields, dict):
            continue
        actual_field = str(fields.get("actual") or "").strip()
        budget_field = str(fields.get("budget") or "").strip()
        last_year_field = str(fields.get("last_year") or "").strip()
        if not actual_field:
            continue
        aggregation = str(metric.get("aggregation") or "").strip().lower()
        if aggregation not in {"sum", "avg"}:
            aggregation = "avg" if metric.get("non_additive") else "sum"
        profiles.append(
            {
                "metric_code": metric_code,
                "context_key": context_key,
                "aggregation": aggregation,
                "actual_field": actual_field,
                "budget_field": budget_field,
                "last_year_field": last_year_field,
            }
        )
    return profiles


def _detail_context_fields(query_parts: dict[str, str], parsed: dict) -> list[tuple[str, str]]:
    route = _query_route(parsed)
    base_fields = [
        ("manage_corp", query_parts["manage_corp_select"]),
        ("brand", query_parts["brand_select"]),
        ("brand_child", query_parts["brand_child_select"]),
        ("brand_level", query_parts["brand_level_select"]),
        ("city_level", query_parts["city_level_select"]),
    ]
    if route == "single_hotel_detail":
        base_fields.extend(
            [
                ("builder", query_parts["builder_select"]),
                ("rooms", query_parts["rooms_select"]),
                ("build_area", query_parts["build_area_select"]),
            ]
        )
    seen_aliases: set[str] = set()
    fields: list[tuple[str, str]] = []
    for alias, expression in base_fields:
        if alias in seen_aliases:
            continue
        fields.append((alias, expression))
        seen_aliases.add(alias)
    return fields


def _metric_field_profile(parsed: dict) -> list[tuple[str, str]]:
    dynamic_fields: list[tuple[str, str]] = []
    seen_aliases: set[str] = set()
    for profile in _bundle_metric_profiles(parsed):
        for suffix, field_name in (
            ("actual", profile.get("actual_field")),
            ("budget", profile.get("budget_field")),
            ("last_year", profile.get("last_year_field")),
        ):
            if not field_name:
                continue
            alias = f"{profile['context_key']}_{suffix}"
            if alias in seen_aliases:
                continue
            dynamic_fields.append((alias, str(field_name)))
            seen_aliases.add(alias)

    extra_fields = [
        ("room_cost_actual", "ROOM_COST_MTD_A"),
        ("admin_expenses_actual", "ADMINI_EXPENSES_MTD_A"),
    ]
    if _query_bundle_code(parsed) not in {"group_dimension_overview", "executive_group_dimension"}:
        extra_fields.extend(
            [
                ("room_profit_actual", "ROOM_PROFIT_MTD_A"),
                ("restaurant_profit_actual", "RESTAURANT_PROFIT_MTD_A"),
                ("rental_rooms_actual", "RENTAL_ROOMS_NUM_MTD_A"),
                ("other_dept_income_actual", "OTHER_DEPT_INCOME_MTD_A"),
                ("other_rate_income_actual", "OTHER_RATE_INCOME_MTD_A"),
            ]
        )
    for alias, field_name in extra_fields:
        if alias not in seen_aliases:
            dynamic_fields.append((alias, field_name))
            seen_aliases.add(alias)
    return dynamic_fields


def _portfolio_metric_fields(parsed: dict) -> list[tuple[str, str]]:
    fields = _metric_field_profile(parsed)
    # Portfolio/group results do not need builder/build-area style dimensions,
    # but they do need enough metric context for narrative sections.
    return fields


def _aggregate_expression(prefix: str, field_name: str, aggregation: str) -> str:
    safe_field = safe_identifier(field_name, "metric field")
    if aggregation == "avg":
        return f"AVG({prefix}{safe_field})"
    return f"SUM({prefix}{safe_field})"


def _portfolio_metric_select_sql(parsed: dict, prefix: str) -> str:
    seen_aliases: set[str] = set()
    parts: list[str] = []
    aggregation_map = {profile["context_key"]: profile["aggregation"] for profile in _bundle_metric_profiles(parsed)}
    for alias, field_name in _portfolio_metric_fields(parsed):
        if alias in seen_aliases:
            continue
        context_key = alias.removesuffix("_actual").removesuffix("_budget").removesuffix("_last_year")
        aggregation = aggregation_map.get(context_key, "sum")
        parts.append(f"{_aggregate_expression(prefix, field_name, aggregation)} AS {alias}")
        seen_aliases.add(alias)
    return ",\n  ".join(parts)


def _analysis_order_clause(parsed: dict, actual_expr: str, compare_expr: str) -> str:
    analysis_focus = _analysis_focus(parsed)
    follow_up_mode = _follow_up_mode(parsed)
    compare_mode = str(parsed.get("compare_mode", "actual")).strip() or "actual"
    if analysis_focus == "yoy_change" or compare_mode == "yoy":
        return f"ORDER BY ABS(({actual_expr} - {compare_expr}) / NULLIF({compare_expr}, 0)) DESC"
    if analysis_focus == "income_structure":
        return f"ORDER BY {actual_expr} DESC"
    if analysis_focus == "profit_cost_efficiency" or follow_up_mode == "driver" or analysis_focus == "driver_analysis":
        return f"ORDER BY ABS({actual_expr} - {compare_expr}) DESC"
    return f"ORDER BY ABS({actual_expr} - {compare_expr}) DESC"


def overview_context_selects(query_parts: dict[str, str], parsed: dict) -> list[str]:
    prefix = f"{query_parts['metric_prefix']}." if query_parts["metric_prefix"] else ""
    dimension_fields = _detail_context_fields(query_parts, parsed)
    metric_fields = _metric_field_profile(parsed)
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
        order_clause = _analysis_order_clause(parsed, actual_field, compare_field)

    context_select_sql = ",\n  ".join(overview_context_selects(query_parts, parsed))
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
'''.strip()


def effective_requested_hotels(parsed: dict) -> list[str]:
    query_plan = parsed.get("query_plan") if isinstance(parsed.get("query_plan"), dict) else {}
    resolved_entities = parsed.get("resolved_entities") if isinstance(parsed.get("resolved_entities"), dict) else {}
    hotel_group = resolved_entities.get("hotel_group") if isinstance(resolved_entities.get("hotel_group"), dict) else {}
    scope_collection = resolved_entities.get("scope_collection") if isinstance(resolved_entities.get("scope_collection"), dict) else {}

    def append_unique(items: list[str], value: object) -> None:
        item = str(value).strip()
        if item and item not in items:
            items.append(item)

    if query_plan.get("query_object_type") == "hotel_group":
        if hotel_group.get("use_group_token_as_filter") is False:
            return []
        members: list[str] = []
        for item in hotel_group.get("member_hotels", []):
            append_unique(members, item)
        append_unique(members, hotel_group.get("group_token"))
        if members:
            return members
    if query_plan.get("query_object_type") in {"area_scope", "manage_corp_scope", "brand_scope", "filtered_scope"}:
        members = [str(item).strip() for item in scope_collection.get("member_hotels", []) if str(item).strip()]
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
    metric_select_sql = _portfolio_metric_select_sql(parsed, prefix)
    return f'''
SELECT
  {sql_literal(object_label)} AS hotel_name,
  {sql_literal(str((parsed.get("query_plan") or {}).get("query_object_type") or "portfolio"))} AS area,
  COUNT(DISTINCT TRIM({query_parts["hotel_select"]})) AS portfolio_member_count,
  {metric_select_sql},
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


def build_dimension_breakdown_sql(
    metric_def: dict,
    parsed: dict,
    dimension: str,
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
    if compare_mode == "yoy":
        compare_source = fields.get("last_year") or fields.get("budget") or fields.get("actual")
    elif compare_mode == "budget":
        compare_source = fields.get("budget") or fields.get("last_year") or fields.get("actual")
    else:
        compare_source = fields.get("budget") or fields.get("last_year") or fields.get("actual")
    compare_field_name = safe_identifier(str(compare_source), "compare field")

    prefix = f"{query_parts['metric_prefix']}." if query_parts["metric_prefix"] else ""
    actual_field = f"{prefix}{actual_field_name}"
    compare_field = f"{prefix}{compare_field_name}"

    dimension_selects = {
        "manage_corp": [("manage_corp", query_parts["manage_corp_select"])],
        "area": [("area", query_parts["area_filter"])],
        "brand_child": [("brand_child", query_parts["brand_child_select"])],
        "manage_corp_area": [
            ("manage_corp", query_parts["manage_corp_select"]),
            ("area", query_parts["area_filter"]),
        ],
    }
    selected_dimensions = dimension_selects.get(dimension)
    if not selected_dimensions:
        raise HTTPException(status_code=400, detail={"message": "unsupported group_by dimension", "dimension": dimension})

    time_scope = str(parsed.get("time_scope", "")).strip()
    if not _TIME_SCOPE_RE.fullmatch(time_scope):
        raise HTTPException(status_code=400, detail={"message": "invalid time_scope", "time_scope": time_scope})

    where_clauses = [f"{query_parts['time_field']} = {sql_literal(time_scope)}"]
    area_scope = [str(area).strip() for area in (requested_areas or []) if str(area).strip()]
    if area_scope:
        where_clauses.append(f"{query_parts['area_filter']} IN ({', '.join(sql_literal(area) for area in area_scope)})")

    for parsed_key, query_key in [
        ("requested_manage_corps", "manage_corp_filter"),
        ("requested_brand_children", "brand_child_filter"),
        ("requested_builders", "builder_filter"),
        ("requested_brand_levels", "brand_level_filter"),
        ("requested_city_levels", "city_level_filter"),
    ]:
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
        where_clauses.append(f"{query_parts['hotel_filter']} IN ({', '.join(sql_literal(hotel) for hotel in hotel_scope)})")

    dimension_sql = ",\n  ".join(
        f"COALESCE(NULLIF(TRIM({expression}), ''), '未标注') AS {alias}"
        for alias, expression in selected_dimensions
    )
    # Group by select positions to avoid alias/name collisions such as manage_corp
    # resolving to a source column instead of the projected expression in DuckDB.
    group_by_sql = ", ".join(str(index) for index in range(1, len(selected_dimensions) + 1))
    metric_select_sql = _portfolio_metric_select_sql(parsed, prefix)

    order_clause = _analysis_order_clause(parsed, f"SUM({actual_field})", f"SUM({compare_field})")
    return f"""
SELECT
  {dimension_sql},
  COUNT(*) AS hotel_count,
  {metric_select_sql},
  SUM({actual_field}) AS actual_value,
  SUM({compare_field}) AS compare_value,
  (SUM({actual_field}) - SUM({compare_field})) AS diff_value,
  (SUM({actual_field}) - SUM({compare_field})) / NULLIF(SUM({compare_field}), 0) AS diff_rate
FROM {query_parts["from_clause"]}
WHERE {" AND ".join(where_clauses)}
GROUP BY {group_by_sql}
{order_clause}
LIMIT 100
""".strip()


def build_dimension_breakdowns(
    metric_def: dict,
    parsed: dict,
    allowed_hotels: list[str] | None = None,
    requested_hotels: list[str] | None = None,
    requested_areas: list[str] | None = None,
) -> dict[str, list[dict]]:
    query_plan = parsed.get("query_plan") if isinstance(parsed.get("query_plan"), dict) else {}
    dimensions = [str(item).strip() for item in query_plan.get("group_by_dimensions", []) if str(item).strip()]
    breakdowns: dict[str, list[dict]] = {}
    for dimension in dimensions:
        sql = build_dimension_breakdown_sql(metric_def, parsed, dimension, allowed_hotels, requested_hotels, requested_areas)
        result = request_json(
            "POST",
            f"{DB_EXECUTOR_SERVICE_URL}/api/v1/db/query",
            {"sql": sql},
            stage=f"db-executor-dimension-breakdown-{dimension}",
        )
        rows = result.get("rows", [])
        breakdowns[dimension] = rows if isinstance(rows, list) else []
    return breakdowns


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
            "best": pick_max(rows, "owner_profit_actual") or pick_max(rows, "operating_profit_actual"),
            "worst": pick_min(rows, "owner_profit_actual") or pick_min(rows, "operating_profit_actual"),
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
    if str(parsed.get("metric_code") or "").strip() == "OPERATING_HOTEL_COUNT":
        actual_value = first_row.get("actual_value")
        area = str(first_row.get("area") or "全部范围").strip() or "全部范围"
        if parsed.get("time_scope_explicit"):
            return f"按 {time_scope} 月度经营数据统计，{area}在运营酒店数为 {actual_value} 家。口径：wddm_dim_overview_cockpit_f 当月有经营数据的酒店去重数。"
        return f"按当前在营口径统计，{area}在营酒店数为 {actual_value} 家。口径：dim_hotel_info.status = 1。"
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


def _external_benchmark_dimensions(parsed: dict) -> list[str]:
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
    return dimensions


def _internal_sample_hint(internal_benchmark: dict[str, object] | None) -> str | None:
    if isinstance(internal_benchmark, dict) and int(internal_benchmark.get("peer_count") or 0) > 0:
        return f"内部已找到 {internal_benchmark.get('scope_used') or '同口径'} 样本 {int(internal_benchmark.get('peer_count') or 0)} 家，可先作为管理口径基准。"
    return None


def _manual_review_benchmark(parsed: dict, internal_benchmark: dict[str, object] | None) -> dict[str, object]:
    sample_hint = _internal_sample_hint(internal_benchmark)
    return {
        "requested": True,
        "provider": "manual_review",
        "status": "awaiting_provider",
        "dimensions": _external_benchmark_dimensions(parsed),
        "message": "你已开启外部行业对标。当前系统会先返回内部经营对标，外部行业数据需按所选 Provider 联网补充后再展示。",
        "disclaimers": [
            "外部行业样本的口径、更新频率和覆盖范围可能与公司内部口径不完全一致，结果需要结合来源说明一起阅读。",
            "建议把外部行业数据作为相对位置参考，不直接替代内部经营考核口径。",
            sample_hint or "若当前问题已有内部同口径样本，建议优先参考内部对标，再决定是否补充外部行业样本。",
        ],
    }


def _uploaded_dataset_benchmark(parsed: dict, internal_benchmark: dict[str, object] | None) -> dict[str, object]:
    sample_hint = _internal_sample_hint(internal_benchmark)
    EXTERNAL_BENCHMARK_DATASET_DIR.mkdir(parents=True, exist_ok=True)
    dataset_files = [path.name for path in sorted(EXTERNAL_BENCHMARK_DATASET_DIR.glob("*")) if path.is_file()]
    ready = bool(dataset_files)
    return {
        "requested": True,
        "provider": "uploaded_dataset",
        "status": "ready_dataset_available" if ready else "dataset_missing",
        "dimensions": _external_benchmark_dimensions(parsed),
        "message": "当前外部对标按本地上传数据集模式执行。" if ready else "尚未在本地检测到可用的外部行业数据集。",
        "datasets": dataset_files[:10],
        "disclaimers": [
            f"已检测到 {len(dataset_files)} 个外部数据文件。" if ready else "请先导入行业月报或市场对标数据文件，再启用该 Provider。",
            sample_hint or "在外部数据集就绪前，建议优先阅读内部对标结果。",
        ],
    }


def _industry_api_benchmark(parsed: dict, internal_benchmark: dict[str, object] | None) -> dict[str, object]:
    sample_hint = _internal_sample_hint(internal_benchmark)
    configured = bool(EXTERNAL_BENCHMARK_API_BASE_URL and EXTERNAL_BENCHMARK_API_KEY)
    return {
        "requested": True,
        "provider": "industry_api",
        "status": "provider_ready" if configured else "provider_not_configured",
        "dimensions": _external_benchmark_dimensions(parsed),
        "message": "外部行业 API 已就绪，可以按当前维度继续拉取对标样本。" if configured else "外部行业 API 尚未配置，当前仍以内部对标为主。",
        "disclaimers": [
            "API 对标结果必须同时展示来源、口径、抓取时间和失败回退状态。",
            sample_hint or "在 API Provider 配置完成前，建议优先参考内部对标。",
        ],
    }


def _web_research_benchmark(parsed: dict, internal_benchmark: dict[str, object] | None) -> dict[str, object]:
    sample_hint = _internal_sample_hint(internal_benchmark)
    return {
        "requested": True,
        "provider": "web_research",
        "status": "ready_for_research",
        "dimensions": _external_benchmark_dimensions(parsed),
        "message": "当前可基于联网搜索补充公开行业摘要，但需要将来源链接、发布日期和口径一起展示。",
        "allowed_domains": EXTERNAL_BENCHMARK_ALLOWED_DOMAINS,
        "disclaimers": [
            "搜索聚合型 Provider 默认只适用于公开行业摘要，不直接等同于可审计的经营样本库。",
            sample_hint or "若内部样本已经足够，建议先以内对标作为管理口径基线。",
        ],
    }


def build_external_benchmark_stub(parsed: dict, internal_benchmark: dict[str, object] | None, enabled: bool) -> dict[str, object] | None:
    if not enabled:
        return None
    provider_map = {
        "manual_review": _manual_review_benchmark,
        "uploaded_dataset": _uploaded_dataset_benchmark,
        "industry_api": _industry_api_benchmark,
        "web_research": _web_research_benchmark,
    }
    provider = EXTERNAL_BENCHMARK_PROVIDER
    result = provider_map.get(provider, _manual_review_benchmark)(parsed, internal_benchmark)
    result["provider"] = provider
    return result


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
    analysis_focus = _analysis_focus(parsed)
    follow_up_mode = _follow_up_mode(parsed)
    query_route = _query_route(parsed)

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
    manage_corps = unique_values(list(parsed.get("requested_manage_corps", [])) + [row.get("manage_corp") for row in display_rows])
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
    if query_route in {"portfolio_group_breakdown", "portfolio_scope_overview", "portfolio_overview"}:
        mode_candidates = [
            {"label": "组合总览", "prompt": "改看组合总览", "active": analysis_mode == "portfolio_overview"},
            {"label": "经营摘要", "prompt": "换成经营摘要", "active": analysis_mode == "management_report"},
            {"label": "归因分析", "prompt": "继续展开原因", "active": analysis_mode == "driver_analysis"},
        ]
    elif query_route == "single_hotel_detail":
        mode_candidates = [
            {"label": "经营摘要", "prompt": "换成经营摘要", "active": analysis_mode == "management_report"},
            {"label": "归因分析", "prompt": "继续展开原因", "active": analysis_mode == "driver_analysis"},
            {"label": "组合总览", "prompt": "改看组合总览", "active": analysis_mode == "portfolio_overview"},
        ]
    else:
        mode_candidates = [
            {"label": "经营摘要", "prompt": "换成经营摘要", "active": analysis_mode == "management_report"},
            {"label": "归因分析", "prompt": "继续展开原因", "active": analysis_mode == "driver_analysis"},
            {"label": "组合总览", "prompt": "改看组合总览", "active": analysis_mode == "portfolio_overview"},
        ]
    mode_items = [item for item in mode_candidates if not item["active"]][:2]

    if analysis_focus == "driver_analysis" or follow_up_mode == "driver":
        focus_candidates = [
            {"label": "收入结构", "prompt": "分析收入结构", "active": False},
            {"label": "利润成本", "prompt": "看利润和成本效率", "active": False},
            {"label": "同比变化", "prompt": "看同比变化", "active": False},
            {"label": "继续原因", "prompt": "继续展开原因", "active": True},
        ]
    elif analysis_focus == "yoy_change":
        focus_candidates = [
            {"label": "继续原因", "prompt": "继续展开原因", "active": False},
            {"label": "收入结构", "prompt": "分析收入结构", "active": False},
            {"label": "利润成本", "prompt": "看利润和成本效率", "active": False},
            {"label": "同比变化", "prompt": "看同比变化", "active": True},
        ]
    elif analysis_focus == "income_structure":
        focus_candidates = [
            {"label": "继续原因", "prompt": "继续展开原因", "active": False},
            {"label": "利润成本", "prompt": "看利润和成本效率", "active": False},
            {"label": "同比变化", "prompt": "看同比变化", "active": False},
            {"label": "收入结构", "prompt": "分析收入结构", "active": True},
        ]
    else:
        focus_candidates = [
            {"label": "收入结构", "prompt": "分析收入结构", "active": analysis_focus == "income_structure"},
            {"label": "利润成本", "prompt": "看利润和成本效率", "active": analysis_focus == "profit_cost_efficiency"},
            {"label": "同比变化", "prompt": "看同比变化", "active": analysis_focus == "yoy_change"},
            {"label": "继续原因", "prompt": "继续展开原因", "active": follow_up_mode == "driver" or analysis_focus == "driver_analysis"},
        ]
    focus_items = [item for item in focus_candidates if not item["active"]][:3]
    groups_by_label = {
        "区域": {"label": "区域", "items": [{"label": item, "prompt": f"只看{item}"} for item in areas]},
        "酒店": {"label": "酒店", "items": [{"label": item, "prompt": f"只看{item}"} for item in hotels]},
        "管理公司": {"label": "管理公司", "items": [{"label": item, "prompt": f"只看{item}"} for item in manage_corps]},
        "月份": {"label": "月份", "items": [{"label": item, "prompt": f"切到{item}"} for item in months]},
        "品牌": {"label": "品牌", "items": [{"label": item, "prompt": f"只看{item}品牌"} for item in brands]},
        "口径": {"label": "口径", "items": [{"label": item["label"], "prompt": item["prompt"]} for item in compare_items]},
        "分析方式": {"label": "分析方式", "items": [{"label": item["label"], "prompt": item["prompt"]} for item in mode_items]},
        "进一步": {"label": "进一步", "items": [{"label": item["label"], "prompt": item["prompt"]} for item in focus_items]},
    }

    object_type = str(query_plan.get("query_object_type") or "").strip()
    requested_hotels = parsed.get("requested_hotels") if isinstance(parsed.get("requested_hotels"), list) else []
    requested_areas = parsed.get("requested_areas") if isinstance(parsed.get("requested_areas"), list) else []
    is_single_hotel = object_type == "single_hotel" or (len(requested_hotels) == 1 and query_plan.get("query_grain") != "portfolio")
    is_area_scope = object_type == "area_scope" or bool(requested_areas)
    is_portfolio = query_plan.get("query_grain") == "portfolio" or object_type in {"hotel_group", "manage_corp_scope", "brand_scope"}

    if is_single_hotel:
        template = ["月份", "口径", "进一步", "分析方式", "品牌", "区域", "管理公司"]
    elif is_portfolio:
        template = ["管理公司", "区域", "品牌", "酒店", "进一步", "分析方式", "月份", "口径"]
    elif is_area_scope and not is_single_hotel:
        template = ["酒店", "品牌", "月份", "进一步", "分析方式", "口径", "管理公司"]
    else:
        template = ["月份", "口径", "进一步", "分析方式", "管理公司", "区域", "酒店", "品牌"]

    ordered_groups = [groups_by_label[label] for label in template if groups_by_label.get(label, {}).get("items")]
    remaining_groups = [
        group for label, group in groups_by_label.items()
        if label not in template and group.get("items")
    ]
    return ordered_groups + remaining_groups


def build_follow_up_prompts(parsed: dict, rows: list[dict], portfolio_breakdown: list[dict]) -> list[dict[str, object]]:
    display_rows = portfolio_breakdown or rows
    query_plan = parsed.get("query_plan") if isinstance(parsed.get("query_plan"), dict) else {}
    query_route = _query_route(parsed)
    analysis_focus = _analysis_focus(parsed)
    follow_up_mode = _follow_up_mode(parsed)
    compare_mode = str(parsed.get("compare_mode") or "actual").strip()

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
            if str(row.get("hotel_name") or "").strip() and str(row.get("hotel_name") or "").strip() != str(query_plan.get("query_object_label") or "").strip()
        ]
    )
    brands = unique_values(list(parsed.get("requested_brand_children", [])) + [row.get("brand_child") for row in display_rows])
    manage_corps = unique_values(list(parsed.get("requested_manage_corps", [])) + [row.get("manage_corp") for row in display_rows])

    prompts: list[dict[str, object]] = []
    if analysis_focus == "driver_analysis" or follow_up_mode == "driver":
        prompts.append({"label": "继续原因", "prompt": "继续展开原因"})
    elif analysis_focus == "income_structure":
        prompts.append({"label": "收入结构", "prompt": "分析收入结构"})
    elif analysis_focus == "profit_cost_efficiency":
        prompts.append({"label": "利润成本", "prompt": "看利润和成本效率"})
    elif analysis_focus == "yoy_change" or compare_mode == "yoy":
        prompts.append({"label": "同比变化", "prompt": "看同比变化"})

    if query_route in {"portfolio_group_breakdown", "portfolio_scope_overview", "portfolio_overview"}:
        for label, values, suffix in (
            ("管理公司", manage_corps, ""),
            ("区域", areas, ""),
            ("品牌", brands, "品牌"),
            ("酒店", hotels, ""),
        ):
            if values:
                prompt = f"只看{values[0]}{suffix}"
                prompts.append({"label": label, "prompt": prompt})
    elif query_route in {"scope_detail", "single_hotel_detail"}:
        for label, values, suffix in (
            ("酒店", hotels, ""),
            ("区域", areas, ""),
            ("品牌", brands, "品牌"),
            ("管理公司", manage_corps, ""),
        ):
            if values:
                prompt = f"只看{values[0]}{suffix}"
                prompts.append({"label": label, "prompt": prompt})

    seen: set[str] = set()
    ordered: list[dict[str, object]] = []
    for item in prompts:
        prompt_text = str(item.get("prompt") or "").strip()
        if not prompt_text or prompt_text in seen:
            continue
        seen.add(prompt_text)
        ordered.append(item)
        if len(ordered) >= 4:
            break
    return ordered


def _narrative_brief_from_explanation(explanation: dict | None, fallback_summary: str) -> str:
    explanation = explanation if isinstance(explanation, dict) else {}
    management_summary = explanation.get("management_summary") if isinstance(explanation.get("management_summary"), list) else []
    for item in management_summary:
        text = str(item or "").strip()
        if text:
            return text
    summary = str(explanation.get("summary") or "").strip()
    if summary:
        return summary
    report_sections = explanation.get("report_sections") if isinstance(explanation.get("report_sections"), list) else []
    for section in report_sections:
        if not isinstance(section, dict):
            continue
        content = str(section.get("content") or "").strip()
        if content:
            return content
    fallback_text = str(fallback_summary or "").strip()
    if fallback_text:
        return fallback_text
    return "当前没有可用的结构化解释结果。"


def _analysis_blocks_from_explanation(explanation: dict | None, fallback_summary: str) -> list[dict[str, object]]:
    explanation = explanation if isinstance(explanation, dict) else {}
    blocks: list[dict[str, object]] = []
    report_sections = explanation.get("report_sections") if isinstance(explanation.get("report_sections"), list) else []
    for index, section in enumerate(report_sections, start=1):
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or f"分析块{index}").strip() or f"分析块{index}"
        content = str(section.get("content") or "").strip()
        if not content:
            continue
        block: dict[str, object] = {
            "block_id": f"section_{index}",
            "block_type": "report_section",
            "title": title,
            "content": content,
            "source": "explanation.report_sections",
        }
        if section.get("items") is not None:
            block["items"] = section.get("items")
        blocks.append(block)
    if blocks:
        return blocks

    management_summary = explanation.get("management_summary") if isinstance(explanation.get("management_summary"), list) else []
    for index, item in enumerate(management_summary, start=1):
        text = str(item or "").strip()
        if not text:
            continue
        blocks.append(
            {
                "block_id": f"management_summary_{index}",
                "block_type": "management_summary",
                "title": f"管理层摘要{index}",
                "content": text,
                "source": "explanation.management_summary",
            }
        )
    if blocks:
        return blocks

    narrative_brief = _narrative_brief_from_explanation(explanation, fallback_summary)
    return [
        {
            "block_id": "summary",
            "block_type": "fallback_summary",
            "title": "经营摘要",
            "content": narrative_brief,
            "source": "fallback",
        }
    ]


def build_trace_events(
    *,
    timings: dict[str, int],
    parsed: dict,
    sql_plan: dict,
    explanation_payload: dict,
    warnings: list[str],
) -> list[dict[str, object]]:
    query_plan = parsed.get("query_plan") if isinstance(parsed.get("query_plan"), dict) else {}
    analysis_agent = explanation_payload.get("analysis_agent") if isinstance(explanation_payload.get("analysis_agent"), dict) else {}
    narrative_agent = explanation_payload.get("narrative_agent") if isinstance(explanation_payload.get("narrative_agent"), dict) else {}
    guardrail = narrative_agent.get("guardrail") if isinstance(narrative_agent.get("guardrail"), dict) else {}
    events: list[dict[str, object]] = [
        {
            "stage": "parse_intent",
            "status": "completed",
            "duration_ms": int(timings.get("semantic_ms") or 0),
            "metadata": {
                "semantic_draft_source": _semantic_draft_stats(parsed)[0],
                "semantic_draft_candidate_count": _semantic_draft_stats(parsed)[1],
                "route_mode": parsed.get("route_mode"),
                "conversation_action": parsed.get("conversation_action"),
                "clarification_type": parsed.get("clarification_type"),
                "analysis_mode": query_plan.get("analysis_mode"),
                "analysis_focus": query_plan.get("analysis_focus"),
                "metric_bundle_code": query_plan.get("metric_bundle_code"),
                "report_template_code": query_plan.get("report_template_code"),
            },
        },
        {
            "stage": "sql_guardrail",
            "status": "completed" if sql_plan.get("safe", True) else "blocked",
            "duration_ms": int(timings.get("sql_guardrail_ms") or 0),
            "metadata": {
                "safe": bool(sql_plan.get("safe", True)),
                "warnings": sql_plan.get("warnings", []),
            },
        },
        {
            "stage": "execute_sql",
            "status": "completed",
            "duration_ms": int(timings.get("db_executor_ms") or 0),
            "metadata": {},
        },
        {
            "stage": "build_analysis_blocks",
            "status": "completed" if analysis_agent else "fallback",
            "duration_ms": int(timings.get("explanation_ms") or 0),
            "metadata": {
                "agent": analysis_agent.get("agent"),
                "contract_version": analysis_agent.get("contract_version"),
            },
        },
        {
            "stage": "build_narrative_brief",
            "status": "completed" if narrative_agent else "fallback",
            "duration_ms": int(timings.get("explanation_ms") or 0),
            "metadata": {
                "agent": narrative_agent.get("agent"),
                "contract_version": narrative_agent.get("contract_version"),
                "guardrail_status": guardrail.get("status"),
            },
        },
    ]
    if warnings:
        events.append(
            {
                "stage": "pipeline_warnings",
                "status": "warning",
                "duration_ms": 0,
                "metadata": {"warnings": warnings},
            }
        )
    return events


def expected_portfolio_member_count(parsed: dict) -> int:
    query_plan = parsed.get("query_plan") if isinstance(parsed.get("query_plan"), dict) else {}
    try:
        planned_count = int(query_plan.get("resolved_hotel_count") or 0)
    except (TypeError, ValueError):
        planned_count = 0
    if planned_count > 0:
        return planned_count

    resolved_entities = parsed.get("resolved_entities") if isinstance(parsed.get("resolved_entities"), dict) else {}
    for key in ("hotel_group", "scope_collection"):
        entity = resolved_entities.get(key) if isinstance(resolved_entities.get(key), dict) else {}
        try:
            member_count = int(entity.get("member_count") or 0)
        except (TypeError, ValueError):
            member_count = 0
        if member_count > 0:
            return member_count
    return 0


def incomplete_portfolio_quality(parsed: dict, rows: list[dict]) -> dict[str, object] | None:
    query_plan = parsed.get("query_plan") if isinstance(parsed.get("query_plan"), dict) else {}
    if query_plan.get("query_grain") != "portfolio":
        return None
    expected_count = expected_portfolio_member_count(parsed)
    if expected_count <= 0 or not rows or not isinstance(rows[0], dict):
        return None
    try:
        actual_count = int(rows[0].get("portfolio_member_count") or 0)
    except (TypeError, ValueError):
        actual_count = 0
    if actual_count == expected_count:
        return None
    return {
        "status": "mismatch",
        "expected_hotel_count": expected_count,
        "actual_hotel_count": actual_count,
        "policy": "suppress_incomplete_aggregate",
    }


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
        {
            "question": payload.question,
            "time_scope": payload.context.time_scope,
            "conversation_context": payload.context.conversation_context,
        },
        stage="semantic",
    )
    if payload.context.analysis_focus:
        parsed["analysis_focus"] = payload.context.analysis_focus
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
            extra={
                "clarification_options": clarification_options,
                **_learning_metadata(parsed, external_benchmark_requested=payload.context.external_benchmark),
            },
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
    metric_source_table = safe_identifier(str(metric_def.get("source_table", "wddm_dim_overview_cockpit_f")), "source_table")
    use_monthly_hotel_count = (
        parsed.get("metric_code") == "OPERATING_HOTEL_COUNT"
        and bool(parsed.get("time_scope_explicit"))
    )
    source_table = "wddm_dim_overview_cockpit_f" if use_monthly_hotel_count else metric_source_table
    query_route = _query_route(parsed)
    sql_text = (
        build_monthly_hotel_count_sql(
            parsed,
            auth_scope.get("allowed_hotels", []),
            resolved_requested_hotels,
            parsed.get("requested_areas", []),
        )
        if use_monthly_hotel_count
        else build_hotel_count_sql(
            parsed,
            auth_scope.get("allowed_hotels", []),
            resolved_requested_hotels,
            parsed.get("requested_areas", []),
        )
        if metric_source_table == _HOTEL_INFO_SOURCE_TABLE
        else build_explain_sql(
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
        if query_route.startswith("portfolio")
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
            "hotel_column": "hotel_fname" if source_table == _HOTEL_INFO_SOURCE_TABLE else auth_scope.get("sql_scope", {}).get("hotel_column", "HOTEL_NAME_s"),
            "area_column": auth_scope.get("sql_scope", {}).get("area_column", "area"),
            "require_time_filter": source_table != _HOTEL_INFO_SOURCE_TABLE,
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
    if query_route.startswith("portfolio") and rows:
        first_portfolio_row = rows[0] if isinstance(rows[0], dict) else {}
        if int(first_portfolio_row.get("portfolio_member_count") or 0) <= 0:
            rows = []
    data_quality = incomplete_portfolio_quality(parsed, rows)
    if data_quality:
        expected_count = int(data_quality["expected_hotel_count"])
        actual_count = int(data_quality["actual_hotel_count"])
        warnings.append("data_incomplete_suppressed")
        summary = (
            f"当前数据完整性未通过：应覆盖 {expected_count} 家酒店，当前账期取到 {actual_count} 家。"
            "为避免错误汇总，已停止展示经营汇总。"
        )
        explanation_payload = {
            "summary": summary,
            "management_summary": [summary],
            "risks": ["数据完整性未通过校验，本次不展示经营指标、排名或汇总数。"],
            "suggestions": ["请先核对本月数据同步范围，再重新发起全量汇总。"],
            "report_sections": [{"title": "数据完整性", "content": summary}],
        }
        timings["explanation_ms"] = 0
        timings["audit_ms"] = 0
        timings["total_ms"] = elapsed_ms(request_started)
        trace_events = build_trace_events(
            timings=timings,
            parsed=parsed,
            sql_plan=sql_plan,
            explanation_payload=explanation_payload,
            warnings=warnings,
        )
        return {
            "trace_id": trace_id,
            "summary": summary,
            "narrative_brief": summary,
            "analysis_blocks": _analysis_blocks_from_explanation(explanation_payload, summary),
            "trace_events": trace_events,
            "parsed_intent": parsed,
            "metric_definition": metric_def,
            "sql_plan": sql_plan,
            "auth_scope": auth_scope,
            "data_source": data_source,
            "data_points": [],
            "portfolio_member_count": None,
            "portfolio_breakdown": [],
            "portfolio_outliers": None,
            "dimension_breakdowns": {},
            "query_route": query_route,
            "quick_filters": [],
            "follow_up_prompts": [],
            "internal_benchmark": None,
            "external_benchmark": None,
            "external_benchmark_requested": payload.context.external_benchmark,
            "explanation": explanation_payload,
            "data_quality": data_quality,
            "warnings": warnings,
            "performance": timings,
        }
    row_count = len(rows)
    data_quality = {"status": "complete"} if query_route.startswith("portfolio") else {"status": "not_applicable"}
    internal_benchmark = None
    portfolio_breakdown: list[dict] = []
    portfolio_outliers: dict[str, dict[str, object]] | None = None
    dimension_breakdowns: dict[str, list[dict]] = {}
    if query_route.startswith("portfolio"):
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
        if query_plan.get("group_by_dimensions"):
            try:
                dimension_breakdowns = build_dimension_breakdowns(
                    metric_def,
                    parsed,
                    auth_scope.get("allowed_hotels", []),
                    resolved_requested_hotels,
                    parsed.get("requested_areas", []),
                )
            except HTTPException as exc:
                warnings.append(f"dimension breakdown fallback: {exc.detail}")
    if parsed.get("intent") != "explain" and rows and not query_route.startswith("portfolio"):
        try:
            internal_benchmark = build_internal_benchmark(rows, metric_def, parsed)
        except HTTPException as exc:
            warnings.append(f"benchmark fallback: {exc.detail}")
    external_benchmark = build_external_benchmark_stub(parsed, internal_benchmark, payload.context.external_benchmark)

    summary = summarize_rows({**parsed, "metric_name": metric_def.get("name_cn")}, rows)
    if parsed.get("metric_code") == "OPERATING_HOTEL_COUNT":
        timings["explanation_ms"] = 0
        explanation_payload = {
            "summary": summary,
            "management_summary": [summary, "该统计直接来源于 dim_hotel_info，不受前端展示条数影响。"],
            "risks": ["如需更细口径，可继续限定区域、品牌、管理公司或具体酒店范围。"],
            "suggestions": ["可以继续追问：只看华南区在营酒店数、只看万豪品牌在营酒店数。"],
            "report_sections": [
                {"title": "统计口径", "content": "当前按 dim_hotel_info.status = 1 统计在营酒店数。"},
                {"title": "结果", "content": summary},
            ],
        }
    else:
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
                    "dimension_breakdowns": dimension_breakdowns,
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

    trace_events = build_trace_events(
        timings=timings,
        parsed=parsed,
        sql_plan=sql_plan,
        explanation_payload=explanation_payload,
        warnings=warnings,
    )
    query_plan = parsed.get("query_plan") if isinstance(parsed.get("query_plan"), dict) else {}
    analysis_contract = query_plan.get("analysis_contract") if isinstance(query_plan.get("analysis_contract"), dict) else {}
    narrative_agent = explanation_payload.get("narrative_agent") if isinstance(explanation_payload.get("narrative_agent"), dict) else {}
    guardrail = narrative_agent.get("guardrail") if isinstance(narrative_agent.get("guardrail"), dict) else {}

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
            analysis_contract=analysis_contract,
            analysis_blocks=_analysis_blocks_from_explanation(explanation_payload, summary),
            guardrail=guardrail,
            trace_events=trace_events,
            extra=_learning_metadata(
                parsed,
                external_benchmark_requested=payload.context.external_benchmark,
                external_benchmark=external_benchmark,
                internal_benchmark=internal_benchmark,
            ),
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
    follow_up_prompts = build_follow_up_prompts(parsed, rows, portfolio_breakdown)
    analysis_blocks = _analysis_blocks_from_explanation(explanation_payload, summary)
    narrative_brief = _narrative_brief_from_explanation(explanation_payload, summary)

    return {
        "trace_id": trace_id,
        "summary": summary,
        "narrative_brief": narrative_brief,
        "analysis_blocks": analysis_blocks,
        "trace_events": trace_events,
        "parsed_intent": parsed,
        "metric_definition": metric_def,
        "sql_plan": sql_plan,
        "auth_scope": auth_scope,
        "data_source": data_source,
        "data_points": rows,
        "portfolio_member_count": portfolio_member_count,
        "portfolio_breakdown": portfolio_breakdown,
        "portfolio_outliers": portfolio_outliers,
        "dimension_breakdowns": dimension_breakdowns,
        "query_route": query_route,
        "quick_filters": quick_filters,
        "follow_up_prompts": follow_up_prompts,
        "internal_benchmark": internal_benchmark,
        "external_benchmark": external_benchmark,
        "external_benchmark_requested": payload.context.external_benchmark,
        "explanation": explanation_payload,
        "data_quality": data_quality,
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
    report_summary = str(explanation.get("summary") or result.get("summary") or "")
    if sections:
        report_summary = f"已生成经营摘要：{sections[0].get('content') or report_summary}"
    return {
        "trace_id": result.get("trace_id"),
        "summary": report_summary,
        "narrative_brief": result.get("narrative_brief"),
        "analysis_blocks": result.get("analysis_blocks", []),
        "report_sections": sections,
        "report_markdown": "\n\n".join(markdown_lines),
        "source_query": {
            "question": payload.question,
            "parsed_intent": result.get("parsed_intent", {}),
        },
        "warnings": result.get("warnings", []),
    }
