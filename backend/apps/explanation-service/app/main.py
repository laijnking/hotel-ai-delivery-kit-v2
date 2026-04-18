import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import BaseModel
import yaml

app = FastAPI(title="explanation-service")
REPORT_TEMPLATE_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "report_templates.yaml"
METRIC_BUNDLE_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "metric_bundles.yaml"
LLM_BASE_URL = os.getenv("QWEN_API_BASE_URL", "").strip()
LLM_API_KEY = os.getenv("QWEN_API_KEY", "").strip()
FAST_LLM_MODEL = os.getenv("QWEN_FAST_MODEL", "").strip() or os.getenv("QWEN_MODEL", "").strip()
DEEP_LLM_MODEL = os.getenv("QWEN_DEEP_MODEL", "").strip() or os.getenv("QWEN_MODEL", "").strip()
LLM_TIMEOUT = float(os.getenv("QWEN_TIMEOUT", "12"))
LLM_EXPLANATION_POLICY = os.getenv("QWEN_EXPLANATION_POLICY", "off").strip().lower()


class Req(BaseModel):
    question: str
    parsed_intent: dict[str, Any]
    rows: list[dict[str, Any]]
    portfolio_breakdown: list[dict[str, Any]] = []
    portfolio_outliers: dict[str, Any] | None = None
    dimension_breakdowns: dict[str, list[dict[str, Any]]] = {}
    peer_benchmark: dict[str, Any] | None = None
    external_benchmark_requested: bool = False


class ReportReq(BaseModel):
    question: str
    parsed_intent: dict[str, Any]
    rows: list[dict[str, Any]]
    portfolio_breakdown: list[dict[str, Any]] = []
    portfolio_outliers: dict[str, Any] | None = None
    dimension_breakdowns: dict[str, list[dict[str, Any]]] = {}
    peer_benchmark: dict[str, Any] | None = None
    external_benchmark_requested: bool = False


@app.get("/health")
def health():
    return {
        "status": "ok",
        "llm_enabled": llm_enabled(),
        "fast_model": FAST_LLM_MODEL or None,
        "deep_model": DEEP_LLM_MODEL or None,
    }


def llm_enabled() -> bool:
    return bool(LLM_BASE_URL and LLM_API_KEY and DEEP_LLM_MODEL)


