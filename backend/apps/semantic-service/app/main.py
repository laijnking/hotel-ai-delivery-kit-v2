import json
import os
import re
from functools import lru_cache
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

try:
    import duckdb
except Exception:  # pragma: no cover - optional runtime dependency
    duckdb = None

app = FastAPI(title="semantic-service")
CONFIG = Path(__file__).resolve().parents[3] / "configs" / "semantic_mapping.yaml"
ENTITY_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "entity_catalog.yaml"
SKILL_REGISTRY = Path(__file__).resolve().parents[3] / "skills" / "registry.yaml"
WAREHOUSE_DIR = Path(os.getenv("WAREHOUSE_DIR", Path(__file__).resolve().parents[3] / "runtime" / "warehouse"))
DUCKDB_PATH = Path(os.getenv("WAREHOUSE_DUCKDB_PATH", WAREHOUSE_DIR / "hotel_warehouse.duckdb"))
_SPACE_RE = re.compile(r"\s+")
_TIME_SCOPE_RE = re.compile(r"^\d{6}$")
_MONTH_IN_QUESTION_RE = re.compile(r"(?<!\d)(1[0-2]|0?[1-9])\s*月")
_YEAR_MONTH_IN_QUESTION_RE = re.compile(r"(20\d{2})\s*年\s*(1[0-2]|0?[1-9])\s*月")
_AREA_PATTERN = re.compile(r"(华南区|华东区|华北区|西南区|华中区|中南区|东北区|西北区)")
_HOTEL_PATTERN = re.compile(r"([\u4e00-\u9fa5A-Za-z0-9]{2,30}?(?:酒店|假日|文华|万丽|柏悦|君悦|希尔顿|嘉华|丽思卡尔顿|公寓))")
_HOTEL_PREFIX_RE = re.compile(r"^(?:请|麻烦|帮我|帮忙|给我|看一下|看下|看一看|看看|看|分析一下|分析|查一下|查询|了解一下|说说|讲讲)+")
_HOTEL_TRAILING_RE = re.compile(r"(?:本月|当月|这个月|上月|去年同期|同比|预算|经营情况|经营状况|表现|情况|怎么样|如何|咋样|[0-9]{1,2}月|20\d{2}年.*)$")
_METRIC_LABELS = {
    "OPERATING_PROFIT": "经营利润",
    "TOTAL_INCOME": "总收入",
    "REVPAR": "每房收益",
    "OPERATING_HOTEL_COUNT": "在营酒店数",
}
_BUSINESS_OVERVIEW_TERMS = ("经营情况", "经营状况", "经营表现", "经营概况", "营业情况", "整体情况", "总体情况")
_SITUATION_TERMS = ("情况", "怎么样", "如何", "咋样", "表现")
_BUILDER_TERMS = ("原万达", "自建")
_BRAND_LEVEL_TERMS = ("奢华级", "豪华五星级", "标准五星级", "准五星级", "高端四星级", "中端级")
_CITY_LEVEL_TERMS = ("一线城市", "新一线城市", "二线城市", "三线城市", "四线城市", "五线城市")
_DEPARTMENT_TERMS = ("客房部", "餐饮部", "管理部门", "固定成本", "其他营收部门")
_ACCOUNT_TERMS = (
    "收入",
    "成本",
    "利润",
    "经营指标",
    "薪资及福利",
    "酒店薪资及福利",
    "客房部收入",
    "餐饮部收入",
    "收入合计",
    "营业成本",
    "营业毛利",
    "经营净利润",
    "业主利润",
    "实际入住房间数",
    "每间可卖房收入",
    "酒水成本",
    "食品成本",
    "能源费用",
)
_HOTEL_GROUP_PATTERN = re.compile(
    r"(?:查一下|看一下|看下|分析一下|了解一下|帮我|请|麻烦)?"
    r"(?:(?:20\d{2}年)?\d{1,2}月(?:份)?)?"
    r"([\u4e00-\u9fa5A-Za-z0-9（）()]{2,20}?)"
    r"(?:所有|全部|整个|全部的)(?:酒店|门店|项目)"
)
_PORTFOLIO_TERMS = ("总体", "整体", "总体经营", "整体经营", "汇总", "汇总情况")
_ALL_SCOPE_TERMS = ("所有", "全部", "全部的", "整个", "全量")
_COMPANY_ROOT_TERMS = ("富力", "富力集团", "公司", "集团", "本公司", "全公司")

LLM_BASE_URL = os.getenv("QWEN_API_BASE_URL", "").strip()
LLM_API_KEY = os.getenv("QWEN_API_KEY", "").strip()
FAST_LLM_MODEL = os.getenv("QWEN_FAST_MODEL", "").strip() or os.getenv("QWEN_MODEL", "").strip()
DEEP_LLM_MODEL = os.getenv("QWEN_DEEP_MODEL", "").strip() or os.getenv("QWEN_MODEL", "").strip()
LLM_TIMEOUT = float(os.getenv("QWEN_TIMEOUT", "12"))
LLM_PARSE_POLICY = os.getenv("QWEN_PARSE_POLICY", "auto").strip().lower()
LLM_PARSE_CONFIDENCE_THRESHOLD = float(os.getenv("QWEN_PARSE_CONFIDENCE_THRESHOLD", "0.82"))


class Req(BaseModel):
    question: str = Field(..., min_length=2)
    time_scope: str | None = None


@app.get("/health")
def health():
    entity_catalog = load_entity_catalog()
    skills = load_skills()
    return {
        "status": "ok",
        "llm_enabled": llm_enabled(),
        "fast_model": FAST_LLM_MODEL or None,
        "deep_model": DEEP_LLM_MODEL or None,
        "entity_counts": {name: len(values) for name, values in entity_catalog.items()},
        "runtime_entity_source": runtime_entity_source_available(),
        "skill_count": len(skills),
    }