@lru_cache(maxsize=1)
def load_report_templates() -> dict[str, dict]:
    if not REPORT_TEMPLATE_CONFIG.exists():
        return {}
    with open(REPORT_TEMPLATE_CONFIG, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    templates = data.get("templates", {}) if isinstance(data, dict) else {}
    return templates if isinstance(templates, dict) else {}


@lru_cache(maxsize=1)
def load_metric_bundles() -> dict[str, dict]:
    if not METRIC_BUNDLE_CONFIG.exists():
        return {}
    with open(METRIC_BUNDLE_CONFIG, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    bundles = data.get("bundles", {}) if isinstance(data, dict) else {}
    return bundles if isinstance(bundles, dict) else {}


@lru_cache(maxsize=1)
def load_focus_profiles() -> dict[str, dict]:
    if not METRIC_BUNDLE_CONFIG.exists():
        return {}
    with open(METRIC_BUNDLE_CONFIG, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    profiles = data.get("focus_profiles", {}) if isinstance(data, dict) else {}
    return profiles if isinstance(profiles, dict) else {}


def _analysis_focus_code(parsed_intent: dict[str, Any] | None) -> str:
    if not isinstance(parsed_intent, dict):
        return ""
    return str(parsed_intent.get("analysis_focus") or "").strip()


def _focus_profile(parsed_intent: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    focus = _analysis_focus_code(parsed_intent)
    if not focus:
        return "", {}
    profile = load_focus_profiles().get(focus)
    if not isinstance(profile, dict):
        profile = {}
    return focus, profile


def _resolve_template_bundle(parsed_intent: dict[str, Any] | None, row: dict[str, Any] | None = None) -> tuple[str, dict[str, Any], str]:
    query_plan = parsed_intent.get("query_plan") if isinstance(parsed_intent, dict) and isinstance(parsed_intent.get("query_plan"), dict) else {}
    bundle_code = str(query_plan.get("metric_bundle_code") or "").strip()
    if not bundle_code:
        analysis_mode = str(query_plan.get("analysis_mode") or "").strip()
        query_grain = str(query_plan.get("query_grain") or "").strip()
        if analysis_mode == "group_by_dimension_report":
            bundle_code = "group_dimension_overview"
        elif query_grain == "hotel":
            bundle_code = "hotel_snapshot"
        elif query_grain == "portfolio":
            bundle_code = "operation_overview"
        elif row and _has_overview_context(row):
            bundle_code = "operation_overview"
        else:
            bundle_code = "operation_overview"
    bundle = load_metric_bundles().get(bundle_code)
    if not isinstance(bundle, dict):
        bundle = {}
    template_code = str(query_plan.get("report_template_code") or "").strip()
    return bundle_code, bundle, template_code


def _bundle_summary_title(bundle_code: str, template_code: str) -> str:
    bundle = load_metric_bundles().get(bundle_code)
    if isinstance(bundle, dict):
        title = str(bundle.get("summary_section_title") or "").strip()
        if title:
            return title
    if template_code == "executive_group_dimension":
        return "分维度经营摘要"
    if template_code == "executive_hotel_snapshot":
        return "单店经营摘要"
    if template_code == "executive_portfolio":
        return "组合经营摘要"
    return {
        "group_dimension_overview": "分维度经营摘要",
        "hotel_snapshot": "单店经营摘要",
        "income_overview": "收入经营摘要",
    }.get(bundle_code, "经营总览")


def _focus_summary_lead(analysis_focus: str, focus_profile: dict[str, Any]) -> str:
    if isinstance(focus_profile, dict):
        lead = str(focus_profile.get("summary_lead") or "").strip()
        if lead:
            return lead
    fallback = {
        "management_report": "本次按管理层摘要整理，先看整体，再下钻结构、利润和成本，尽量不先下结论。",
        "portfolio_overview": "本次按组合视角观察，先看整体，再看结构、利润和成本，最后再决定是否继续下钻。",
        "driver_analysis": "本次围绕结果差异继续展开原因，先看驱动项，再判断变化来自收入、利润还是成本。",
        "income_structure": "本次先拆收入结构，不先判断好坏，先看总收入、客房收入、餐饮/宴会收入及其占比。",
        "profit_cost_efficiency": "本次把利润与成本放在一起看，先判断收入改善有没有转成利润，再看成本是否抵消收益。",
        "yoy_change": "本次切到去年同期观察，先确认变化方向，再拆是基数变化、结构变化还是成本变化。",
        "dimension_comparison": "本次按维度比较，先看管理公司、区域、品牌的相对位置，再拆收入、利润和成本。",
        "scope_refinement": "本次只是收窄观察范围，先确认口径一致，再继续看变化。",
        "scope_inventory": "本次只核对在营酒店数量，不对经营优劣做判断。",
        "metric_snapshot": "本次按单项指标快照观察，先看当前值和对比值，再判断差异来自哪一层。",
    }
    return fallback.get(analysis_focus, "")


def _bundle_summary_preamble(bundle: dict[str, Any], fallback: str) -> str:
    text = str(bundle.get("summary_preamble") or "").strip() if isinstance(bundle, dict) else ""
    return text or fallback


def _bundle_follow_up_text(bundle: dict[str, Any], fallback: str, focus_profile: dict[str, Any] | None = None) -> str:
    prompts = None
    if isinstance(focus_profile, dict):
        prompts = focus_profile.get("follow_up_prompts")
    if not isinstance(prompts, list):
        prompts = bundle.get("follow_up_prompts") if isinstance(bundle, dict) else None
    if isinstance(prompts, list):
        items = [str(item).strip() for item in prompts if str(item).strip()]
        if items:
            return "；".join(items[:3]) + "。"
    return fallback


def _analysis_contract(parsed_intent: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(parsed_intent, dict):
        return {}
    contract = parsed_intent.get("analysis_contract")
    if not isinstance(contract, dict):
        query_plan = parsed_intent.get("query_plan") if isinstance(parsed_intent.get("query_plan"), dict) else {}
        contract = query_plan.get("analysis_contract") if isinstance(query_plan, dict) else {}
    return contract if isinstance(contract, dict) else {}


def _analysis_contract_block_sequence(parsed_intent: dict[str, Any] | None, template_code: str) -> list[str]:
    contract = _analysis_contract(parsed_intent)
    sequence = contract.get("block_sequence")
    if not isinstance(sequence, list):
        return []
    section_titles = _analysis_block_titles(template_code)
    title_to_block: dict[str, str] = {}
    for block_type, titles in section_titles.items():
        for title in titles:
            title_to_block[str(title)] = block_type
    aliases = {
        "scope_overview": "scope_overview",
        "分析范围": "scope_overview",
        "dimension_summary": "dimension_summary",
        "分维度经营摘要": "dimension_summary",
        "管理公司/区域汇总": "dimension_summary",
        "income_quality": "income_quality",
        "收入质量": "income_quality",
        "room_efficiency": "room_efficiency",
        "客房效率": "room_efficiency",
        "profit_quality": "profit_quality",
        "利润质量": "profit_quality",
        "cost_efficiency": "cost_efficiency",
        "成本效率": "cost_efficiency",
        "benchmark": "benchmark",
        "横向对标": "benchmark",
        "横向对标与继续追问": "benchmark",
        "portfolio_watchlist": "portfolio_watchlist",
        "重点酒店与梯队": "portfolio_watchlist",
    }
    normalized: list[str] = []
    for item in sequence:
        block_type = ""
        if isinstance(item, str):
            candidate = item.strip()
            block_type = aliases.get(candidate, "") or title_to_block.get(candidate, "")
        elif isinstance(item, dict):
            for key in ("block_type", "type", "code", "title", "section"):
                candidate = str(item.get(key) or "").strip()
                if not candidate:
                    continue
                block_type = aliases.get(candidate, "") or title_to_block.get(candidate, "")
                if block_type:
                    break
        if block_type and block_type not in normalized:
            normalized.append(block_type)
    return normalized


def _analysis_block_order(parsed_intent: dict[str, Any] | None, template_code: str) -> list[str]:
    contract_sequence = _analysis_contract_block_sequence(parsed_intent, template_code)
    if contract_sequence:
        return contract_sequence
    templates = load_report_templates()
    template = templates.get(template_code) if isinstance(template_code, str) else None
    analysis_focus = _analysis_focus_code(parsed_intent)
    if isinstance(template, dict):
        order_cfg = template.get("analysis_block_order", [])
        if isinstance(order_cfg, dict):
            for key in (analysis_focus, "default"):
                candidate = order_cfg.get(key)
                if isinstance(candidate, list) and candidate:
                    return [str(item).strip() for item in candidate if str(item).strip()]
        elif isinstance(order_cfg, list) and order_cfg:
            return [str(item).strip() for item in order_cfg if str(item).strip()]
    return {
        "executive_group_dimension": [
            "scope_overview",
            "dimension_summary",
            "income_quality",
            "room_efficiency",
            "profit_quality",
            "cost_efficiency",
            "benchmark",
        ],
        "executive_portfolio": [
            "scope_overview",
            "portfolio_watchlist",
            "income_quality",
            "room_efficiency",
            "profit_quality",
            "cost_efficiency",
            "benchmark",
        ],
        "executive_hotel_snapshot": [
            "scope_overview",
            "income_quality",
            "room_efficiency",
            "profit_quality",
            "cost_efficiency",
            "benchmark",
        ],
    }.get(template_code, [
        "scope_overview",
        "income_quality",
        "room_efficiency",
        "profit_quality",
        "cost_efficiency",
        "benchmark",
    ])


def _analysis_block_titles(template_code: str) -> dict[str, list[str]]:
    if template_code == "executive_group_dimension":
        return {
            "scope_overview": ["分析范围"],
            "dimension_summary": ["分维度经营摘要", "管理公司/区域汇总"],
            "income_quality": ["收入质量"],
            "room_efficiency": ["客房效率"],
            "profit_quality": ["利润质量"],
            "cost_efficiency": ["成本效率"],
            "benchmark": ["横向对标与继续追问", "横向对标"],
            "portfolio_watchlist": ["重点酒店与梯队"],
        }
    if template_code == "executive_portfolio":
        return {
            "scope_overview": ["分析范围"],
            "dimension_summary": ["分维度经营摘要", "管理公司/区域汇总"],
            "income_quality": ["收入质量"],
            "room_efficiency": ["客房效率"],
            "profit_quality": ["利润质量"],
            "cost_efficiency": ["成本效率"],
            "benchmark": ["横向对标与继续追问", "横向对标"],
            "portfolio_watchlist": ["重点酒店与梯队"],
        }
    return {
        "scope_overview": ["分析范围"],
        "dimension_summary": ["分维度经营摘要", "管理公司/区域汇总"],
        "income_quality": ["收入质量"],
        "room_efficiency": ["客房效率"],
        "profit_quality": ["利润质量"],
        "cost_efficiency": ["成本效率"],
        "benchmark": ["横向对标与继续追问", "横向对标"],
        "portfolio_watchlist": ["重点酒店与梯队"],
    }


def _analysis_block_label(block_type: str) -> str:
    return {
        "scope_overview": "分析范围",
        "dimension_summary": "分维度经营摘要",
        "income_quality": "收入质量",
        "room_efficiency": "客房效率",
        "profit_quality": "利润质量",
        "cost_efficiency": "成本效率",
        "benchmark": "横向对标",
        "portfolio_watchlist": "重点酒店与梯队",
    }.get(block_type, block_type)


def _analysis_block_metrics(block_type: str) -> list[str]:
    return _analysis_block_fact_spec(block_type).get("metrics_used", [])


def _analysis_block_evidence_fields(block_type: str) -> list[str]:
    return _analysis_block_fact_spec(block_type).get("evidence_fields", [])


def _analysis_block_data_status(block_type: str, row: dict[str, Any], content: str) -> str:
    if not content:
        return "missing"
    unavailable_markers = ("未包含", "暂不能", "暂不", "不足", "N/A", "当前结果未", "当前未")
    if any(marker in content for marker in unavailable_markers):
        return "partial"
    if block_type == "dimension_summary":
        breakdowns = row.get("dimension_breakdowns")
        if isinstance(breakdowns, dict) and any(isinstance(value, list) and value for value in breakdowns.values()):
            return "available"
        return "partial"
    if block_type == "benchmark":
        peer_benchmark = row.get("peer_benchmark")
        if isinstance(peer_benchmark, dict) and int(peer_benchmark.get("peer_count") or 0) > 0:
            return "available"
        return "partial"
    if block_type == "portfolio_watchlist":
        portfolio_breakdown = row.get("portfolio_breakdown")
        weakest_hotels = row.get("weakest_hotels")
        if isinstance(portfolio_breakdown, list) and portfolio_breakdown:
            return "available"
        if isinstance(weakest_hotels, list) and weakest_hotels:
            return "available"
        return "partial"
    fields = []
    for field in _analysis_block_evidence_fields(block_type):
        if field in {"dimension_breakdowns", "peer_benchmark", "portfolio_breakdown", "portfolio_outliers", "weakest_hotels"}:
            continue
        if field.startswith("report_sections.") or field.endswith("[0]"):
            continue
        fields.append(field)
    if not fields:
        return "partial"
    if any(row.get(field) not in (None, "") for field in fields):
        return "available"
    return "partial"


def _analysis_block_fact_spec(block_type: str) -> dict[str, list[str]]:
    return {
        "scope_overview": {
            "metrics_used": [
                "query_object_label",
                "query_grain",
                "resolved_hotel_count",
                "actual_value",
                "compare_value",
                "diff_value",
                "diff_rate",
            ],
            "evidence_fields": [
                "summary",
                "management_summary[0]",
                "report_sections.分析范围",
            ],
        },
        "dimension_summary": {
            "metrics_used": [
                "hotel_count",
                "total_income_actual",
                "owner_profit_actual",
                "operating_profit_actual",
                "revpar_actual",
            ],
            "evidence_fields": [
                "dimension_breakdowns.manage_corp",
                "dimension_breakdowns.area",
                "dimension_breakdowns.manage_corp_area",
                "report_sections.管理公司/区域汇总",
            ],
        },
        "income_quality": {
            "metrics_used": [
                "TOTAL_INCOME",
                "ROOM_INCOME",
                "RESTAURANT_INCOME",
                "BANQUET_INCOME",
                "OTHER_DEPT_INCOME",
                "OTHER_RATE_INCOME",
            ],
            "evidence_fields": [
                "total_income_actual",
                "room_income_actual",
                "restaurant_income_actual",
                "banquet_income_actual",
                "other_dept_income_actual",
                "other_rate_income_actual",
                "report_sections.收入质量",
            ],
        },
        "room_efficiency": {
            "metrics_used": [
                "OCCUPANCY_RATE",
                "ADR",
                "REVPAR",
                "RENTAL_ROOMS",
            ],
            "evidence_fields": [
                "occupancy_rate_actual",
                "occupancy_rate_budget",
                "occupancy_rate_last_year",
                "adr_actual",
                "adr_budget",
                "adr_last_year",
                "revpar_actual",
                "revpar_budget",
                "revpar_last_year",
                "rental_rooms_actual",
                "report_sections.客房效率",
            ],
        },
        "profit_quality": {
            "metrics_used": [
                "OWNER_PROFIT",
                "OPERATING_PROFIT",
                "ROOM_PROFIT",
                "RESTAURANT_PROFIT",
            ],
            "evidence_fields": [
                "owner_profit_actual",
                "owner_profit_budget",
                "owner_profit_last_year",
                "operating_profit_actual",
                "operating_profit_budget",
                "operating_profit_last_year",
                "room_profit_actual",
                "restaurant_profit_actual",
                "report_sections.利润质量",
            ],
        },
        "cost_efficiency": {
            "metrics_used": [
                "PEOPLE_COST",
                "ENERGY_EXPENSES",
                "RESTAURANT_COST",
                "FOOD_COST",
                "WINE_COST",
                "ROOM_COST",
                "ADMIN_EXPENSES",
            ],
            "evidence_fields": [
                "people_cost_actual",
                "energy_expenses_actual",
                "restaurant_cost_actual",
                "food_cost_actual",
                "wine_cost_actual",
                "room_cost_actual",
                "admin_expenses_actual",
                "report_sections.成本效率",
            ],
        },
        "benchmark": {
            "metrics_used": [
                "area",
                "brand",
                "brand_child",
                "brand_level",
                "city_level",
                "peer_count",
                "scope_used",
            ],
            "evidence_fields": [
                "area",
                "brand",
                "brand_child",
                "brand_level",
                "city_level",
                "peer_benchmark.current",
                "peer_benchmark.peer_avg",
                "report_sections.横向对标与继续追问",
            ],
        },
        "portfolio_watchlist": {
            "metrics_used": [
                "portfolio_member_count",
                "diff_value",
                "diff_rate",
                "owner_profit_actual",
                "operating_profit_actual",
                "total_income_actual",
            ],
            "evidence_fields": [
                "weakest_hotels",
                "portfolio_breakdown",
                "portfolio_outliers",
                "report_sections.重点酒店与梯队",
            ],
        },
    }.get(block_type, {"metrics_used": [], "evidence_fields": []})


def _analysis_block_data_status(
    block_type: str,
    source_kind: str,
    content: str,
    result: dict[str, Any],
    matched_title: str,
    peer_benchmark: dict[str, Any] | None = None,
    portfolio_breakdown: list[dict[str, Any]] | None = None,
    dimension_breakdowns: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    if not content:
        return "missing"
    if block_type == "benchmark":
        if isinstance(peer_benchmark, dict) and int(peer_benchmark.get("peer_count") or 0) > 0:
            return "available"
        return "partial"
    if block_type == "portfolio_watchlist":
        if isinstance(portfolio_breakdown, list) and portfolio_breakdown:
            return "available"
        if isinstance(result.get("weakest_hotels"), list) and result.get("weakest_hotels"):
            return "available"
        return "partial"
    if block_type == "dimension_summary":
        if isinstance(dimension_breakdowns, dict) and any(isinstance(v, list) and v for v in dimension_breakdowns.values()):
            return "available"
        return "partial"
    available, required = _analysis_block_required_field_status(block_type, result)
    if required:
        if len(available) == len(required):
            return "available"
        if available or content:
            return "partial"
        return "missing"
    if source_kind == "section" and matched_title:
        return "available"
    if source_kind == "fallback":
        return "partial"
    return "available"


def _analysis_block_required_fields(block_type: str) -> list[str]:
    return {
        "income_quality": ["total_income_actual", "room_income_actual", "restaurant_income_actual", "banquet_income_actual"],
        "room_efficiency": ["occupancy_rate_actual", "adr_actual", "revpar_actual"],
        "profit_quality": ["owner_profit_actual", "operating_profit_actual"],
        "cost_efficiency": ["people_cost_actual", "energy_expenses_actual", "restaurant_cost_actual"],
    }.get(block_type, [])


def _analysis_block_required_field_status(block_type: str, result: dict[str, Any]) -> tuple[list[str], list[str]]:
    row = result.get("_source_row") if isinstance(result.get("_source_row"), dict) else {}
    required = _analysis_block_required_fields(block_type)
    available = [field for field in required if row.get(field) not in (None, "")]
    return available, required


def _analysis_block_missing_fields(block_type: str, result: dict[str, Any]) -> list[str]:
    available, required = _analysis_block_required_field_status(block_type, result)
    return [field for field in required if field not in available]


def _analysis_block_missing_reason(block_type: str, result: dict[str, Any], data_status: str) -> str:
    if data_status == "available":
        return ""
    missing = _analysis_block_missing_fields(block_type, result)
    if not missing:
        return "当前分析块只有部分证据来源，建议结合明细数据再判断。"
    return "当前分析块缺少关键字段：" + "、".join(missing) + "。"


def _analysis_block_evidence_fields(block_type: str, matched_title: str, source_kind: str) -> list[str]:
    spec = _analysis_block_fact_spec(block_type)
    evidence_fields = [str(item).strip() for item in spec.get("evidence_fields", []) if str(item).strip()]
    if matched_title:
        section_field = f"report_sections.{matched_title}"
        if section_field not in evidence_fields:
            evidence_fields.insert(0, section_field)
    if source_kind == "fallback":
        fallback_field = "summary" if block_type == "scope_overview" else "management_summary[0]"
        if fallback_field not in evidence_fields:
            evidence_fields.append(fallback_field)
    return list(dict.fromkeys(evidence_fields))


def _build_analysis_blocks(
    result: dict[str, Any],
    parsed_intent: dict[str, Any] | None,
    template_code: str,
) -> list[dict[str, Any]]:
    report_sections = result.get("report_sections") if isinstance(result, dict) else []
    if not isinstance(report_sections, list):
        report_sections = []
    section_map: dict[str, str] = {}
    for item in report_sections:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        if title and content and title not in section_map:
            section_map[title] = content

    block_titles = _analysis_block_titles(template_code)
    order = _analysis_block_order(parsed_intent, template_code)
    blocks: list[dict[str, Any]] = []
    summary_text = str(result.get("summary") or "").strip()
    management_summary = result.get("management_summary") if isinstance(result, dict) else []
    management_lead = ""
    if isinstance(management_summary, list) and management_summary:
        management_lead = str(management_summary[0] or "").strip()
    source_row = result.get("_source_row") if isinstance(result.get("_source_row"), dict) else {}
    analysis_context: dict[str, Any] = dict(source_row)
    if isinstance(result, dict):
        analysis_context["summary"] = result.get("summary")
        analysis_context["management_summary"] = result.get("management_summary")
        for key in ("dimension_breakdowns", "peer_benchmark", "portfolio_breakdown", "portfolio_outliers", "weakest_hotels"):
            value = result.get(key)
            if value is not None:
                analysis_context[key] = value
    for block_type in order:
        candidates = block_titles.get(block_type, [_analysis_block_label(block_type)])
        matched_title = ""
        content = ""
        source_kind = ""
        for candidate in candidates:
            candidate_text = section_map.get(candidate)
            if candidate_text:
                matched_title = candidate
                content = candidate_text
                source_kind = "section"
                break
        if not content:
            if block_type == "scope_overview":
                matched_title = "分析范围"
                content = management_lead or summary_text
                source_kind = "fallback"
            elif block_type == "portfolio_watchlist":
                watchlist = result.get("weakest_hotels") if isinstance(result, dict) else []
                if isinstance(watchlist, list) and watchlist:
                    snippets = [str(item).strip() for item in watchlist[:3] if str(item).strip()]
                    if snippets:
                        matched_title = "重点酒店与梯队"
                        content = "；".join(snippets) + "。"
                        source_kind = "fallback"
        if not content:
            continue
        fact_spec = _analysis_block_fact_spec(block_type)
        data_status = _analysis_block_data_status(
            block_type,
            source_kind,
            content,
            result,
            matched_title,
            result.get("peer_benchmark") if isinstance(result.get("peer_benchmark"), dict) else None,
            result.get("portfolio_breakdown") if isinstance(result.get("portfolio_breakdown"), list) else None,
            result.get("dimension_breakdowns") if isinstance(result.get("dimension_breakdowns"), dict) else None,
        )
        blocks.append(
            {
                "code": block_type,
                "type": block_type,
                "title": matched_title or _analysis_block_label(block_type),
                "content": content,
                "template_code": template_code,
                "focus": _analysis_focus_code(parsed_intent),
                "metrics_used": fact_spec.get("metrics_used", []),
                "evidence_fields": _analysis_block_evidence_fields(block_type, matched_title, source_kind),
                "data_status": data_status,
                "missing_fields": _analysis_block_missing_fields(block_type, result),
                "missing_reason": _analysis_block_missing_reason(block_type, result, data_status),
            }
        )
    return blocks


def _build_narrative_brief(
    result: dict[str, Any],
    parsed_intent: dict[str, Any] | None,
    template_code: str,
    bundle_code: str,
    bundle: dict[str, Any],
    focus_profile: dict[str, Any],
) -> dict[str, Any]:
    summary = str(result.get("summary") or "").strip()
    management_summary = result.get("management_summary") if isinstance(result, dict) else []
    lead = summary
    if not lead and isinstance(management_summary, list) and management_summary:
        lead = str(management_summary[0] or "").strip()
    follow_up_text = _bundle_follow_up_text(
        bundle,
        "；".join([str(item).strip() for item in (result.get("suggestions") or [])[:3] if str(item).strip()]) + "。" if isinstance(result.get("suggestions"), list) and result.get("suggestions") else "可以继续追问经营摘要、收入结构、利润成本效率或重点酒店。",
        focus_profile,
    )
    query_plan = parsed_intent.get("query_plan") if isinstance(parsed_intent, dict) and isinstance(parsed_intent.get("query_plan"), dict) else {}
    focus_code = _analysis_focus_code(parsed_intent)
    contract = _analysis_contract(parsed_intent)
    contract_sequence = _analysis_contract_block_sequence(parsed_intent, template_code)
    return {
        "headline": _bundle_summary_title(bundle_code, template_code),
        "lead": lead,
        "follow_up_text": follow_up_text,
        "template_code": template_code,
        "focus": focus_code,
        "focus_meta": {
            "analysis_focus": focus_code,
            "analysis_mode": str(query_plan.get("analysis_mode") or "").strip(),
            "query_grain": str(query_plan.get("query_grain") or "").strip(),
            "bundle_code": bundle_code,
            "analysis_contract": {
                "has_contract": bool(contract),
                "block_sequence": contract_sequence,
                "priority": str(contract.get("priority") or "").strip(),
            },
        },
    }


def run_analysis_agent(
    result: dict[str, Any],
    parsed_intent: dict[str, Any] | None,
    template_code: str,
) -> dict[str, Any]:
    """Build structured fact blocks; narrative generation consumes this output."""
    return {
        "analysis_blocks": _build_analysis_blocks(result, parsed_intent, template_code),
        "agent": "analysis_agent",
        "contract_version": "1.0",
    }


def _evaluate_narrative_guardrail(narrative_brief: dict[str, Any], analysis_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    checks = ["no_unbacked_facts", "facts_from_analysis_blocks", "missing_data_not_overstated"]
    warnings: list[dict[str, Any]] = []
    narrative_text = " ".join(
        str(narrative_brief.get(key) or "")
        for key in ("headline", "lead", "follow_up_text")
    )
    overstatement_terms = ("完整", "充分", "可判断", "明确判断", "完全")
    for block in analysis_blocks:
        if not isinstance(block, dict):
            continue
        if block.get("data_status") not in {"partial", "missing"}:
            continue
        missing_fields = block.get("missing_fields") if isinstance(block.get("missing_fields"), list) else []
        if missing_fields and any(term in narrative_text for term in overstatement_terms):
            warnings.append(
                {
                    "code": "missing_data_overstated",
                    "block": block.get("code") or block.get("type"),
                    "missing_fields": missing_fields,
                }
            )
    warning_codes = [str(item.get("code") or "").strip() for item in warnings if str(item.get("code") or "").strip()]
    return {
        "status": "warning" if warnings else "passed",
        "checks": checks + list(dict.fromkeys(warning_codes)),
        "warnings": warnings,
    }


def run_narrative_agent(
    result: dict[str, Any],
    parsed_intent: dict[str, Any] | None,
    template_code: str,
    bundle_code: str,
    bundle: dict[str, Any],
    focus_profile: dict[str, Any],
    analysis_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build reader-facing narrative from structured analysis facts."""
    narrative_brief = _build_narrative_brief(result, parsed_intent, template_code, bundle_code, bundle, focus_profile)
    guardrail = _evaluate_narrative_guardrail(narrative_brief, analysis_blocks)
    return {
        "narrative_brief": narrative_brief,
        "agent": "narrative_agent",
        "contract_version": "1.0",
        "input_blocks": [str(item.get("code") or item.get("type") or "").strip() for item in analysis_blocks if isinstance(item, dict)],
        "guardrail": guardrail,
    }


def _attach_structured_outputs(
    result: dict[str, Any],
    parsed_intent: dict[str, Any] | None,
) -> dict[str, Any]:
    bundle_code, bundle, template_code = _resolve_template_bundle(parsed_intent, None)
    _, focus_profile = _focus_profile(parsed_intent)
    analysis_result = run_analysis_agent(result, parsed_intent, template_code)
    narrative_result = run_narrative_agent(
        result,
        parsed_intent,
        template_code,
        bundle_code,
        bundle,
        focus_profile,
        analysis_result["analysis_blocks"],
    )
    enhanced = dict(result)
    enhanced["analysis_blocks"] = analysis_result["analysis_blocks"]
    enhanced["analysis_agent"] = {
        "agent": analysis_result["agent"],
        "contract_version": analysis_result["contract_version"],
    }
    enhanced["narrative_brief"] = narrative_result["narrative_brief"]
    enhanced["narrative_agent"] = {
        "agent": narrative_result["agent"],
        "contract_version": narrative_result["contract_version"],
        "input_blocks": narrative_result["input_blocks"],
        "guardrail": narrative_result["guardrail"],
    }
    enhanced.pop("_source_row", None)
    return enhanced


def should_use_llm_enhancement(parsed_intent: dict[str, Any]) -> bool:
    if not llm_enabled() or LLM_EXPLANATION_POLICY in {"0", "false", "off", "never"}:
        return False
    if LLM_EXPLANATION_POLICY in {"1", "true", "always"}:
        return True
    intent = str(parsed_intent.get("intent", "")).strip()
    return intent in {"report", "explain"} or bool(parsed_intent.get("needs_deep_explanation"))


def _format_percent(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value * 100:.1f}%"
    return "N/A"


def _format_amount(value: Any) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value.is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}"
    return "N/A"


def _numeric(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _ratio_text(numerator: Any, denominator: Any) -> str:
    num = _numeric(numerator)
    den = _numeric(denominator)
    if num is None or den in (None, 0.0):
        return "N/A"
    return _format_percent(num / den)


def _variance_text(actual: Any, compare: Any, label: str) -> str:
    actual_num = _numeric(actual)
    compare_num = _numeric(compare)
    if actual_num is None or compare_num is None:
        return f"{label}对比值不足"
    diff = actual_num - compare_num
    rate = "N/A" if compare_num == 0 else _format_percent(diff / compare_num)
    return f"{label}差额 {_format_amount(diff)}，差异率 {rate}"


def _has_overview_context(row: dict[str, Any]) -> bool:
    return any(
        key in row and row.get(key) is not None
        for key in (
            "total_income_actual",
            "room_income_actual",
            "restaurant_income_actual",
            "banquet_income_actual",
            "occupancy_rate_actual",
            "adr_actual",
            "revpar_actual",
            "operating_profit_actual",
            "people_cost_actual",
            "energy_expenses_actual",
        )
    )


def _build_income_quality_text(row: dict[str, Any]) -> str:
    total = row.get("total_income_actual")
    if _numeric(total) is None:
        return "当前结果尚未包含总收入、客房收入、餐饮/宴会收入和其它收入结构，无法拆分收入质量。"
    room = row.get("room_income_actual")
    restaurant = row.get("restaurant_income_actual")
    banquet = row.get("banquet_income_actual")
    other_dept = row.get("other_dept_income_actual")
    other_rate = row.get("other_rate_income_actual")
    return (
        f"总收入 {_format_amount(total)}，其中客房收入 {_format_amount(room)}（占比 {_ratio_text(room, total)}），"
        f"餐厅收入 {_format_amount(restaurant)}（占比 {_ratio_text(restaurant, total)}），"
        f"宴会收入 {_format_amount(banquet)}（占比 {_ratio_text(banquet, total)}），"
        f"其它营业部门收入 {_format_amount(other_dept)}，租金及其它收入 {_format_amount(other_rate)}。"
        f"{_variance_text(total, row.get('total_income_budget'), '总收入对预算')}；"
        f"{_variance_text(total, row.get('total_income_last_year'), '总收入同比')}。"
    )


def _build_room_efficiency_text(row: dict[str, Any]) -> str:
    if _numeric(row.get("occupancy_rate_actual")) is None and _numeric(row.get("adr_actual")) is None and _numeric(row.get("revpar_actual")) is None:
        return "当前结果未同时返回入住率、ADR 和 RevPAR，不能判断房价和出租率的共同作用。"
    return (
        f"入住率 {_format_percent(row.get('occupancy_rate_actual'))}，预算 {_format_percent(row.get('occupancy_rate_budget'))}，同期 {_format_percent(row.get('occupancy_rate_last_year'))}；"
        f"ADR {_format_amount(row.get('adr_actual'))}，预算 {_format_amount(row.get('adr_budget'))}，同期 {_format_amount(row.get('adr_last_year'))}；"
        f"RevPAR {_format_amount(row.get('revpar_actual'))}，预算 {_format_amount(row.get('revpar_budget'))}，同期 {_format_amount(row.get('revpar_last_year'))}；"
        f"出租房间数 {_format_amount(row.get('rental_rooms_actual'))}。"
    )


def _build_profit_quality_text(row: dict[str, Any]) -> str:
    owner_profit = row.get("owner_profit_actual")
    profit = row.get("operating_profit_actual")
    total = row.get("total_income_actual")
    if _numeric(owner_profit) is None and _numeric(profit) is None:
        return "当前结果未包含 NOP业主净利润或经营利润（GOP），不能判断收入变化是否同步转化为利润。"
    return (
        f"NOP业主净利润 {_format_amount(owner_profit)}，NOP率 {_ratio_text(owner_profit, total)}；"
        f"经营利润（GOP） {_format_amount(profit)}，GOP率 {_ratio_text(profit, total)}；"
        f"{_variance_text(profit, row.get('operating_profit_budget'), 'GOP对预算')}；"
        f"{_variance_text(profit, row.get('operating_profit_last_year'), 'GOP同比')}。"
        f"客房利润 {_format_amount(row.get('room_profit_actual'))}，餐饮利润 {_format_amount(row.get('restaurant_profit_actual'))}。"
    )


def _build_cost_efficiency_text(row: dict[str, Any]) -> str:
    total = row.get("total_income_actual")
    cost_keys = [
        ("人工成本", "people_cost_actual"),
        ("能源费用", "energy_expenses_actual"),
        ("餐饮成本", "restaurant_cost_actual"),
        ("食品成本", "food_cost_actual"),
        ("酒水成本", "wine_cost_actual"),
        ("客房成本", "room_cost_actual"),
        ("行政费用", "admin_expenses_actual"),
    ]
    parts = [
        f"{label} {_format_amount(row.get(key))}（占收入 {_ratio_text(row.get(key), total)}）"
        for label, key in cost_keys
        if _numeric(row.get(key)) is not None
    ]
    if not parts:
        return "当前结果未包含人工、能耗、餐饮成本和费用率数据，不能拆分成本效率。"
    return "；".join(parts) + "。"


def _build_internal_benchmark_text(peer_benchmark: dict[str, Any] | None) -> str | None:
    if not isinstance(peer_benchmark, dict):
        return None
    peer_count = peer_benchmark.get("peer_count")
    current = peer_benchmark.get("current") if isinstance(peer_benchmark.get("current"), dict) else {}
    peer_avg = peer_benchmark.get("peer_avg") if isinstance(peer_benchmark.get("peer_avg"), dict) else {}
    scope = peer_benchmark.get("scope") if isinstance(peer_benchmark.get("scope"), dict) else {}
    scope_used = str(peer_benchmark.get("scope_used") or "").strip()
    if not isinstance(peer_count, int) or peer_count <= 0:
        return None
    scope_text = "、".join(str(scope.get(key) or "").strip() for key in ("area", "brand", "brand_child", "brand_level", "city_level") if str(scope.get(key) or "").strip())
    return (
        f"内部对标采用 {scope_used or '当前同口径样本'}，样本共 {peer_count} 家（不含本店），范围为 {scope_text or '当前范围'}；"
        f"样本总收入均值 {_format_amount(peer_avg.get('total_income'))}，RevPAR 均值 {_format_amount(peer_avg.get('revpar'))}，"
        f"经营利润均值 {_format_amount(peer_avg.get('operating_profit'))}，经营利润率均值 {_format_percent(peer_avg.get('profit_margin'))}，"
        f"综合成本率均值 {_format_percent(peer_avg.get('cost_rate'))}。"
        f"当前酒店总收入 {_format_amount(current.get('total_income'))}，RevPAR {_format_amount(current.get('revpar'))}，"
        f"经营利润 {_format_amount(current.get('operating_profit'))}，经营利润率 {_format_percent(current.get('profit_margin'))}，"
        f"综合成本率 {_format_percent(current.get('cost_rate'))}。"
    )


def _build_benchmark_text(row: dict[str, Any], peer_insight: str | None, peer_benchmark: dict[str, Any] | None = None, external_benchmark_requested: bool = False) -> str:
    descriptors = [
        str(row.get("area") or "").strip(),
        str(row.get("brand") or "").strip(),
        str(row.get("brand_child") or "").strip(),
        str(row.get("brand_level") or "").strip(),
        str(row.get("city_level") or "").strip(),
    ]
    descriptor_text = "、".join(item for item in descriptors if item)
    internal_text = _build_internal_benchmark_text(peer_benchmark)
    if internal_text:
        suffix = "；你已开启外部行业对标，但当前系统尚未接入稳定外部源，后续可按需联网补充。" if external_benchmark_requested else ""
        return f"{internal_text} 当前酒店维度标签：{descriptor_text or '未返回区域/品牌/档次标签'}{suffix}"
    if peer_insight:
        suffix = "；你已开启外部行业对标，但当前系统尚未接入稳定外部源，后续可按需联网补充。" if external_benchmark_requested else ""
        return f"{peer_insight} 当前酒店维度标签：{descriptor_text or '未返回区域/品牌/档次标签'}{suffix}"
    if external_benchmark_requested:
        return f"当前返回了区域/品牌/档次标签：{descriptor_text or '未返回'}；内部同口径对标样本暂不足。你已开启外部行业对标，但当前系统尚未接入稳定外部源，后续可按需联网补充。"
    return f"当前返回了区域/品牌/档次标签：{descriptor_text or '未返回'}；如需判断相对位置，需要在同区域、同品牌、同档次样本内同时比较收入、RevPAR、利润率和成本率。"


def _build_executive_sections(conclusion: str, risks: list[str], suggestions: list[str]) -> list[dict[str, Any]]:
    return [
        {"title": "分析范围", "content": conclusion},
        {"title": "收入质量", "content": risks[0] if len(risks) > 0 else "当前结果未包含收入结构拆分，无法判断收入来自客房、餐饮还是宴会。"},
        {"title": "客房效率", "content": risks[1] if len(risks) > 1 else "当前结果未包含入住率、ADR、RevPAR 的组合数据，暂不能判断房价和出租率的共同作用。"},
        {"title": "利润质量", "content": risks[2] if len(risks) > 2 else "当前结果未包含收入与经营利润的联动拆解，暂不能判断收入改善是否同步转化为利润。"},
        {"title": "成本效率", "content": risks[3] if len(risks) > 3 else "当前结果未包含人工、能耗、餐饮成本和费用率数据，暂不能判断成本效率。"},
        {"title": "横向对标", "content": risks[4] if len(risks) > 4 else "当前结果未包含同区域、同品牌或同档次对标样本，暂不能判断相对市场位置。"},
    ]


def _format_ranked_rows(rows: list[dict[str, Any]], *, key: str, label: str, limit: int = 5, reverse: bool = True) -> str | None:
    valid_rows = [row for row in rows if row.get("hotel_name") and isinstance(row.get(key), (int, float))]
    if not valid_rows:
        return None
    ranked = sorted(valid_rows, key=lambda item: item.get(key) or 0, reverse=reverse)[:limit]
    parts = [
        f"{index}. {row.get('hotel_name')} {label}{_format_amount(row.get(key))}"
        for index, row in enumerate(ranked, 1)
    ]
    return "；".join(parts) + "。"


def _build_portfolio_ranking_text(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "当前组合明细不足，暂不能形成酒店排名、梯队或异常样本。"
    ranking_parts = [
        _format_ranked_rows(rows, key="total_income_actual", label="总收入 "),
        _format_ranked_rows(rows, key="owner_profit_actual", label="NOP业主净利润 "),
        _format_ranked_rows(rows, key="operating_profit_actual", label="GOP "),
        _format_ranked_rows(rows, key="revpar_actual", label="RevPAR "),
        _format_ranked_rows(rows, key="diff_value", label="差额 ", reverse=False),
    ]
    ranking_parts = [item for item in ranking_parts if item]
    return " ".join(ranking_parts) if ranking_parts else "当前组合明细已返回，但缺少可用于排名的收入、利润、RevPAR 或差额字段。"


def _build_portfolio_tier_text(rows: list[dict[str, Any]]) -> str:
    profit_rows = [row for row in rows if isinstance(row.get("owner_profit_actual"), (int, float))]
    if not profit_rows:
        return "当前组合明细未包含 NOP业主净利润，暂不能形成业主净利润梯队。"
    tiers = [
        ("2000万以上", lambda value: value >= 20_000_000),
        ("1000万-2000万", lambda value: 10_000_000 <= value < 20_000_000),
        ("500万-1000万", lambda value: 5_000_000 <= value < 10_000_000),
        ("200万-500万", lambda value: 2_000_000 <= value < 5_000_000),
        ("0-200万", lambda value: 0 <= value < 2_000_000),
        ("亏损", lambda value: value < 0),
    ]
    parts: list[str] = []
    for label, predicate in tiers:
        matched = [row for row in profit_rows if predicate(float(row.get("owner_profit_actual") or 0))]
        if matched:
            total = sum(float(row.get("owner_profit_actual") or 0) for row in matched)
            parts.append(f"{label} {len(matched)} 家，合计 NOP业主净利润 {_format_amount(total)}")
    return "；".join(parts) + "。" if parts else "当前组合明细未形成有效 NOP业主净利润梯队。"


def _dimension_label(dimension: str) -> str:
    labels = {
        "manage_corp": "管理公司",
        "area": "区域",
        "brand_child": "品牌",
        "manage_corp_area": "管理公司 x 区域",
    }
    return labels.get(dimension, dimension)


def _dimension_row_label(dimension: str, row: dict[str, Any]) -> str:
    if dimension == "manage_corp_area":
        manage_corp = str(row.get("manage_corp") or "未标注").strip() or "未标注"
        area = str(row.get("area") or "未标注").strip() or "未标注"
        return f"{manage_corp}-{area}"
    if dimension == "manage_corp":
        return str(row.get("manage_corp") or "未标注").strip() or "未标注"
    if dimension == "area":
        return str(row.get("area") or "未标注").strip() or "未标注"
    if dimension == "brand_child":
        return str(row.get("brand_child") or "未标注").strip() or "未标注"
    return str(row.get("name") or "未标注").strip() or "未标注"


def _build_dimension_breakdown_text(dimension_breakdowns: dict[str, list[dict[str, Any]]] | None) -> str | None:
    if not dimension_breakdowns:
        return None
    parts: list[str] = []
    for dimension in ("manage_corp", "area", "manage_corp_area", "brand_child"):
        rows = dimension_breakdowns.get(dimension) or []
        if not rows:
            continue
        ranked = sorted(
            rows,
            key=lambda item: item.get("total_income_actual") if isinstance(item.get("total_income_actual"), (int, float)) else float("-inf"),
            reverse=True,
        )[:3]
        snippets = []
        for row in ranked:
            label = _dimension_row_label(dimension, row)
            snippets.append(
                f"{label}：{int(row.get('hotel_count') or 0)} 家，总收入 {_format_amount(row.get('total_income_actual'))}，"
                f"NOP {_format_amount(row.get('owner_profit_actual'))}，GOP {_format_amount(row.get('operating_profit_actual'))}，"
                f"RevPAR {_format_amount(row.get('revpar_actual'))}"
            )
        if snippets:
            parts.append(f"{_dimension_label(dimension)}维度前三项：" + "；".join(snippets))
    return " ".join(parts) if parts else None


def _build_template_summary_text(
    *,
    template_code: str,
    bundle: dict[str, Any],
    analysis_focus: str,
    focus_profile: dict[str, Any],
    summary: str,
    row: dict[str, Any],
    query_plan: dict[str, Any],
    compare_scope: str,
    member_count: Any,
    portfolio_insight: str | None,
    outlier_text: str | None,
    dimension_text: str | None,
) -> str:
    scope_label = str(query_plan.get("query_object_label") or row.get("hotel_name") or "当前范围").strip() or "当前范围"
    preamble = _bundle_summary_preamble(
        bundle,
        "当前结果已完成经营拆解，先看收入、利润、客房效率和成本效率，再判断差异来自哪一层。",
    )
    focus_lead = _focus_summary_lead(analysis_focus, focus_profile)
    if template_code == "executive_hotel_snapshot":
        parts = [
            preamble,
            focus_lead,
            f"当前聚焦 {scope_label}，样本 1 家，实际值 {_format_amount(row.get('actual_value'))}，对比 {_format_amount(row.get('compare_value'))}，差额 {_format_amount(row.get('diff_value'))}，差异率约 {_format_percent(row.get('diff_rate'))}。",
        ]
        if compare_scope:
            parts.append(f"默认对比口径为{compare_scope}。")
        return " ".join(part for part in parts if part)
    if template_code == "executive_group_dimension":
        parts = [
            preamble,
            focus_lead,
            f"当前已按 {scope_label} 做分维度汇总；本次组合样本 {member_count or 'N/A'} 家，对{compare_scope}的差额 {_format_amount(row.get('diff_value'))}，差异率约 {_format_percent(row.get('diff_rate'))}。",
        ]
        if dimension_text:
            parts.append("已补充管理公司与区域层级的前三项对比。")
        if outlier_text:
            parts.append(outlier_text)
        return " ".join(part for part in parts if part)
    parts = [
        preamble,
        focus_lead,
        f"当前已按 {scope_label} 做组合汇总；本次组合样本 {member_count or 'N/A'} 家，对{compare_scope}的差额 {_format_amount(row.get('diff_value'))}，差异率约 {_format_percent(row.get('diff_rate'))}。",
    ]
    if portfolio_insight:
        parts.append(portfolio_insight)
    if outlier_text:
        parts.append(outlier_text)
    if dimension_text:
        parts.append("已按管理公司/区域维度补充观察。")
    return " ".join(part for part in parts if part)


def _build_report_style_sections(
    summary: str,
    risks: list[str],
    suggestions: list[str],
    parsed_intent: dict[str, Any] | None,
    row: dict[str, Any],
    portfolio_breakdown: list[dict[str, Any]] | None,
    portfolio_outliers: dict[str, Any] | None,
    dimension_breakdowns: dict[str, list[dict[str, Any]]] | None,
    peer_benchmark: dict[str, Any] | None,
    external_benchmark_requested: bool,
) -> list[dict[str, Any]]:
    query_plan = parsed_intent.get("query_plan") if isinstance(parsed_intent, dict) and isinstance(parsed_intent.get("query_plan"), dict) else {}
    scope_label = _scope_label(parsed_intent, str(row.get("hotel_name") or "当前范围"))
    period = str(parsed_intent.get("time_scope") or "当前期间") if isinstance(parsed_intent, dict) else "当前期间"
    compare_scope = _compare_scope_label(parsed_intent)
    member_count = row.get("portfolio_member_count") or query_plan.get("resolved_hotel_count") or "N/A"
    ranking_text = _build_portfolio_ranking_text(portfolio_breakdown or [])
    tier_text = _build_portfolio_tier_text(portfolio_breakdown or [])
    outlier_text = _portfolio_outlier_text(portfolio_outliers) or "当前未形成明确异常样本，可继续按收入、利润、RevPAR 或成本率筛选。"
    dimension_text = _build_dimension_breakdown_text(dimension_breakdowns)
    benchmark_text = _build_benchmark_text(row, None, peer_benchmark, external_benchmark_requested)
    follow_up_text = "；".join(suggestions[:3]) + "。" if suggestions else "可以继续追问经营摘要、收入结构、利润成本效率或重点酒店。"
    sections = [
        {
            "title": "分析范围",
            "content": f"{period}，{scope_label}，样本 {member_count} 家。{summary}",
        },
        {"title": "经营总览", "content": f"总收入 {_format_amount(row.get('total_income_actual'))}；NOP业主净利润 {_format_amount(row.get('owner_profit_actual'))}；NOP率 {_ratio_text(row.get('owner_profit_actual'), row.get('total_income_actual'))}；经营利润（GOP） {_format_amount(row.get('operating_profit_actual'))}；对{compare_scope}差额 {_format_amount(row.get('diff_value'))}，差异率 {_format_percent(row.get('diff_rate'))}。"},
    ]
    if dimension_text:
        sections.append({"title": "管理公司/区域汇总", "content": dimension_text})
    sections.extend([
        {"title": "收入质量", "content": risks[0] if len(risks) > 0 else _build_income_quality_text(row)},
        {"title": "客房效率", "content": risks[1] if len(risks) > 1 else _build_room_efficiency_text(row)},
        {"title": "利润质量", "content": risks[2] if len(risks) > 2 else _build_profit_quality_text(row)},
        {"title": "成本效率", "content": risks[3] if len(risks) > 3 else _build_cost_efficiency_text(row)},
        {"title": "重点酒店与梯队", "content": f"{ranking_text} {tier_text} {outlier_text}"},
        {"title": "横向对标与继续追问", "content": f"{benchmark_text} 可继续问：{follow_up_text}"},
    ])
    return _apply_report_template(parsed_intent, sections)


def _build_report_style_sections_v2(
    summary: str,
    risks: list[str],
    suggestions: list[str],
    parsed_intent: dict[str, Any] | None,
    row: dict[str, Any],
    portfolio_breakdown: list[dict[str, Any]] | None,
    portfolio_outliers: dict[str, Any] | None,
    dimension_breakdowns: dict[str, list[dict[str, Any]]] | None,
    peer_benchmark: dict[str, Any] | None,
    external_benchmark_requested: bool,
) -> list[dict[str, Any]]:
    query_plan = parsed_intent.get("query_plan") if isinstance(parsed_intent, dict) and isinstance(parsed_intent.get("query_plan"), dict) else {}
    analysis_focus = _analysis_focus_code(parsed_intent)
    _, focus_profile = _focus_profile(parsed_intent)
    bundle_code, bundle, template_code = _resolve_template_bundle(parsed_intent, row)
    scope_label = _scope_label(parsed_intent, str(row.get("hotel_name") or "当前范围"))
    period = str(parsed_intent.get("time_scope") or "当前期间") if isinstance(parsed_intent, dict) else "当前期间"
    compare_scope = _compare_scope_label(parsed_intent)
    member_count = row.get("portfolio_member_count") or query_plan.get("resolved_hotel_count") or "N/A"
    ranking_text = _build_portfolio_ranking_text(portfolio_breakdown or [])
    tier_text = _build_portfolio_tier_text(portfolio_breakdown or [])
    outlier_text = _portfolio_outlier_text(portfolio_outliers) or "当前未形成明确异常样本，可继续按收入、利润、RevPAR 或成本率筛选。"
    dimension_text = _build_dimension_breakdown_text(dimension_breakdowns)
    benchmark_text = _build_benchmark_text(row, None, peer_benchmark, external_benchmark_requested)
    follow_up_text = _bundle_follow_up_text(
        bundle,
        "；".join(suggestions[:3]) + "。" if suggestions else "可以继续追问经营摘要、收入结构、利润成本效率或重点酒店。",
        focus_profile,
    )
    summary_title = _bundle_summary_title(bundle_code, template_code)
    summary_content = _build_template_summary_text(
        template_code=template_code,
        bundle=bundle,
        analysis_focus=analysis_focus,
        focus_profile=focus_profile,
        summary=summary,
        row=row,
        query_plan=query_plan,
        compare_scope=compare_scope,
        member_count=member_count,
        portfolio_insight=_portfolio_breakdown_text(portfolio_breakdown or []) if template_code == "executive_portfolio" else None,
        outlier_text=outlier_text if template_code in {"executive_portfolio", "executive_group_dimension"} else None,
        dimension_text=dimension_text if template_code == "executive_group_dimension" else None,
    )
    sections = [
        {"title": "分析范围", "content": f"{period}，{scope_label}，样本 {member_count} 家。"},
        {"title": summary_title, "content": summary_content},
    ]
    if template_code == "executive_group_dimension" and dimension_text:
        sections.append({"title": "管理公司/区域汇总", "content": dimension_text})
    sections.extend([
        {"title": "收入质量", "content": risks[0] if len(risks) > 0 else _build_income_quality_text(row)},
        {"title": "客房效率", "content": risks[1] if len(risks) > 1 else _build_room_efficiency_text(row)},
        {"title": "利润质量", "content": risks[2] if len(risks) > 2 else _build_profit_quality_text(row)},
        {"title": "成本效率", "content": risks[3] if len(risks) > 3 else _build_cost_efficiency_text(row)},
    ])
    if template_code == "executive_portfolio":
        sections.append({"title": "重点酒店与梯队", "content": f"{ranking_text} {tier_text} {outlier_text}"})
        sections.append({"title": "横向对标与继续追问", "content": f"{benchmark_text} 可继续问：{follow_up_text}"})
    elif template_code == "executive_group_dimension":
        sections.append({"title": "横向对标与继续追问", "content": f"{benchmark_text} 可继续问：{follow_up_text}"})
    else:
        sections.append({"title": "横向对标", "content": f"{benchmark_text} 可继续问：{follow_up_text}"})
    return _apply_report_template(parsed_intent, sections)


def _apply_report_template(parsed_intent: dict[str, Any] | None, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    query_plan = parsed_intent.get("query_plan") if isinstance(parsed_intent, dict) and isinstance(parsed_intent.get("query_plan"), dict) else {}
    template_code = str(query_plan.get("report_template_code") or "").strip()
    if not template_code:
        return sections
    templates = load_report_templates()
    template = templates.get(template_code)
    if not isinstance(template, dict):
        return sections
    include_sections = template.get("include_sections", [])
    if isinstance(include_sections, list) and include_sections:
        allowed_titles = {str(title) for title in include_sections}
        sections = [item for item in sections if str(item.get("title") or "") in allowed_titles]
    section_order = template.get("section_order", [])
    if not isinstance(section_order, list) or not section_order:
        return sections
    analysis_focus = _analysis_focus_code(parsed_intent)
    focus_order = template.get("focus_section_order", {})
    focus_section_order: list[str] = []
    if isinstance(focus_order, dict) and analysis_focus:
        focus_candidate = focus_order.get(analysis_focus)
        if isinstance(focus_candidate, list) and focus_candidate:
            focus_section_order = [str(title) for title in focus_candidate if str(title).strip()]
    order_map = {str(title): index for index, title in enumerate(section_order)}
    focus_map = {str(title): index for index, title in enumerate(focus_section_order)}
    return sorted(
        sections,
        key=lambda item: (
            focus_map.get(str(item.get("title") or ""), len(focus_section_order) + order_map.get(str(item.get("title") or ""), len(section_order))),
            order_map.get(str(item.get("title") or ""), len(section_order)),
            str(item.get("title") or ""),
        ),
    )


def _scope_label(parsed_intent: dict[str, Any] | None, fallback: str = "当前范围") -> str:
    query_plan = parsed_intent.get("query_plan") if isinstance(parsed_intent, dict) and isinstance(parsed_intent.get("query_plan"), dict) else {}
    return str(query_plan.get("query_object_label") or fallback).strip() or fallback


def _build_management_summary(
    *,
    metric_name: str,
    parsed_intent: dict[str, Any] | None,
    row: dict[str, Any],
    summary: str,
    portfolio_breakdown: list[dict[str, Any]] | None,
    peer_benchmark: dict[str, Any] | None,
    focus_profile: dict[str, Any] | None = None,
) -> list[str]:
    query_plan = parsed_intent.get("query_plan") if isinstance(parsed_intent, dict) and isinstance(parsed_intent.get("query_plan"), dict) else {}
    scope_label = _scope_label(parsed_intent, str(row.get("hotel_name") or "当前范围"))
    analysis_mode = str(query_plan.get("analysis_mode") or "").strip()
    analysis_focus = _analysis_focus_code(parsed_intent)
    management_summary: list[str] = []
    focus_lead = _focus_summary_lead(analysis_focus, focus_profile or {})

    if analysis_focus == "income_structure":
        management_summary.append(focus_lead or f"本次按 {scope_label} 专门拆收入结构，优先看总收入、客房收入、餐饮/宴会收入和其他收入的构成。")
        management_summary.append(_build_income_quality_text(row))
        return management_summary

    if analysis_focus == "profit_cost_efficiency":
        management_summary.append(focus_lead or f"本次按 {scope_label} 专门看利润质量和成本效率，重点观察利润是否跟随收入改善，以及人工、能耗、餐饮成本和费用率。")
        management_summary.append(_build_profit_quality_text(row))
        management_summary.append(_build_cost_efficiency_text(row))
        return management_summary

    if analysis_focus == "yoy_change":
        management_summary.append(focus_lead or f"本次按 {scope_label} 切换到同比观察，重点区分当前变化是预算偏差还是去年同期基数变化。")
        management_summary.append(summary)
        return management_summary

    if analysis_focus == "driver_analysis":
        management_summary.append(focus_lead or f"本次按 {scope_label} 展开原因，先看驱动项，再判断变化来自收入、利润还是成本。")
        management_summary.append(summary)
        return management_summary

    if analysis_focus == "dimension_comparison":
        management_summary.append(focus_lead or f"本次按 {scope_label} 做维度比较，先看管理公司、区域、品牌的相对位置，再拆收入、利润和成本。")
        management_summary.append(summary)
        return management_summary

    if analysis_focus == "management_report":
        management_summary.append(focus_lead or f"本次按 {scope_label} 整理经营摘要，先把收入质量、客房效率、利润质量、成本效率和内部对标放在同一张管理层视图里。")
        management_summary.append(summary)
        return management_summary

    if analysis_focus == "portfolio_overview":
        management_summary.append(focus_lead or f"本次按 {scope_label} 做组合观察，先看组合层面的收入、利润和成本效率。")
        management_summary.append(summary)
        return management_summary

    if analysis_focus == "scope_refinement":
        management_summary.append(focus_lead or f"本次只是把 {scope_label} 收窄到当前观察范围，先确保口径一致，再继续看变化。")
        management_summary.append(summary)
        return management_summary

    if analysis_focus == "scope_inventory":
        management_summary.append(focus_lead or f"本次只核对 {scope_label} 的在营酒店数量，不把它解释成经营优劣。")
        management_summary.append(f"当前在营酒店数 {_format_amount(row.get('actual_value'))} 家，对比 {_format_amount(row.get('compare_value'))} 家，差额 {_format_amount(row.get('diff_value'))}，差异率约 {_format_percent(row.get('diff_rate'))}。")
        return management_summary

    if analysis_focus == "metric_snapshot":
        management_summary.append(focus_lead or f"本次按 {scope_label} 的单项指标快照观察，先看当前值和对比值，再判断差异来自哪一层。")
        management_summary.append(summary)
        return management_summary

    if analysis_mode == "portfolio_overview":
        member_count = row.get("portfolio_member_count")
        management_summary.append(
            f"本次按 {scope_label} 做组合观察，当前样本 {member_count or 'N/A'} 家，先看组合层面的收入、利润和成本效率。"
        )
        if isinstance(row.get("total_income_actual"), (int, float)) or isinstance(row.get("operating_profit_actual"), (int, float)):
            management_summary.append(
                f"组合总收入 {_format_amount(row.get('total_income_actual'))}，NOP业主净利润 {_format_amount(row.get('owner_profit_actual'))}，"
                f"NOP率 {_ratio_text(row.get('owner_profit_actual'), row.get('total_income_actual'))}，经营利润（GOP） {_format_amount(row.get('operating_profit_actual'))}。"
            )
        if portfolio_breakdown:
            top = portfolio_breakdown[0]
            management_summary.append(
                f"如需继续下钻，可优先查看 {top.get('hotel_name') or '重点酒店'}，它已经进入当前组合的重点样本。"
            )
        elif isinstance(peer_benchmark, dict) and int(peer_benchmark.get("peer_count") or 0) > 0:
            management_summary.append(
                f"内部已找到 {peer_benchmark.get('scope_used') or '同口径'} 样本 {int(peer_benchmark.get('peer_count') or 0)} 家，可继续看组合相对位置。"
            )
        else:
            management_summary.append(f"???????? {_format_amount(row.get('total_income_actual'))}?NOP????? {_format_amount(row.get('owner_profit_actual'))}?GOP {_format_amount(row.get('operating_profit_actual'))}?")
        return management_summary

    management_summary.append(
        f"本次按 {scope_label} 返回 {metric_name} 的当前观察，先聚焦实际值、对比值和差额，再决定是否继续下钻原因。"
    )
    if isinstance(row.get("actual_value"), (int, float)) or isinstance(row.get("compare_value"), (int, float)):
        management_summary.append(
            f"当前实际 {_format_amount(row.get('actual_value'))}，对比 {_format_amount(row.get('compare_value'))}，差额 {_format_amount(row.get('diff_value'))}，差异率 {_format_percent(row.get('diff_rate'))}。"
        )
    if isinstance(peer_benchmark, dict) and int(peer_benchmark.get("peer_count") or 0) > 0:
        management_summary.append(
            f"内部同口径样本 {int(peer_benchmark.get('peer_count') or 0)} 家，可继续看收入质量、客房效率、利润质量和成本效率。"
        )
    else:
        management_summary.append(f"???? {_format_amount(row.get('actual_value'))}??? {_format_amount(row.get('compare_value'))}??? {_format_amount(row.get('diff_value'))}?")
    return management_summary


def _build_follow_up_suggestions(
    metric_name: str,
    parsed_intent: dict[str, Any] | None,
    portfolio_breakdown: list[dict[str, Any]] | None,
    focus_profile: dict[str, Any] | None = None,
) -> list[str]:
    query_plan = parsed_intent.get("query_plan") if isinstance(parsed_intent, dict) and isinstance(parsed_intent.get("query_plan"), dict) else {}
    analysis_mode = str(query_plan.get("analysis_mode") or "").strip()
    scope_label = _scope_label(parsed_intent)
    analysis_focus = _analysis_focus_code(parsed_intent)
    if isinstance(focus_profile, dict):
        prompts = focus_profile.get("follow_up_prompts")
        if isinstance(prompts, list):
            items = [str(item).strip() for item in prompts if str(item).strip()]
            if items:
                return items[:3]
    focus_suggestions = {
        "income_structure": [
            "继续看客房收入。",
            "只看餐饮/宴会收入。",
            "切换到收入同比变化。",
        ],
        "profit_cost_efficiency": [
            "继续看人工成本。",
            "只看能耗和餐饮成本。",
            "切换到利润同比变化。",
        ],
        "yoy_change": [
            "继续看去年同期对比。",
            "切换到预算对比。",
            "下钻到单店原因。",
        ],
        "driver_analysis": [
            "继续展开原因。",
            "只看华南区。",
            "切换到去年同期。",
        ],
        "dimension_comparison": [
            "继续看管理公司对比。",
            "只看华南区。",
            "切换到品牌维度。",
        ],
        "scope_refinement": [
            "继续收窄到单店。",
            "切换到品牌。",
            "改成去年同期。",
        ],
        "scope_inventory": [
            "继续看各区域在营数量。",
            "切换到品牌维度。",
            "看去年同期在营数量。",
        ],
        "metric_snapshot": [
            "继续展开原因。",
            "切换到去年同期。",
            "只看华南区。",
        ],
        "management_report": [
            "继续看重点酒店和梯队。",
            "切换到去年同期，对比变化是基数问题还是结构问题。",
            "继续下钻收入、利润或成本科目。",
        ],
        "portfolio_overview": [
            "继续看重点酒店。",
            "切换到管理公司维度。",
            "只看华南区。",
        ],
    }
    if analysis_focus in focus_suggestions:
        return focus_suggestions[analysis_focus][:3]
    if analysis_mode == "portfolio_overview":
        suggestions = [
            f"继续下钻 {scope_label} 里拖累组合的酒店名单。",
            "切换到同比变化，观察组合是预算偏差还是同比承压。",
            "继续拆收入质量、客房效率、利润质量和成本效率四层结构。",
        ]
        if portfolio_breakdown:
            suggestions.insert(0, f"优先展开 {portfolio_breakdown[0].get('hotel_name') or '重点酒店'} 的经营明细。")
        return suggestions[:3]
    return [
        f"继续围绕 {metric_name} 展开原因拆解。",
        "切换到同比变化，确认当前波动来自预算差还是同比变化。",
        "补看同区域/同品牌/同档次内部对标样本。",
    ]


def _empty_response(metric: str, risk_text: str, suggestion_text: str) -> dict[str, Any]:
    summary = f"当前未查询到可用于解释 {metric} 的结果。"
    risks = [risk_text]
    suggestions = [suggestion_text]
    return {
        "summary": summary,
        "management_summary": [summary],
        "risks": risks,
        "suggestions": suggestions,
        "report_sections": _build_executive_sections(summary, risks, suggestions),
    }


def _build_peer_insight(rows: list[dict[str, Any]]) -> str | None:
    hotel_rows = [
        row
        for row in rows
        if row.get("hotel_name") and (isinstance(row.get("diff_value"), (int, float)) or isinstance(row.get("diff_rate"), (int, float)))
    ]
    if len(hotel_rows) < 2:
        return None
    score = lambda item: item.get("diff_value") if isinstance(item.get("diff_value"), (int, float)) else item.get("diff_rate") or 0
    best = max(hotel_rows, key=score)
    worst = min(hotel_rows, key=score)
    area = best.get("area") or worst.get("area") or "当前范围"
    return (
        f"横向看，{area}内缺口相对较小的是 {best.get('hotel_name')}（差额 {_format_amount(best.get('diff_value'))}，差异率 {_format_percent(best.get('diff_rate'))}），"
        f"缺口最大的是 {worst.get('hotel_name')}（差额 {_format_amount(worst.get('diff_value'))}，差异率 {_format_percent(worst.get('diff_rate'))}）。"
    )


def _metric_label(metric: str) -> str:
    return {
        "OPERATING_PROFIT": "经营利润（GOP）",
        "OWNER_PROFIT": "NOP业主净利润",
        "TOTAL_INCOME": "总收入",
        "REVPAR": "每房收益",
    }.get(metric, metric)


def _direction_label(parsed_intent: dict[str, Any]) -> str:
    compare_mode = parsed_intent.get("compare_mode")
    if compare_mode == "budget":
        return "实际值减预算值"
    if compare_mode == "yoy":
        return "实际值减去年同期"
    return "实际值减对比值"


def _compare_scope_label(parsed_intent: dict[str, Any] | None) -> str:
    compare_mode = parsed_intent.get("compare_mode") if isinstance(parsed_intent, dict) else None
    if compare_mode == "budget":
        return "预算"
    if compare_mode == "yoy":
        return "去年同期"
    if compare_mode == "actual":
        return "当前口径"
    return "对比口径"


def _valid_diff_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if isinstance(row.get("diff_value"), (int, float)) or isinstance(row.get("diff_rate"), (int, float))]


def _format_hotel_row(row: dict[str, Any]) -> str:
    hotel_name = row.get("hotel_name") or "未知酒店"
    actual_value = _format_amount(row.get("actual_value"))
    compare_value = _format_amount(row.get("compare_value"))
    diff_value = _format_amount(row.get("diff_value"))
    diff_rate = _format_percent(row.get("diff_rate"))
    return f"{hotel_name}：实际 {actual_value}，对比 {compare_value}，差额 {diff_value}，差异率 {diff_rate}"


def _portfolio_breakdown_text(rows: list[dict[str, Any]]) -> str | None:
    valid_rows = _valid_diff_rows(rows)
    if not valid_rows:
        return None
    best = max(valid_rows, key=lambda item: item.get("diff_value") if isinstance(item.get("diff_value"), (int, float)) else -10**12)
    worst = min(valid_rows, key=lambda item: item.get("diff_value") if isinstance(item.get("diff_value"), (int, float)) else 10**12)
    return (
        f"组合内拉动较强的是 {best.get('hotel_name')}（差额 {_format_amount(best.get('diff_value'))}，差异率 {_format_percent(best.get('diff_rate'))}）；"
        f"拖累较明显的是 {worst.get('hotel_name')}（差额 {_format_amount(worst.get('diff_value'))}，差异率 {_format_percent(worst.get('diff_rate'))}）。"
    )


def _portfolio_outlier_text(outliers: dict[str, Any] | None) -> str | None:
    if not isinstance(outliers, dict):
        return None

    def hotel_line(bucket: str, side: str, label: str) -> str | None:
        item = outliers.get(bucket, {}).get(side) if isinstance(outliers.get(bucket), dict) else None
        if not isinstance(item, dict):
            return None
        hotel_name = item.get("hotel_name")
        if not hotel_name:
            return None
        if bucket == "cost":
            value = _format_amount(item.get("people_cost_actual"))
            return f"{label}{hotel_name}（人工成本 {_format_amount(item.get('people_cost_actual'))}）"
        if bucket == "profit":
            return (
                f"{label}{hotel_name}（NOP业主净利润 {_format_amount(item.get('owner_profit_actual'))}；"
                f"GOP {_format_amount(item.get('operating_profit_actual'))}）"
            )
        return f"{label}{hotel_name}（差额 {_format_amount(item.get('diff_value'))}）"

    lines = [
        hotel_line("income", "best", "收入拉动较强的是 "),
        hotel_line("income", "worst", "收入拖累较明显的是 "),
        hotel_line("profit", "best", "NOP业主净利润表现较强的是 "),
        hotel_line("profit", "worst", "NOP业主净利润承压较明显的是 "),
        hotel_line("cost", "worst", "人工成本偏高的是 "),
    ]
    lines = [item for item in lines if item]
    return "；".join(lines) + "。" if lines else None


def _build_explain_response(metric: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    top_rows = rows[:3]
    if not top_rows:
        return {
            "drivers": [],
            **_empty_response(metric, "当前无法确认波动来源，管理判断可能缺少依据。", "请确认时间范围、酒店范围或指标口径后重试。"),
        }

    drivers = []
    for row in top_rows:
        account_name = row.get("account_name") or row.get("dept") or "关键科目"
        diff_rate = _format_percent(row.get("diff_rate"))
        diff_value = row.get("diff_value") or 0
        direction = "偏高" if diff_value > 0 else "偏低"
        amount_text = _format_amount(abs(diff_value)) if isinstance(diff_value, (int, float)) else "N/A"
        drivers.append(
            {
                "name": account_name,
                "impact": direction,
                "evidence": f"{account_name} 较对比值{direction} {diff_rate}，影响金额约 {amount_text}",
            }
        )

    key_driver_names = "、".join(item["name"] for item in drivers[:2])
    summary = f"已完成 {metric} 的归因分析，当前波动主要集中在 {key_driver_names}。"
    risks = [item["evidence"] for item in drivers]
    suggestions = [
        "优先复核收入下降项是否与入住率、房价或出租房量变化一致。",
        "同步检查人工、能源和餐饮成本是否出现结构性抬升。",
    ]
    return {
        "summary": summary,
        "management_summary": [summary, "建议先按驱动项区分收入端、成本端和费用端，再判断哪一层是主要波动来源。"],
        "drivers": drivers,
        "risks": risks,
        "suggestions": suggestions,
        "report_sections": _build_executive_sections(summary, risks, suggestions),
    }


def _build_metric_response(
    metric: str,
    rows: list[dict[str, Any]],
    parsed_intent: dict[str, Any] | None = None,
    portfolio_breakdown: list[dict[str, Any]] | None = None,
    portfolio_outliers: dict[str, Any] | None = None,
    dimension_breakdowns: dict[str, list[dict[str, Any]]] | None = None,
    peer_benchmark: dict[str, Any] | None = None,
    external_benchmark_requested: bool = False,
) -> dict[str, Any]:
    metric_name = _metric_label(metric)
    if not rows:
        return {
            "key_points": [],
            **_empty_response(metric_name, "当前未取到可分析样本。", "建议先确认酒店、区域、月份和指标口径是否存在数据。"),
        }

    valid_rows = _valid_diff_rows(rows)
    ranked_rows = valid_rows or rows
    negative_rows = [row for row in valid_rows if (row.get("diff_value") if isinstance(row.get("diff_value"), (int, float)) else row.get("diff_rate") or 0) < 0]
    positive_rows = [row for row in valid_rows if (row.get("diff_value") if isinstance(row.get("diff_value"), (int, float)) else row.get("diff_rate") or 0) > 0]
    first = ranked_rows[0]
    query_plan = parsed_intent.get("query_plan") if isinstance(parsed_intent, dict) and isinstance(parsed_intent.get("query_plan"), dict) else {}
    analysis_focus = str(parsed_intent.get("analysis_focus") or "").strip() if isinstance(parsed_intent, dict) else ""
    diff_rate = _format_percent(first.get("diff_rate"))
    hotel_name = first.get("hotel_name", "某酒店")
    actual_value = _format_amount(first.get("actual_value"))
    compare_value = _format_amount(first.get("compare_value"))
    diff_value = _format_amount(first.get("diff_value"))
    peer_insight = _build_peer_insight(rows)
    portfolio_insight = _portfolio_breakdown_text(portfolio_breakdown or [])
    outlier_text = _portfolio_outlier_text(portfolio_outliers)
    dimension_text = _build_dimension_breakdown_text(dimension_breakdowns)
    direction_text = _direction_label(parsed_intent or {})
    compare_scope = _compare_scope_label(parsed_intent)
    if query_plan.get("query_grain") == "portfolio":
        member_count = first.get("portfolio_member_count")
        summary = (
            f"当前已按 {query_plan.get('query_object_label') or hotel_name} 做组合汇总拆解；"
            f"本次组合样本 {member_count or 'N/A'} 家，对{compare_scope}的组合层面差额 {diff_value}，差异率约 {diff_rate}。"
        )
    else:
        summary = (
            f"当前仅基于 {metric_name} 的实际值、对比值、差额和差异率做客观拆解；"
            f"共返回 {len(rows)} 家酒店，样本首项为 {hotel_name}，对{compare_scope}差额 {diff_value}，差异率约 {diff_rate}。"
        )
    if peer_insight:
        summary = f"{summary} {peer_insight}"
    if portfolio_insight:
        summary = f"{summary} {portfolio_insight}"
    if dimension_text and query_plan.get("analysis_mode") == "group_by_dimension_report":
        summary = f"{summary} 已按管理公司/区域维度补充分组汇总。"
    if outlier_text:
        summary = f"{summary} {outlier_text}"
    bundle_code, bundle, template_code = _resolve_template_bundle(parsed_intent, first)
    _, focus_profile = _focus_profile(parsed_intent)
    if template_code == "executive_group_dimension":
        summary = f"已切到分维度视角：{summary}"
    elif template_code == "executive_hotel_snapshot":
        summary = f"已切到单店视角：{summary}"
    elif template_code == "executive_portfolio":
        summary = f"已切到组合视角：{summary}"
    key_points = [
        f"重点酒店：{hotel_name}",
        f"实际值：{actual_value}",
        f"对比值：{compare_value}",
        f"差额：{diff_value}",
        f"口径说明：当前默认按{compare_scope}对比，差额 = {direction_text}；正数通常代表高于{compare_scope}，负数通常代表低于{compare_scope}。",
    ]
    weakest = [_format_hotel_row(row) for row in ranked_rows[:5]]
    if portfolio_breakdown:
        weakest = [_format_hotel_row(row) for row in (portfolio_breakdown or [])[:5]]
    if _has_overview_context(first):
        risks = [
            _build_income_quality_text(first),
            _build_room_efficiency_text(first),
            _build_profit_quality_text(first),
            _build_cost_efficiency_text(first),
            _build_benchmark_text(first, outlier_text or portfolio_insight or peer_insight, peer_benchmark, external_benchmark_requested),
        ]
    else:
        risks = [
            f"当前指标为{metric_name}，实际 {actual_value}，对比 {compare_value}，差额 {diff_value}，差异率 {diff_rate}。若要判断收入质量，需要继续拆到总收入、客房收入、餐饮收入、宴会收入及其他收入结构；当前结果尚未包含这些收入构成。",
            "客房效率需要同时观察入住率、ADR 和 RevPAR：入住率说明出租量，ADR 说明价格质量，RevPAR 体现房价和出租率的综合效率；当前结果未同时返回这三项，不能推断房价策略或出租率贡献。",
            f"利润质量要看经营利润是否跟随收入改善。当前仅能看到{metric_name}本身的差额，尚不能证明收入增量是否转化为经营利润；本次结果中负向样本 {len(negative_rows)} 家，正向样本 {len(positive_rows)} 家。",
            "成本效率需要拆人工、能耗、餐饮成本、渠道费用和费用率。如果收入增长但这些成本费用增速更快，经营利润可能不会同步改善；当前结果尚未包含成本科目。",
            _build_benchmark_text(first, peer_insight, peer_benchmark, external_benchmark_requested),
        ]
    if analysis_focus == "income_structure":
        summary = f"已切换到收入结构拆解：{_build_income_quality_text(first)}"
        risks = [_build_income_quality_text(first)]
    elif analysis_focus == "profit_cost_efficiency":
        summary = f"已切换到利润与成本效率拆解：{_build_profit_quality_text(first)} {_build_cost_efficiency_text(first)}"
        risks = [_build_profit_quality_text(first), _build_cost_efficiency_text(first)]
    elif analysis_focus == "yoy_change":
        summary = f"已切换到去年同期变化观察：{summary}"
    elif analysis_focus == "driver_analysis":
        summary = f"已切换到原因分析：{summary}"
    elif analysis_focus == "dimension_comparison":
        summary = f"已切换到维度比较：{summary}"
    elif analysis_focus == "management_report":
        summary = f"已整理经营摘要：{summary}"
    elif analysis_focus == "scope_refinement":
        summary = f"已收窄观察范围：{summary}"
    elif analysis_focus == "scope_inventory":
        summary = f"已切换到在营酒店数量核对：{summary}"
    management_summary = _build_management_summary(
        metric_name=metric_name,
        parsed_intent=parsed_intent,
        row=first,
        summary=summary,
        portfolio_breakdown=portfolio_breakdown,
        peer_benchmark=peer_benchmark,
        focus_profile=focus_profile,
    )
    suggestions = _build_follow_up_suggestions(metric_name, parsed_intent, portfolio_breakdown, focus_profile)
    return {
        "summary": summary,
        "management_summary": management_summary,
        "key_points": key_points,
        "weakest_hotels": weakest,
        "risks": risks,
        "suggestions": suggestions,
        "_source_row": first,
        "report_sections": _build_report_style_sections_v2(
            summary,
            risks,
            suggestions,
            parsed_intent,
            first,
            portfolio_breakdown,
            portfolio_outliers,
            dimension_breakdowns,
            peer_benchmark,
            external_benchmark_requested,
        ),
    }


def _parse_llm_json(content: str) -> dict | None:
    try:
        data = json.loads(content)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _call_llm_summary(question: str, parsed_intent: dict[str, Any], rows: list[dict[str, Any]], base_result: dict[str, Any]) -> dict | None:
    if not llm_enabled():
        return None

    payload = {
        "question": question,
        "parsed_intent": parsed_intent,
        "sample_rows": rows[:5],
        "base_result": base_result,
    }
    system_prompt = (
        "你是酒店运营数据分析助手，强调客观拆解，不直接下经营好坏结论。"
        "请根据输入输出 JSON，不要输出额外文字。"
        "字段包括 summary, risks, suggestions。"
        "summary 只说明当前数据范围和可观察事实，不要写健康、承压、好坏等结论。"
        "risks 必须按顺序给出五段：收入质量、客房效率、利润质量、成本效率、横向对标。"
        "如果输入数据缺少某维度，必须明确写“当前未取数/当前结果未包含”，不要编造。"
        "suggestions 只写后续需要补齐的数据维度，不要写管理动作或责任建议。"
        "所有金额必须保留千位分隔符。"
    )
    request_body = {
        "model": DEEP_LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=LLM_TIMEOUT) as client:
            response = client.post(f"{LLM_BASE_URL.rstrip('/')}/chat/completions", json=request_body, headers=headers)
            response.raise_for_status()
            body = response.json()
        content = body["choices"][0]["message"]["content"]
    except Exception:
        return None

    return _parse_llm_json(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False))


def _apply_llm_enhancement(question: str, parsed_intent: dict[str, Any], rows: list[dict[str, Any]], result: dict[str, Any]) -> dict[str, Any]:
    if not should_use_llm_enhancement(parsed_intent):
        return {
            **result,
            "llm_enhancement": {
                "used": False,
                "policy": LLM_EXPLANATION_POLICY,
                "reason": "deterministic_explanation_first",
            },
        }

    llm_result = _call_llm_summary(question, parsed_intent, rows, result)
    if not llm_result:
        return {
            **result,
            "llm_enhancement": {
                "used": False,
                "policy": LLM_EXPLANATION_POLICY,
                "reason": "llm_unavailable_or_timeout",
            },
        }

    summary = str(llm_result.get("summary") or result.get("summary") or "")
    risks = llm_result.get("risks")
    suggestions = llm_result.get("suggestions")
    if not isinstance(risks, list) or not risks:
        risks = result.get("risks", [])
    if not isinstance(suggestions, list) or not suggestions:
        suggestions = result.get("suggestions", [])

    enhanced = dict(result)
    enhanced["summary"] = summary
    if not enhanced.get("management_summary"):
        enhanced["management_summary"] = [summary]
    enhanced["risks"] = [str(item) for item in risks]
    enhanced["suggestions"] = [str(item) for item in suggestions]
    enhanced["report_sections"] = _build_executive_sections(enhanced["summary"], enhanced["risks"], enhanced["suggestions"])
    enhanced["llm_enhancement"] = {
        "used": True,
        "policy": LLM_EXPLANATION_POLICY,
        "model": DEEP_LLM_MODEL,
    }
    return enhanced


@app.post("/api/v1/explain/metric")
def explain(payload: Req):
    rows = payload.rows or []
    metric = payload.parsed_intent.get("metric_code", "指标")
    intent = payload.parsed_intent.get("intent", "query")
    result = (
        _build_explain_response(metric, rows)
        if intent == "explain"
        else _build_metric_response(
            metric,
            rows,
            payload.parsed_intent,
            payload.portfolio_breakdown,
            payload.portfolio_outliers,
            payload.dimension_breakdowns,
            payload.peer_benchmark,
            payload.external_benchmark_requested,
        )
    )
    enhanced = _apply_llm_enhancement(payload.question, payload.parsed_intent, rows, result)
    return _attach_structured_outputs(enhanced, payload.parsed_intent)


@app.post("/api/v1/explain/report")
def build_report(payload: ReportReq):
    metric = payload.parsed_intent.get("metric_code", "指标")
    intent = payload.parsed_intent.get("intent", "query")
    result = (
        _build_explain_response(metric, payload.rows)
        if intent == "explain"
        else _build_metric_response(
            metric,
            payload.rows,
            payload.parsed_intent,
            payload.portfolio_breakdown,
            payload.portfolio_outliers,
            payload.dimension_breakdowns,
            payload.peer_benchmark,
            payload.external_benchmark_requested,
        )
    )
    result = _apply_llm_enhancement(payload.question, payload.parsed_intent, payload.rows, result)
    result = _attach_structured_outputs(result, payload.parsed_intent)
    sections = result.get("report_sections", [])
    markdown = "\n\n".join(f"## {item['title']}\n{item['content']}" for item in sections)
    return {
        "summary": result.get("summary"),
        "analysis_blocks": result.get("analysis_blocks", []),
        "narrative_brief": result.get("narrative_brief", {}),
        "report_sections": sections,
        "report_markdown": markdown,
    }