@lru_cache(maxsize=1)
def load_config() -> dict:
    with open(CONFIG, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise HTTPException(status_code=500, detail="semantic mapping config is invalid")
    return cfg


@lru_cache(maxsize=1)
def load_skills() -> list[dict]:
    if not SKILL_REGISTRY.exists():
        return []
    with open(SKILL_REGISTRY, "r", encoding="utf-8") as f:
        registry = yaml.safe_load(f) or {}
    items = registry.get("skills", []) if isinstance(registry, dict) else []
    if not isinstance(items, list):
        return []

    skills: list[dict] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("enabled", True):
            continue
        skill_file = SKILL_REGISTRY.parent / str(item.get("file", "")).strip()
        if not skill_file.exists():
            continue
        with open(skill_file, "r", encoding="utf-8") as f:
            skill = yaml.safe_load(f) or {}
        if not isinstance(skill, dict) or not skill.get("enabled", True):
            continue
        skill.setdefault("id", item.get("id"))
        skill.setdefault("version", item.get("version"))
        skills.append(skill)
    return skills


def match_skill(question_norm: str) -> dict | None:
    candidates: list[tuple[int, dict, str]] = []
    for skill in load_skills():
        triggers = skill.get("triggers", [])
        if not isinstance(triggers, list):
            continue
        for trigger in triggers:
            trigger_norm = normalize_text(str(trigger))
            if trigger_norm and trigger_norm in question_norm:
                candidates.append((len(trigger_norm), skill, str(trigger)))
    if not candidates:
        return None
    _, skill, trigger = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
    matched = dict(skill)
    matched["matched_trigger"] = trigger
    return matched


def _clean_entity_line(line: str, header_prefix: str) -> str:
    item = line.replace("\ufeff", "").strip()
    if not item or item == header_prefix:
        return ""
    if item.endswith("：") and item == header_prefix:
        return ""
    return item


def runtime_entity_source_available() -> bool:
    return bool(duckdb is not None and DUCKDB_PATH.exists())


def _fetch_runtime_entities() -> dict[str, list[str]]:
    if not runtime_entity_source_available():
        return {}

    sql_map = {
        "hotel": """
            SELECT DISTINCT TRIM(hotel_name_s) AS value
            FROM dim_allhotel_slcp
            WHERE hotel_name_s IS NOT NULL AND TRIM(hotel_name_s) <> ''
        """,
        "area": """
            SELECT DISTINCT TRIM(area) AS value
            FROM dim_allhotel_slcp
            WHERE area IS NOT NULL AND TRIM(area) <> ''
        """,
        "brand": """
            SELECT DISTINCT TRIM(brand_child) AS value
            FROM dim_allhotel_slcp
            WHERE brand_child IS NOT NULL AND TRIM(brand_child) <> ''
        """,
        "brand_child": """
            SELECT DISTINCT TRIM(brand_child) AS value
            FROM dim_allhotel_slcp
            WHERE brand_child IS NOT NULL AND TRIM(brand_child) <> ''
        """,
        "manage_corp": """
            SELECT DISTINCT TRIM(manage_corp) AS value
            FROM wddm_dim_overview_cockpit_f
            WHERE manage_corp IS NOT NULL AND TRIM(manage_corp) <> ''
        """,
        "city": """
            SELECT DISTINCT TRIM(hotel_city) AS value
            FROM dim_allhotel_slcp
            WHERE hotel_city IS NOT NULL AND TRIM(hotel_city) <> ''
        """,
        "builder": """
            SELECT DISTINCT TRIM(Builder) AS value
            FROM dim_allhotel_slcp
            WHERE Builder IS NOT NULL AND TRIM(Builder) <> ''
        """,
        "brand_level": """
            SELECT DISTINCT TRIM(brand_level) AS value
            FROM dim_allhotel_slcp
            WHERE brand_level IS NOT NULL AND TRIM(brand_level) <> ''
        """,
        "city_level": """
            SELECT DISTINCT TRIM(city_level) AS value
            FROM dim_allhotel_slcp
            WHERE city_level IS NOT NULL AND TRIM(city_level) <> ''
        """,
        "department": """
            SELECT DISTINCT TRIM(Dept) AS value
            FROM vw_pnl_fact
            WHERE Dept IS NOT NULL AND TRIM(Dept) <> ''
        """,
        "account": """
            SELECT DISTINCT value
            FROM (
                SELECT TRIM(account_name) AS value FROM vw_pnl_fact
                UNION
                SELECT TRIM(account_nameF01) AS value FROM vw_pnl_fact
                UNION
                SELECT TRIM(account_nameF02) AS value FROM vw_pnl_fact
                UNION
                SELECT TRIM(accountName) AS value FROM vw_pnl_fact
            )
            WHERE value IS NOT NULL AND value <> ''
        """,
    }
    catalog: dict[str, list[str]] = {}
    assert duckdb is not None
    with duckdb.connect(str(DUCKDB_PATH), read_only=True) as conn:
        for entity_name, sql in sql_map.items():
            try:
                rows = conn.execute(sql).fetchall()
            except Exception:
                rows = []
            values: list[str] = []
            for row in rows:
                item = str(row[0]).strip() if row and row[0] is not None else ""
                if item and item not in values:
                    values.append(item)
            catalog[entity_name] = values
    return catalog


def _fetch_runtime_scope_graph() -> list[dict[str, str]]:
    if not runtime_entity_source_available():
        return []

    sql = """
        WITH latest AS (
            SELECT MAX(calmonth) AS calmonth
            FROM wddm_dim_overview_cockpit_f
        )
        SELECT DISTINCT
            TRIM(COALESCE(s.hotel_name_s, o.hotel_name)) AS hotel_name,
            TRIM(COALESCE(s.area, o.from_area)) AS area,
            TRIM(COALESCE(o.manage_corp, s.brand)) AS manage_corp,
            TRIM(COALESCE(o.hotel_brand, s.brand_child)) AS brand_child,
            TRIM(s.Builder) AS builder,
            TRIM(s.brand_level) AS brand_level,
            TRIM(s.city_level) AS city_level
        FROM wddm_dim_overview_cockpit_f o
        LEFT JOIN dim_allhotel_slcp s
          ON s.hotel_name_f = o.hotel_name
        JOIN latest l
          ON o.calmonth = l.calmonth
        WHERE TRIM(COALESCE(s.hotel_name_s, o.hotel_name)) <> ''
    """
    rows: list[dict[str, str]] = []
    assert duckdb is not None
    with duckdb.connect(str(DUCKDB_PATH), read_only=True) as conn:
        try:
            result = conn.execute(sql)
        except Exception:
            return []
        columns = [str(item[0]) for item in (result.description or [])]
        for raw_row in result.fetchall():
            node: dict[str, str] = {}
            for index, column in enumerate(columns):
                value = raw_row[index] if index < len(raw_row) else None
                node[column] = str(value).strip() if value is not None else ""
            if node.get("hotel_name"):
                rows.append(node)
    return rows


@lru_cache(maxsize=1)
def load_entity_catalog() -> dict[str, list[str]]:
    if not ENTITY_CONFIG.exists():
        return {}
    with open(ENTITY_CONFIG, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    entities = cfg.get("entities", {}) if isinstance(cfg, dict) else {}
    if not isinstance(entities, dict):
        return {}

    runtime_catalog = _fetch_runtime_entities()
    catalog: dict[str, list[str]] = {}
    for entity_name, entity_cfg in entities.items():
        if not isinstance(entity_cfg, dict):
            continue
        values: list[str] = list(runtime_catalog.get(str(entity_name), []))
        source = Path(str(entity_cfg.get("source", "")).strip())
        header_prefix = str(entity_cfg.get("header_prefix", "")).strip()
        if source.exists():
            with open(source, "r", encoding="utf-8-sig") as file:
                for raw_line in file:
                    item = _clean_entity_line(raw_line, header_prefix)
                    if item and item not in values:
                        values.append(item)
        catalog[str(entity_name)] = values

    for entity_name, values in runtime_catalog.items():
        catalog.setdefault(entity_name, values)
    return catalog


@lru_cache(maxsize=1)
def load_scope_graph() -> list[dict[str, str]]:
    return _fetch_runtime_scope_graph()


def match_catalog_entities(question: str, entity_name: str) -> list[str]:
    values = load_entity_catalog().get(entity_name, [])
    if not values:
        return []
    question_norm = normalize_text(question)
    matches: list[str] = []
    for value in sorted(values, key=lambda item: len(normalize_text(item)), reverse=True):
        value_norm = normalize_text(value)
        if not value_norm:
            continue
        alias_norms = [value_norm]
        if entity_name == "hotel" and not value.endswith(("酒店", "公寓")):
            alias_norms.append(f"{value_norm}酒店")
        if any(alias in question_norm for alias in alias_norms):
            if value not in matches:
                matches.append(value)
            question_norm = question_norm.replace(value_norm, "")
            for alias in alias_norms:
                question_norm = question_norm.replace(alias, "")
    return matches


def match_terms(question_norm: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if normalize_text(term) in question_norm]


def normalize_manage_corp(value: str) -> str:
    text = value.strip()
    if text == "万达":
        return "万达品牌"
    return text


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return _SPACE_RE.sub("", value).casefold()


def normalize_time_scope(time_scope: str | None, defaults: dict, warnings: list[str], question: str = "") -> str:
    candidate = (time_scope or "").strip()
    if candidate and _TIME_SCOPE_RE.fullmatch(candidate):
        base_year = candidate[:4]
    else:
        fallback = str(defaults.get("time_scope", "202601")).strip() or "202601"
        base_year = fallback[:4]
        if candidate:
            warnings.append(f"invalid time_scope {candidate!r}, fallback to {fallback}")

    year_month = _YEAR_MONTH_IN_QUESTION_RE.search(question)
    if year_month:
        return f"{year_month.group(1)}{int(year_month.group(2)):02d}"

    month = _MONTH_IN_QUESTION_RE.search(question)
    if month:
        return f"{base_year}{int(month.group(1)):02d}"

    if candidate and _TIME_SCOPE_RE.fullmatch(candidate):
        return candidate
    return str(defaults.get("time_scope", "202601")).strip() or "202601"


def iter_keyword_map(section: object) -> list[tuple[str, object]]:
    if isinstance(section, dict):
        return [(str(key), value) for key, value in section.items()]
    return []


def extract_metric_code(cfg: dict, question_norm: str) -> tuple[str, str | None]:
    if re.search(r"(多少|几|总共|合计).{0,8}家?酒店.{0,8}(在营|运营|营业|开业)", question_norm) or re.search(
        r"(在营|运营|营业|开业).{0,8}酒店.{0,8}(多少|几|总共|合计)", question_norm
    ):
        return "OPERATING_HOTEL_COUNT", "在营酒店数问法"
    synonyms = iter_keyword_map(cfg.get("synonyms", {}))
    synonyms.sort(key=lambda item: len(normalize_text(item[0])), reverse=True)
    for keyword, value in synonyms:
        keyword_norm = normalize_text(keyword)
        if not keyword_norm or keyword_norm not in question_norm:
            continue
        metric_code = str(value).strip()
        if metric_code:
            return metric_code, keyword

    if any(normalize_text(term) in question_norm for term in _BUSINESS_OVERVIEW_TERMS):
        return "OPERATING_PROFIT", "经营情况"

    defaults = cfg.get("defaults", {})
    return str(defaults.get("default_metric_code", "TOTAL_INCOME")).strip() or "TOTAL_INCOME", None


def is_situation_question(question_norm: str) -> bool:
    return any(normalize_text(term) in question_norm for term in _SITUATION_TERMS)


def extract_intent(cfg: dict, question_norm: str) -> tuple[str, str | None]:
    intents = iter_keyword_map(cfg.get("intents", {}))
    intents.sort(key=lambda item: len(normalize_text(item[0])), reverse=True)
    for keyword, value in intents:
        keyword_norm = normalize_text(keyword)
        if keyword_norm and keyword_norm in question_norm:
            return str(value).strip() or "query", keyword
    defaults = cfg.get("defaults", {})
    return str(defaults.get("intent", "query")).strip() or "query", None


def extract_compare_mode(cfg: dict, question_norm: str) -> tuple[str, str | None]:
    compare_keywords = cfg.get("compare_keywords", {})
    if isinstance(compare_keywords, dict):
        for mode in ("budget", "yoy"):
            keywords = compare_keywords.get(mode, [])
            for keyword in keywords if isinstance(keywords, list) else []:
                keyword_norm = normalize_text(str(keyword))
                if keyword_norm and keyword_norm in question_norm:
                    return mode, str(keyword)
    return str(cfg.get("defaults", {}).get("compare_mode", "actual")).strip() or "actual", None


def extract_variance_direction(question_norm: str) -> str:
    below_terms = (
        "未达",
        "未达预算",
        "低于预算",
        "不达预算",
        "下滑",
        "下降",
        "减少",
        "低于",
        "偏低",
        "差",
        "弱",
    )
    above_terms = (
        "高于预算",
        "超过预算",
        "超预算",
        "增长",
        "提升",
        "高于",
        "偏高",
        "好",
        "强",
    )
    if any(term in question_norm for term in below_terms):
        return "below"
    if any(term in question_norm for term in above_terms):
        return "above"
    return "all"


def clean_hotel_name(value: str) -> str:
    hotel = value.strip(" ，。？！?：:")
    hotel = _HOTEL_PREFIX_RE.sub("", hotel)
    hotel = _HOTEL_TRAILING_RE.sub("", hotel).strip(" ，。？！?：:")
    return hotel


def extract_scope(question: str) -> dict[str, list[str]]:
    question_norm = normalize_text(question)
    requested_areas: list[str] = match_catalog_entities(question, "area")
    for match in _AREA_PATTERN.findall(question):
        if match not in requested_areas:
            requested_areas.append(match)

    requested_hotels: list[str] = match_catalog_entities(question, "hotel")
    if not requested_hotels:
        for match in _HOTEL_PATTERN.finditer(question):
            raw_hotel = match.group(1)
            suffix = question[match.end() : match.end() + 2]
            if suffix == "品牌":
                continue
            if suffix in {"酒店", "公寓"} and not raw_hotel.endswith(suffix):
                raw_hotel = f"{raw_hotel}{suffix}"
            hotel = clean_hotel_name(raw_hotel)
            if any(token in hotel for token in ("哪些酒店", "哪些", "本月", "预算", "同比", "经营利润", "总收入", "每房收益", "奢华级酒店", "五星级酒店", "所有酒店", "全部酒店", "整个酒店")):
                continue
            if hotel and hotel not in requested_hotels:
                requested_hotels.append(hotel)

    requested_manage_corps = [normalize_manage_corp(item) for item in match_catalog_entities(question, "manage_corp")]
    requested_brand_children = match_catalog_entities(question, "brand_child") or match_catalog_entities(question, "brand")
    requested_builders = match_catalog_entities(question, "builder") or match_terms(question_norm, _BUILDER_TERMS)
    requested_brand_levels = match_catalog_entities(question, "brand_level") or match_terms(question_norm, _BRAND_LEVEL_TERMS)
    requested_city_levels = match_catalog_entities(question, "city_level") or match_terms(question_norm, _CITY_LEVEL_TERMS)
    requested_departments = match_catalog_entities(question, "department") or match_terms(question_norm, _DEPARTMENT_TERMS)
    requested_accounts = match_catalog_entities(question, "account") or match_terms(question_norm, _ACCOUNT_TERMS)

    return {
        "requested_areas": requested_areas,
        "requested_hotels": requested_hotels,
        "requested_manage_corps": requested_manage_corps,
        "requested_brand_children": requested_brand_children,
        "requested_builders": requested_builders,
        "requested_brand_levels": requested_brand_levels,
        "requested_city_levels": requested_city_levels,
        "requested_departments": requested_departments,
        "requested_accounts": requested_accounts,
    }


def find_hotel_group_token(question: str, scope: dict[str, list[str]]) -> str | None:
    if scope.get("requested_hotels"):
        return None
    match = _HOTEL_GROUP_PATTERN.search(question)
    if not match:
        return None
    candidate = clean_hotel_name(match.group(1))
    candidate = re.sub(r"^(?:20\d{2}年)?\d{1,2}月(?:份)?", "", candidate).strip()
    candidate = re.sub(r"(?:查一下|看一下|看下|分析一下|了解一下|帮我|请|麻烦)$", "", candidate).strip()
    if not candidate or len(candidate) < 2:
        return None
    if candidate in {"哪些", "本月", "这个月", "经营", "总体", "整体"}:
        return None
    return candidate


def resolve_hotel_group(question: str, scope: dict[str, list[str]]) -> dict[str, object] | None:
    token = find_hotel_group_token(question, scope)
    if not token:
        return None
    token_norm = normalize_text(token)
    if not token_norm:
        return None
    if token_norm in {normalize_text(term) for term in _COMPANY_ROOT_TERMS}:
        members: list[str] = []
        for node in load_scope_graph():
            hotel_name = str(node.get("hotel_name") or "").strip()
            if hotel_name and hotel_name not in members:
                members.append(hotel_name)
        if not members:
            members = list(load_entity_catalog().get("hotel", []))
        return {
            "label": "公司全部酒店",
            "group_token": token,
            "member_hotels": members,
            "member_count": len(members),
            "resolution_basis": "company_root_all_hotels",
            "use_group_token_as_filter": False,
        }
    hotels = load_entity_catalog().get("hotel", [])
    members: list[str] = []
    for hotel in hotels:
        hotel_norm = normalize_text(hotel)
        if token_norm and token_norm in hotel_norm and hotel not in members:
            members.append(hotel)
    if len(members) < 2:
        return None
    return {
        "label": f"{token}体系酒店集合",
        "group_token": token,
        "member_hotels": members,
        "member_count": len(members),
        "resolution_basis": "hotel_name_contains_token",
        "use_group_token_as_filter": True,
    }


def _matches_scope_value(node_value: str, requested_values: list[str]) -> bool:
    if not requested_values:
        return True
    node_norm = normalize_text(node_value)
    if not node_norm:
        return False
    for value in requested_values:
        value_norm = normalize_text(str(value))
        if value_norm and (value_norm == node_norm or value_norm in node_norm or node_norm in value_norm):
            return True
    return False


def resolve_scope_collection(result: dict) -> dict[str, object] | None:
    if result.get("requested_hotels"):
        return None

    graph = load_scope_graph()
    if not graph:
        return None

    requested_areas = [str(item).strip() for item in result.get("requested_areas", []) if str(item).strip()]
    requested_manage_corps = [str(item).strip() for item in result.get("requested_manage_corps", []) if str(item).strip()]
    requested_brand_children = [str(item).strip() for item in result.get("requested_brand_children", []) if str(item).strip()]
    requested_builders = [str(item).strip() for item in result.get("requested_builders", []) if str(item).strip()]
    requested_brand_levels = [str(item).strip() for item in result.get("requested_brand_levels", []) if str(item).strip()]
    requested_city_levels = [str(item).strip() for item in result.get("requested_city_levels", []) if str(item).strip()]

    has_scope = any(
        (
            requested_areas,
            requested_manage_corps,
            requested_brand_children,
            requested_builders,
            requested_brand_levels,
            requested_city_levels,
        )
    )
    if not has_scope:
        return None

    members: list[str] = []
    for node in graph:
        if not _matches_scope_value(node.get("area", ""), requested_areas):
            continue
        if not _matches_scope_value(node.get("manage_corp", ""), requested_manage_corps):
            continue
        if not _matches_scope_value(node.get("brand_child", ""), requested_brand_children):
            continue
        if not _matches_scope_value(node.get("builder", ""), requested_builders):
            continue
        if not _matches_scope_value(node.get("brand_level", ""), requested_brand_levels):
            continue
        if not _matches_scope_value(node.get("city_level", ""), requested_city_levels):
            continue
        hotel_name = str(node.get("hotel_name") or "").strip()
        if hotel_name and hotel_name not in members:
            members.append(hotel_name)

    if not members:
        return None

    scope_parts: list[str] = []
    if requested_areas:
        scope_parts.extend(requested_areas)
    if requested_manage_corps:
        scope_parts.extend(requested_manage_corps)
    if requested_brand_children:
        scope_parts.extend(requested_brand_children)
    if requested_builders:
        scope_parts.extend(requested_builders)
    if requested_brand_levels:
        scope_parts.extend(requested_brand_levels)
    if requested_city_levels:
        scope_parts.extend(requested_city_levels)

    if requested_areas:
        scope_type = "area_scope"
    elif requested_manage_corps:
        scope_type = "manage_corp_scope"
    elif requested_brand_children:
        scope_type = "brand_scope"
    else:
        scope_type = "filtered_scope"

    return {
        "scope_type": scope_type,
        "label": " / ".join(scope_parts) or "当前范围酒店集合",
        "member_hotels": members,
        "member_count": len(members),
        "resolution_basis": "runtime_scope_graph",
        "applied_filters": {
            "areas": requested_areas,
            "manage_corps": requested_manage_corps,
            "brand_children": requested_brand_children,
            "builders": requested_builders,
            "brand_levels": requested_brand_levels,
            "city_levels": requested_city_levels,
        },
    }


def build_resolved_entities(question: str, result: dict) -> dict[str, object]:
    hotel_group = resolve_hotel_group(question, result)
    scope_collection = resolve_scope_collection(result)
    return {
        "hotels": list(result.get("requested_hotels", [])),
        "areas": list(result.get("requested_areas", [])),
        "manage_corps": list(result.get("requested_manage_corps", [])),
        "brand_children": list(result.get("requested_brand_children", [])),
        "builders": list(result.get("requested_builders", [])),
        "brand_levels": list(result.get("requested_brand_levels", [])),
        "city_levels": list(result.get("requested_city_levels", [])),
        "departments": list(result.get("requested_departments", [])),
        "accounts": list(result.get("requested_accounts", [])),
        "hotel_group": hotel_group,
        "scope_collection": scope_collection,
    }


def is_portfolio_question(question_norm: str) -> bool:
    return any(normalize_text(term) in question_norm for term in _PORTFOLIO_TERMS) or any(
        normalize_text(term) in question_norm for term in _ALL_SCOPE_TERMS
    )


def build_query_plan(question: str, result: dict) -> dict[str, object]:
    question_norm = normalize_text(question)
    resolved_entities = result.get("resolved_entities") if isinstance(result.get("resolved_entities"), dict) else build_resolved_entities(question, result)
    hotel_group = resolved_entities.get("hotel_group") if isinstance(resolved_entities.get("hotel_group"), dict) else None
    scope_collection = resolved_entities.get("scope_collection") if isinstance(resolved_entities.get("scope_collection"), dict) else None
    areas = list(result.get("requested_areas", []))
    hotels = list(result.get("requested_hotels", []))
    manage_corps = list(result.get("requested_manage_corps", []))
    brand_children = list(result.get("requested_brand_children", []))
    intent = str(result.get("intent", "query")).strip() or "query"
    metric_code = str(result.get("metric_code", "TOTAL_INCOME")).strip() or "TOTAL_INCOME"
    metric_name = _METRIC_LABELS.get(metric_code, metric_code)
    portfolio_like = is_portfolio_question(question_norm)

    if hotel_group:
        object_type = "hotel_group"
        object_label = str(hotel_group.get("label") or "酒店集合")
        query_grain = "portfolio"
    elif scope_collection and (portfolio_like or int(scope_collection.get("member_count") or 0) > 1):
        object_type = str(scope_collection.get("scope_type") or "filtered_scope")
        object_label = str(scope_collection.get("label") or "当前范围酒店集合")
        query_grain = "portfolio" if metric_code != "OPERATING_HOTEL_COUNT" else "scope_stat"
    elif len(hotels) == 1 and not portfolio_like:
        object_type = "single_hotel"
        object_label = hotels[0]
        query_grain = "hotel"
    elif areas:
        object_type = "area_scope"
        object_label = " / ".join(areas)
        query_grain = "portfolio" if portfolio_like else "comparison"
    elif manage_corps:
        object_type = "manage_corp_scope"
        object_label = " / ".join(manage_corps)
        query_grain = "portfolio" if portfolio_like else "comparison"
    elif brand_children:
        object_type = "brand_scope"
        object_label = " / ".join(brand_children)
        query_grain = "portfolio" if portfolio_like else "comparison"
    else:
        object_type = "current_scope"
        object_label = "当前管理范围"
        query_grain = "comparison" if intent in {"query", "rank"} else "portfolio"

    if metric_code == "OPERATING_HOTEL_COUNT":
        analysis_mode = "scope_stat_snapshot"
        themes = [metric_name, "scope_inventory"]
        execution_order = ["resolve_scope", "count_entities", "compose_stat"]
    elif intent == "explain":
        analysis_mode = "driver_analysis"
        themes = ["driver_breakdown", "pnl_drilldown"]
        execution_order = ["resolve_scope", "query_detail", "identify_drivers", "compose_explanation"]
    elif intent == "report":
        analysis_mode = "management_report"
        themes = ["income_quality", "room_efficiency", "profit_quality", "cost_efficiency", "internal_benchmark"]
        execution_order = ["resolve_scope", "aggregate_metrics", "peer_benchmark", "compose_report"]
    elif query_grain == "portfolio":
        analysis_mode = "portfolio_overview"
        themes = ["income_quality", "room_efficiency", "profit_quality", "cost_efficiency", "internal_benchmark"]
        execution_order = ["resolve_scope", "aggregate_metrics", "peer_benchmark", "identify_outliers", "compose_overview"]
    elif intent == "rank":
        analysis_mode = "ranking_overview"
        themes = [metric_name]
        execution_order = ["resolve_scope", "query_ranked_rows", "compose_ranking"]
    else:
        analysis_mode = "hotel_metric_snapshot"
        themes = [metric_name, "internal_benchmark"]
        execution_order = ["resolve_scope", "query_metric", "compose_snapshot"]

    fast_steps = {"resolve_scope", "count_entities", "query_metric", "query_ranked_rows", "aggregate_metrics", "compose_stat", "compose_snapshot", "compose_ranking"}
    async_steps = {"peer_benchmark", "identify_outliers", "identify_drivers", "compose_explanation", "compose_report", "compose_overview"}
    filters = {
        "areas": areas,
        "hotels": hotels,
        "manage_corps": manage_corps,
        "brand_children": brand_children,
        "builders": list(result.get("requested_builders", [])),
        "brand_levels": list(result.get("requested_brand_levels", [])),
        "city_levels": list(result.get("requested_city_levels", [])),
        "departments": list(result.get("requested_departments", [])),
        "accounts": list(result.get("requested_accounts", [])),
    }
    query_steps = [
        {
            "step": step,
            "must_be_fast": step in fast_steps,
            "can_async": step in async_steps,
        }
        for step in execution_order
    ]
    evidence_needed = [
        "pnl_fact" if theme in {"income_quality", "profit_quality", "cost_efficiency", "driver_breakdown", "pnl_drilldown"} else
        "hotel_dimension" if theme in {"scope_inventory", "internal_benchmark"} else
        "metric_snapshot"
        for theme in themes
    ]

    return {
        "planner_contract_version": "1.0",
        "intent": intent,
        "time_scope": result.get("time_scope"),
        "period_type": result.get("period_type"),
        "metrics": [{"code": metric_code, "name": metric_name}],
        "comparison_mode": result.get("compare_mode"),
        "filters": filters,
        "query_object_type": object_type,
        "query_object_label": object_label,
        "query_grain": query_grain,
        "analysis_mode": analysis_mode,
        "themes": themes,
        "execution_order": execution_order,
        "query_steps": query_steps,
        "evidence_needed": list(dict.fromkeys(evidence_needed)),
        "fast_path": [item["step"] for item in query_steps if item["must_be_fast"]],
        "async_path": [item["step"] for item in query_steps if item["can_async"]],
        "resolved_hotel_count": (
            len(hotel_group.get("member_hotels", []))
            if hotel_group
            else int(scope_collection.get("member_count") or 0)
            if scope_collection
            else len(hotels)
        ),
    }


def llm_enabled() -> bool:
    return bool(LLM_BASE_URL and LLM_API_KEY and FAST_LLM_MODEL)


def should_use_llm_parse(rule_result: dict, question: str) -> bool:
    if not llm_enabled() or LLM_PARSE_POLICY in {"0", "false", "off", "never"}:
        return False
    if LLM_PARSE_POLICY in {"1", "true", "always"}:
        return True
    confidence = rule_result.get("confidence")
    if should_clarify(rule_result, question):
        return True
    if isinstance(confidence, (int, float)) and confidence >= LLM_PARSE_CONFIDENCE_THRESHOLD:
        return False
    return True


def allowed_metrics(cfg: dict) -> list[str]:
    values = {str(value).strip() for _, value in iter_keyword_map(cfg.get("synonyms", {})) if str(value).strip()}
    default_metric = str(cfg.get("defaults", {}).get("default_metric_code", "")).strip()
    if default_metric:
        values.add(default_metric)
    values.add("OPERATING_PROFIT")
    for skill in load_skills():
        defaults = skill.get("defaults", {})
        if isinstance(defaults, dict):
            metric_code = str(defaults.get("metric_code", "")).strip()
            if metric_code:
                values.add(metric_code)
    return sorted(values)


def allowed_intents(cfg: dict) -> list[str]:
    values = {str(value).strip() for _, value in iter_keyword_map(cfg.get("intents", {})) if str(value).strip()}
    values.add(str(cfg.get("defaults", {}).get("intent", "query")).strip() or "query")
    values.update({"query", "report", "explain", "rank"})
    for skill in load_skills():
        defaults = skill.get("defaults", {})
        if isinstance(defaults, dict):
            intent = str(defaults.get("intent", "")).strip()
            if intent:
                values.add(intent)
    return sorted(values)


def parse_llm_json(content: str) -> dict | None:
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


def call_llm_json(model: str, system_prompt: str, user_payload: dict) -> dict | None:
    if not (LLM_BASE_URL and LLM_API_KEY and model):
        return None

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=LLM_TIMEOUT) as client:
            response = client.post(f"{LLM_BASE_URL.rstrip('/')}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
        content = body["choices"][0]["message"]["content"]
    except Exception:
        return None

    return parse_llm_json(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False))


def call_llm_parse(question: str, time_scope: str, cfg: dict) -> dict | None:
    system_prompt = (
        "你是酒店经营分析助手的快速语义解析器。"
        "请把用户问题解析成 JSON，不要输出任何额外文字。"
        "字段包括 intent, metric_code, compare_mode, variance_direction, requested_areas, requested_hotels, requested_manage_corps, requested_brand_children, requested_builders, requested_brand_levels, requested_city_levels, requested_departments, requested_accounts, confidence。"
        f"intent 只能是 {allowed_intents(cfg)}。"
        f"metric_code 只能是 {allowed_metrics(cfg)}。"
        f"可用业务技能包括 {[skill.get('id') for skill in load_skills()]}，如果命中技能，请严格遵守该技能默认指标和口径。"
        "compare_mode 只能是 actual, budget, yoy。"
        "variance_direction 只能是 below, above, all；未达预算、下滑、低于用 below，高于、增长、超过用 above。"
        "经营情况、经营状况、经营表现这类宽泛问法，默认 metric_code 用 OPERATING_PROFIT，intent 用 query。"
        "收入情况、利润情况、RevPAR情况、怎么样、如何这类问法，如果没有明确同比，compare_mode 默认用 budget。"
        "你必须按数据结构输出字段：酒店范围 requested_hotels、区域 requested_areas、管理公司 requested_manage_corps、品牌/子品牌 requested_brand_children、建设来源 requested_builders、品牌档次 requested_brand_levels、城市等级 requested_city_levels、部门 requested_departments、科目 requested_accounts、月份 time_scope、指标 metric_code、口径 compare_mode。"
        "酒店名称只保留真实酒店名，不要带“看一下、帮我、3月、经营情况”等修饰词。"
        "如果用户要求摘要、晨报、报告，intent 用 report。"
        "如果用户追问原因、为什么、归因，intent 用 explain。"
    )
    return call_llm_json(
        FAST_LLM_MODEL,
        system_prompt,
        {"question": question, "time_scope": time_scope},
    )


def build_rule_parse(payload: Req, cfg: dict) -> dict:
    defaults = cfg.get("defaults", {})
    question_norm = normalize_text(payload.question)
    warnings: list[str] = []
    matched_skill = match_skill(question_norm)
    skill_defaults = matched_skill.get("defaults", {}) if isinstance(matched_skill, dict) and isinstance(matched_skill.get("defaults"), dict) else {}
    metric_code, matched_metric_term = extract_metric_code(cfg, question_norm)
    intent, matched_intent_term = extract_intent(cfg, question_norm)
    compare_mode, matched_compare_term = extract_compare_mode(cfg, question_norm)
    matched_skill_trigger = matched_skill.get("matched_trigger") if isinstance(matched_skill, dict) else None
    if matched_skill:
        skill_metric = str(skill_defaults.get("metric_code", "")).strip()
        skill_intent = str(skill_defaults.get("intent", "")).strip()
        skill_compare = str(skill_defaults.get("compare_mode", "")).strip()
        if skill_metric:
            metric_code = skill_metric
            matched_metric_term = str(matched_skill_trigger or matched_skill.get("name") or matched_skill.get("id"))
        if skill_intent:
            intent = skill_intent
            matched_intent_term = str(matched_skill.get("id") or matched_skill.get("name"))
        if skill_compare and matched_compare_term is None:
            compare_mode = skill_compare
            matched_compare_term = f"skill:{matched_skill.get('id')}"
    if matched_metric_term and is_situation_question(question_norm) and not matched_compare_term:
        compare_mode = "budget"
        matched_compare_term = "默认预算对比"
    variance_direction = extract_variance_direction(question_norm)
    skill_variance = str(skill_defaults.get("variance_direction", "")).strip()
    if matched_skill and skill_variance in {"below", "above", "all"} and variance_direction == "all":
        variance_direction = skill_variance
    time_scope = normalize_time_scope(payload.time_scope, defaults, warnings, payload.question)
    time_scope_explicit = bool(_YEAR_MONTH_IN_QUESTION_RE.search(payload.question) or _MONTH_IN_QUESTION_RE.search(payload.question))
    period_type = str(skill_defaults.get("period_type") or defaults.get("period_type", "MTD")).strip() or "MTD"
    scope = extract_scope(payload.question)
    if metric_code == "OPERATING_HOTEL_COUNT":
        scope["requested_hotels"] = []

    confidence = 0.55
    if matched_metric_term:
        confidence += 0.2
    if matched_intent_term:
        confidence += 0.15
    if matched_compare_term:
        confidence += 0.1
    dimension_keys = [
        "requested_areas",
        "requested_hotels",
        "requested_manage_corps",
        "requested_brand_children",
        "requested_builders",
        "requested_brand_levels",
        "requested_city_levels",
        "requested_departments",
        "requested_accounts",
    ]
    if any(scope.get(key) for key in dimension_keys):
        confidence += 0.05
    if scope["requested_departments"] or scope["requested_accounts"]:
        confidence += 0.08
    if _MONTH_IN_QUESTION_RE.search(payload.question) or _YEAR_MONTH_IN_QUESTION_RE.search(payload.question):
        confidence += 0.05
    if matched_skill:
        confidence += 0.08
    confidence = min(confidence, 0.98)

    return {
        "intent": intent,
        "metric_code": metric_code,
        "compare_mode": compare_mode,
        "variance_direction": variance_direction,
        "time_scope": time_scope,
        "time_scope_explicit": time_scope_explicit,
        "period_type": period_type,
        "requested_areas": scope["requested_areas"],
        "requested_hotels": scope["requested_hotels"],
        "requested_manage_corps": scope["requested_manage_corps"],
        "requested_brand_children": scope["requested_brand_children"],
        "requested_builders": scope["requested_builders"],
        "requested_brand_levels": scope["requested_brand_levels"],
        "requested_city_levels": scope["requested_city_levels"],
        "requested_departments": scope["requested_departments"],
        "requested_accounts": scope["requested_accounts"],
        "skill_id": matched_skill.get("id") if isinstance(matched_skill, dict) else None,
        "skill_version": matched_skill.get("version") if isinstance(matched_skill, dict) else None,
        "matched_terms": {
            "metric": matched_metric_term,
            "intent": matched_intent_term,
            "compare": matched_compare_term,
            "skill": matched_skill_trigger,
        },
        "confidence": confidence,
        "warnings": warnings,
        "parse_debug": {
            "stage": "rule_parse",
            "matched_metric": matched_metric_term,
            "matched_compare": matched_compare_term,
            "matched_intent": matched_intent_term,
            "matched_skill": matched_skill.get("id") if isinstance(matched_skill, dict) else None,
            "matched_skill_trigger": matched_skill_trigger,
            "fast_model": FAST_LLM_MODEL or None,
        },
        "parse_version": "1.3-rule",
    }


def merge_rule_and_llm(rule_result: dict, llm_result: dict | None, cfg: dict) -> dict:
    if not llm_result:
        return rule_result

    merged = dict(rule_result)
    llm_metric = str(llm_result.get("metric_code", "")).strip()
    llm_intent = str(llm_result.get("intent", "")).strip()
    llm_compare_mode = str(llm_result.get("compare_mode", "")).strip()
    llm_variance_direction = str(llm_result.get("variance_direction", "")).strip()
    llm_confidence = llm_result.get("confidence")

    if llm_metric in allowed_metrics(cfg):
        merged["metric_code"] = llm_metric
    if llm_intent in allowed_intents(cfg):
        merged["intent"] = llm_intent
    rule_compare_is_default = rule_result.get("matched_terms", {}).get("compare") == "默认预算对比"
    if llm_compare_mode in {"actual", "budget", "yoy"} and not (rule_compare_is_default and llm_compare_mode == "actual"):
        merged["compare_mode"] = llm_compare_mode
    if llm_variance_direction in {"below", "above", "all"}:
        merged["variance_direction"] = llm_variance_direction

    requested_areas = llm_result.get("requested_areas")
    if isinstance(requested_areas, list) and requested_areas:
        merged["requested_areas"] = [str(item).strip() for item in requested_areas if str(item).strip()]

    requested_hotels = llm_result.get("requested_hotels")
    if isinstance(requested_hotels, list) and requested_hotels:
        cleaned_hotels = [clean_hotel_name(str(item)) for item in requested_hotels if str(item).strip()]
        merged["requested_hotels"] = [item for item in cleaned_hotels if item]

    for list_field in (
        "requested_manage_corps",
        "requested_brand_children",
        "requested_builders",
        "requested_brand_levels",
        "requested_city_levels",
        "requested_departments",
        "requested_accounts",
    ):
        values = llm_result.get(list_field)
        if isinstance(values, list) and values:
            normalized = [str(item).strip() for item in values if str(item).strip()]
            if list_field == "requested_manage_corps":
                normalized = [normalize_manage_corp(item) for item in normalized]
            merged[list_field] = normalized

    if isinstance(llm_confidence, (int, float)):
        merged["confidence"] = max(float(llm_confidence), float(rule_result.get("confidence", 0.55)))

    merged.setdefault("warnings", [])
    merged["warnings"] = list(merged["warnings"])
    merged["parse_debug"] = {
        **dict(rule_result.get("parse_debug", {})),
        "stage": "rule_plus_fast_llm",
        "llm_used": True,
        "llm_metric": llm_metric or None,
        "llm_compare_mode": llm_compare_mode or None,
        "llm_intent": llm_intent or None,
    }
    merged["parse_version"] = "1.3-fast-llm"
    return merged


def should_clarify(result: dict, question: str) -> bool:
    question_text = question.strip()
    if len(question_text) <= 4:
        return True
    has_scope = bool(
        result.get("requested_areas")
        or result.get("requested_hotels")
        or result.get("requested_manage_corps")
        or result.get("requested_brand_children")
        or result.get("requested_builders")
        or result.get("requested_brand_levels")
        or result.get("requested_city_levels")
    )
    matched_terms = result.get("matched_terms", {})
    has_compare = bool(matched_terms.get("compare"))
    has_business_overview = bool(matched_terms.get("metric") == "经营情况")
    generic_prompt = re.search(r"(看一下|帮我分析|帮我看看|讲讲|说说|汇报一下|分析一下)", question_text)
    generic_without_scope = generic_prompt is not None and not has_scope and not has_business_overview
    metric_only_prompt = bool(matched_terms.get("metric")) and not has_scope and not has_compare and len(question_text) <= 10
    return generic_without_scope or metric_only_prompt


def build_clarification_options(result: dict) -> list[str]:
    metric = result.get("metric_code", "该指标")
    metric_name = _METRIC_LABELS.get(str(metric), str(metric))
    return [
        f"看本月{metric_name}预算对比",
        f"看本月{metric_name}同比变化",
        "只看华南区",
        "先给我管理摘要",
    ]


def build_clarification_prompt(question: str, result: dict) -> dict:
    metric = _METRIC_LABELS.get(str(result.get("metric_code") or ""), "当前指标")
    scope_hint = "你更想先看区域还是单店？"
    compare_hint = "要看预算对比，还是同比变化？"
    message = f"我先快速确认一下：你这次是想看 {metric} 的哪个范围和口径？{scope_hint}{compare_hint}"
    return {
        "needs_clarification": True,
        "clarification_question": message,
        "clarification_options": build_clarification_options(result),
    }


@app.post("/api/v1/semantic/parse")
def parse(payload: Req):
    cfg = load_config()
    question_norm = normalize_text(payload.question)
    if not question_norm:
        raise HTTPException(status_code=400, detail="question is required")

    rule_result = build_rule_parse(payload, cfg)
    use_llm = should_use_llm_parse(rule_result, payload.question)
    llm_result = call_llm_parse(payload.question, rule_result["time_scope"], cfg) if use_llm else None
    merged = merge_rule_and_llm(rule_result, llm_result, cfg)
    if not use_llm:
        merged = dict(merged)
        merged["parse_debug"] = {
            **dict(merged.get("parse_debug", {})),
            "llm_used": False,
            "llm_skip_reason": "high_confidence_rule_parse",
            "llm_parse_policy": LLM_PARSE_POLICY,
        }
    merged["resolved_entities"] = build_resolved_entities(payload.question, merged)
    merged["query_plan"] = build_query_plan(payload.question, merged)
    if should_clarify(merged, payload.question):
        merged.update(build_clarification_prompt(payload.question, merged))
    else:
        merged["needs_clarification"] = False
        merged["clarification_question"] = None
        merged["clarification_options"] = []
    return merged
