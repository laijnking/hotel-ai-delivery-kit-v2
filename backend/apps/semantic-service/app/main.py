import json
import os
import re
import csv
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
METRIC_BUNDLES_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "metric_bundles.yaml"
BASE_DATA_DIR = Path(os.getenv("BASE_DATA_DIR", Path(__file__).resolve().parents[5] / "basedata"))
SEMANTIC_KNOWLEDGE_DIR = Path(
    os.getenv("SEMANTIC_KNOWLEDGE_DIR", Path(__file__).resolve().parents[4] / "templates" / "semantic_knowledge")
)
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
    "OPERATING_PROFIT": "经营利润（GOP）",
    "OWNER_PROFIT": "NOP业主净利润",
    "TOTAL_INCOME": "总收入",
    "ROOM_INCOME": "客房收入",
    "RESTAURANT_INCOME": "餐饮收入",
    "BANQUET_INCOME": "宴会收入",
    "ADR": "ADR",
    "OCCUPANCY_RATE": "入住率",
    "REVPAR": "每房收益",
    "PEOPLE_COST": "人工成本",
    "ENERGY_EXPENSES": "能耗费用",
    "RESTAURANT_COST": "餐饮成本",
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
LLM_PARSE_POLICY = os.getenv("QWEN_PARSE_POLICY", "always").strip().lower()
LLM_PARSE_CONFIDENCE_THRESHOLD = float(os.getenv("QWEN_PARSE_CONFIDENCE_THRESHOLD", "0.82"))
_FOLLOW_UP_DRIVER_TERMS = ("原因", "为什么", "归因", "解释", "展开原因")
_FOLLOW_UP_REFINE_TERMS = ("只看", "仅看", "切到", "改看", "换成", "换到", "聚焦到", "聚焦")
_FOLLOW_UP_CONTINUE_TERMS = ("继续", "展开", "追问", "再看")


class Req(BaseModel):
    question: str = Field(..., min_length=2)
    time_scope: str | None = None
    conversation_context: dict | None = None


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
        "base_data_dir": str(BASE_DATA_DIR),
        "base_data_available": BASE_DATA_DIR.exists(),
        "semantic_knowledge_dir": str(SEMANTIC_KNOWLEDGE_DIR),
        "semantic_knowledge_available": SEMANTIC_KNOWLEDGE_DIR.exists(),
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


@lru_cache(maxsize=1)
def load_metric_bundles() -> dict[str, dict]:
    if not METRIC_BUNDLES_CONFIG.exists():
        return {}
    with open(METRIC_BUNDLES_CONFIG, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    bundles = data.get("bundles", {}) if isinstance(data, dict) else {}
    return bundles if isinstance(bundles, dict) else {}


def _load_config_aliases(section: str) -> dict[str, list[str]]:
    cfg = load_config()
    raw = cfg.get(section, {}) if isinstance(cfg, dict) else {}
    if not isinstance(raw, dict):
        return {}
    aliases: dict[str, list[str]] = {}
    for axis, values in raw.items():
        if not isinstance(values, list):
            continue
        cleaned = [str(item).strip() for item in values if str(item).strip()]
        if cleaned:
            aliases[str(axis)] = cleaned
    return aliases


@lru_cache(maxsize=1)
def load_follow_up_aliases() -> dict[str, list[str]]:
    aliases = _load_config_aliases("follow_up_aliases")
    if aliases:
        return aliases
    return {
        "driver": [term for term in _FOLLOW_UP_DRIVER_TERMS],
        "refine_scope": [term for term in _FOLLOW_UP_REFINE_TERMS],
        "compare_shift": ["换成同比", "改成同比", "切成同比", "换成预算", "改成预算", "切成预算"],
        "continue": [term for term in _FOLLOW_UP_CONTINUE_TERMS],
    }


@lru_cache(maxsize=1)
def load_dimension_aliases() -> dict[str, list[str]]:
    aliases = _load_config_aliases("dimension_aliases")
    if aliases:
        return aliases
    return {
        "manage_corp": ["管理公司", "管理方", "管理集团", "管理口径"],
        "brand": ["品牌", "品牌维度", "品牌汇总", "品牌口径"],
        "brand_child": ["子品牌", "子品牌维度", "子品牌汇总", "细分品牌"],
        "area": ["区域", "大区", "区域维度", "区域汇总"],
        "hotel": ["酒店", "单店", "门店", "酒店维度", "酒店汇总"],
        "month": ["月份", "月份维度", "时间", "时间维度", "本月", "去年同期", "同比"],
        "subject_hierarchy": ["科目", "科目层级", "科目上下级", "科目树", "部门", "部门层级", "账目", "PnL"],
    }


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


def resolve_entity_source(source: str) -> Path | None:
    raw = str(source or "").strip()
    if not raw:
        return None

    raw_path = Path(raw).expanduser()
    candidates: list[Path] = [raw_path]
    if not raw_path.is_absolute():
        candidates.append((ENTITY_CONFIG.parent / raw_path).resolve())
        candidates.append((Path(__file__).resolve().parents[4] / raw_path).resolve())
    if raw_path.name:
        candidates.append((BASE_DATA_DIR / raw_path.name).resolve())

    seen: set[str] = set()
    for candidate in candidates:
        candidate_key = str(candidate)
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        if candidate.exists():
            return candidate
    return None


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows: list[dict[str, str]] = []
        for row in reader:
            if not isinstance(row, dict):
                continue
            rows.append({str(key).strip(): str(value or "").strip() for key, value in row.items() if key})
        return rows


@lru_cache(maxsize=1)
def load_semantic_metric_templates() -> list[dict[str, str]]:
    return _read_csv_rows(SEMANTIC_KNOWLEDGE_DIR / "metric_dictionary.csv")


@lru_cache(maxsize=1)
def load_semantic_entity_alias_templates() -> list[dict[str, str]]:
    return _read_csv_rows(SEMANTIC_KNOWLEDGE_DIR / "entity_aliases.csv")


@lru_cache(maxsize=1)
def load_semantic_hotel_master_templates() -> list[dict[str, str]]:
    return _read_csv_rows(SEMANTIC_KNOWLEDGE_DIR / "hotel_master.csv")


@lru_cache(maxsize=1)
def load_semantic_department_templates() -> list[dict[str, str]]:
    return _read_csv_rows(SEMANTIC_KNOWLEDGE_DIR / "department_dictionary.csv")


@lru_cache(maxsize=1)
def load_semantic_account_templates() -> list[dict[str, str]]:
    return _read_csv_rows(SEMANTIC_KNOWLEDGE_DIR / "account_dictionary.csv")


def _template_catalog_values() -> dict[str, list[str]]:
    catalog: dict[str, list[str]] = {
        "hotel": [],
        "area": [],
        "manage_corp": [],
        "brand": [],
        "brand_child": [],
        "city": [],
        "builder": [],
        "brand_level": [],
        "city_level": [],
        "department": [],
        "account": [],
    }

    def append_unique(entity_name: str, value: str) -> None:
        item = str(value or "").strip()
        if item and item not in catalog[entity_name]:
            catalog[entity_name].append(item)

    for row in load_semantic_hotel_master_templates():
        if "酒店名称包括" in str(row.get("hotel_name") or ""):
            continue
        append_unique("hotel", str(row.get("hotel_name") or ""))
        append_unique("area", str(row.get("area") or ""))
        append_unique("manage_corp", str(row.get("manage_corp") or ""))
        append_unique("brand", str(row.get("brand") or ""))
        append_unique("brand_child", str(row.get("brand_child") or ""))
        append_unique("city", str(row.get("city") or ""))
        append_unique("builder", str(row.get("builder") or ""))
        append_unique("brand_level", str(row.get("brand_level") or ""))
        append_unique("city_level", str(row.get("city_level") or ""))

    for row in load_semantic_department_templates():
        append_unique("department", str(row.get("department_name") or ""))

    for row in load_semantic_account_templates():
        append_unique("account", str(row.get("account_name") or ""))
        append_unique("account", str(row.get("level_1") or ""))
        append_unique("account", str(row.get("level_2") or ""))

    return {key: value for key, value in catalog.items() if value}


def _template_scope_graph() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in load_semantic_hotel_master_templates():
        hotel_name = str(row.get("hotel_name") or "").strip()
        if not hotel_name or "酒店名称包括" in hotel_name:
            continue
        rows.append(
            {
                "hotel_name": hotel_name,
                "area": str(row.get("area") or "").strip(),
                "manage_corp": str(row.get("manage_corp") or "").strip(),
                "brand_child": str(row.get("brand_child") or "").strip(),
                "builder": str(row.get("builder") or "").strip(),
                "brand_level": str(row.get("brand_level") or "").strip(),
                "city_level": str(row.get("city_level") or "").strip(),
            }
        )
    return rows


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
    template_catalog = _template_catalog_values()
    catalog: dict[str, list[str]] = {}
    for entity_name, entity_cfg in entities.items():
        if not isinstance(entity_cfg, dict):
            continue
        values: list[str] = list(runtime_catalog.get(str(entity_name), []))
        source = resolve_entity_source(str(entity_cfg.get("source", "")).strip())
        header_prefix = str(entity_cfg.get("header_prefix", "")).strip()
        if source and source.exists():
            with open(source, "r", encoding="utf-8-sig") as file:
                for raw_line in file:
                    item = _clean_entity_line(raw_line, header_prefix)
                    if item and item not in values:
                        values.append(item)
        for item in template_catalog.get(str(entity_name), []):
            if item not in values:
                values.append(item)
        catalog[str(entity_name)] = values

    for entity_name, values in runtime_catalog.items():
        catalog.setdefault(entity_name, values)
    for entity_name, values in template_catalog.items():
        catalog.setdefault(entity_name, [])
        for item in values:
            if item not in catalog[entity_name]:
                catalog[entity_name].append(item)
    return catalog


@lru_cache(maxsize=1)
def load_entity_aliases() -> dict[str, dict[str, list[str]]]:
    if not ENTITY_CONFIG.exists():
        return {}
    with open(ENTITY_CONFIG, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    aliases = cfg.get("aliases", {}) if isinstance(cfg, dict) else {}
    if not isinstance(aliases, dict):
        return {}

    result: dict[str, dict[str, list[str]]] = {}
    for entity_name, entity_aliases in aliases.items():
        if not isinstance(entity_aliases, dict):
            continue
        canonical_map: dict[str, list[str]] = {}
        for canonical, alias_values in entity_aliases.items():
            if isinstance(alias_values, str):
                values = [alias_values]
            elif isinstance(alias_values, list):
                values = [str(item).strip() for item in alias_values if str(item).strip()]
            else:
                values = []
            if values:
                canonical_map[str(canonical).strip()] = values
        if canonical_map:
            result[str(entity_name).strip()] = canonical_map
    entity_type_map = {
        "hotel": "hotel",
        "area": "area",
        "brand": "brand",
        "brand_child": "brand_child",
        "manage_corp": "manage_corp",
        "city": "city",
    }
    for row in load_semantic_entity_alias_templates():
        entity_type = entity_type_map.get(str(row.get("entity_type") or "").strip(), "")
        canonical = str(row.get("canonical_name") or "").strip()
        alias = str(row.get("alias") or "").strip()
        if not entity_type or not canonical or not alias:
            continue
        result.setdefault(entity_type, {}).setdefault(canonical, [])
        if alias not in result[entity_type][canonical]:
            result[entity_type][canonical].append(alias)
    return result


@lru_cache(maxsize=1)
def load_scope_graph() -> list[dict[str, str]]:
    graph = _fetch_runtime_scope_graph()
    if graph:
        return graph
    return _template_scope_graph()


def entity_alias_norms(entity_name: str, value: str) -> list[str]:
    alias_norms = [normalize_text(value)]
    configured = load_entity_aliases().get(entity_name, {}).get(value, [])
    for alias in configured:
        alias_norm = normalize_text(alias)
        if alias_norm and alias_norm not in alias_norms:
            alias_norms.append(alias_norm)
    if entity_name == "hotel" and not value.endswith(("酒店", "公寓")):
        alias_norms.append(f"{alias_norms[0]}酒店")
    return [alias for alias in alias_norms if alias]


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
        alias_norms = entity_alias_norms(entity_name, value)
        if any(alias in question_norm for alias in alias_norms):
            if value not in matches:
                matches.append(value)
            question_norm = question_norm.replace(value_norm, "")
            for alias in alias_norms:
                question_norm = question_norm.replace(alias, "")
    return matches


def match_terms(question_norm: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if normalize_text(term) in question_norm]


def normalize_context(context: object) -> dict[str, object]:
    return context if isinstance(context, dict) else {}


def normalize_manage_corp(value: str) -> str:
    text = value.strip()
    if text == "万达":
        return "万达品牌"
    return text


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return _SPACE_RE.sub("", value).casefold()


def normalize_time_scope(
    time_scope: str | None,
    defaults: dict,
    warnings: list[str],
    question: str = "",
    seed_time_scope: str | None = None,
) -> str:
    candidate = (time_scope or seed_time_scope or "").strip()
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


def detect_follow_up_mode(question_norm: str) -> str | None:
    aliases = load_follow_up_aliases()
    if any(term in question_norm for term in aliases.get("driver", [])):
        return "driver"
    if any(term in question_norm for term in aliases.get("refine_scope", [])):
        return "refine_scope"
    switch_terms = ("换成", "改成", "切成", "切换到", "转成")
    compare_terms = {normalize_text(item) for values in load_config().get("compare_keywords", {}).values() if isinstance(values, list) for item in values}
    if any(term in question_norm for term in switch_terms) and any(term in question_norm for term in compare_terms):
        return "compare_shift"
    if any(term in question_norm for term in aliases.get("continue", [])):
        return "continue"
    return None


def detect_analysis_focus(
    question_norm: str,
    metric_code: str,
    intent: str,
    portfolio_like: bool,
    group_by_dimensions: list[str],
    follow_up_mode: str | None,
    dimension_axes: list[str],
) -> str:
    if metric_code == "OPERATING_HOTEL_COUNT":
        return "scope_inventory"
    if group_by_dimensions:
        return "dimension_comparison"
    if "subject_hierarchy" in dimension_axes:
        return "pnl_hierarchy"
    if follow_up_mode == "compare_shift":
        return "comparison_shift"
    if follow_up_mode == "driver" or intent == "explain":
        return "driver_analysis"
    if any(term in question_norm for term in ("收入结构", "收入质量", "营收结构", "餐饮收入", "宴会收入", "客房收入")):
        return "income_structure"
    if any(term in question_norm for term in ("利润质量", "成本效率", "人工成本", "能耗", "费用率", "利润成本")):
        return "profit_cost_efficiency"
    if intent == "report" or any(normalize_text(term) in question_norm for term in _BUSINESS_OVERVIEW_TERMS):
        return "management_report"
    if follow_up_mode == "refine_scope":
        return "scope_refinement"
    if portfolio_like:
        return "portfolio_overview"
    return "metric_snapshot"


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

    for row in load_semantic_metric_templates():
        metric_code = str(row.get("metric_code") or "").strip()
        aliases = [item.strip() for item in str(row.get("aliases") or "").split("|") if item.strip()]
        for alias in aliases:
            alias_norm = normalize_text(alias)
            if alias_norm and alias_norm in question_norm and metric_code:
                return metric_code, alias

    if any(normalize_text(term) in question_norm for term in _BUSINESS_OVERVIEW_TERMS) or any(
        normalize_text(term) in question_norm for term in ("经营摘要", "经营总览", "管理摘要")
    ):
        return "OWNER_PROFIT", "经营情况"

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
            if any(token in hotel for token in ("哪些酒店", "哪些", "本月", "预算", "同比", "经营利润", "总收入", "每房收益", "奢华级酒店", "五星级酒店", "所有酒店", "全部酒店", "整个酒店", "品牌酒店", "品牌")):
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
    department_norms = {normalize_text(item) for item in requested_departments}
    requested_accounts = [
        item
        for item in requested_accounts
        if normalize_text(item)
        not in {
            normalize_text("汇总"),
            normalize_text("总览"),
            normalize_text("摘要"),
            normalize_text("概览"),
            normalize_text("利润"),
            normalize_text("经营利润"),
            normalize_text("经营情况"),
            normalize_text("经营状况"),
        }
        and normalize_text(item) not in department_norms
    ]

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
    candidate = re.sub(r"^(?:汇总一下|总结一下|统计一下|查一下|看一下|看下|分析一下|了解一下|帮我|请|麻烦)", "", candidate).strip()
    candidate = re.sub(r"^(?:本月|这个月|当月|本年|今年|当前)", "", candidate).strip()
    candidate = re.sub(r"^(?:20\d{2}年)?\d{1,2}月(?:份)?", "", candidate).strip()
    candidate = re.sub(r"(?:查一下|看一下|看下|分析一下|了解一下|帮我|请|麻烦)$", "", candidate).strip()
    candidate = re.sub(r"的$", "", candidate).strip()
    if not candidate or len(candidate) < 2:
        return None
    if candidate in {"哪些", "本月", "这个月", "经营", "总体", "整体"}:
        return None
    return candidate


def is_implicit_company_summary_question(question: str, scope: dict[str, list[str]]) -> bool:
    if any(
        scope.get(key)
        for key in (
            "requested_hotels",
            "requested_areas",
            "requested_manage_corps",
            "requested_brand_children",
            "requested_builders",
            "requested_brand_levels",
            "requested_city_levels",
        )
    ):
        return False
    question_norm = normalize_text(question)
    has_summary_word = any(normalize_text(term) in question_norm for term in _PORTFOLIO_TERMS)
    has_business_context = any(term in question_norm for term in ("经营", "业绩", "收入", "利润", "营收"))
    return has_summary_word and has_business_context


def resolve_hotel_group(question: str, scope: dict[str, list[str]]) -> dict[str, object] | None:
    token = find_hotel_group_token(question, scope)
    question_norm = normalize_text(question)
    company_root_norms = {normalize_text(term) for term in _COMPANY_ROOT_TERMS}
    all_hotel_scope_requested = "酒店" in question and any(normalize_text(term) in question_norm for term in _ALL_SCOPE_TERMS)
    has_business_context = any(term in question_norm for term in ("经营", "业绩", "收入", "利润", "营收"))
    if not token and "酒店" in question and any(term in question_norm for term in company_root_norms) and any(
        normalize_text(term) in question_norm for term in _ALL_SCOPE_TERMS
    ):
        token = "公司"
    if not token and all_hotel_scope_requested and has_business_context:
        token = "公司"
    if not token and is_implicit_company_summary_question(question, scope):
        token = "公司"
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


def detect_group_by_dimensions(question: str) -> list[str]:
    question_norm = normalize_text(question)
    if not any(term in question_norm for term in ("维度", "分组", "汇总到", "汇总至", "按")):
        return []

    dimensions: list[str] = []

    def append_unique(value: str) -> None:
        if value not in dimensions:
            dimensions.append(value)

    if any(term in question_norm for term in ("管理公司", "管理方", "管理集团")):
        append_unique("manage_corp")
    if "区域" in question_norm:
        append_unique("area")
    if any(term in question_norm for term in ("品牌", "子品牌")):
        append_unique("brand_child")
    if "manage_corp" in dimensions and "area" in dimensions:
        append_unique("manage_corp_area")

    return dimensions


def detect_dimension_axes(question: str, result: dict, group_by_dimensions: list[str], follow_up_mode: str | None) -> list[str]:
    question_norm = normalize_text(question)
    aliases = load_dimension_aliases()
    axes: list[str] = []

    def append_unique(value: str) -> None:
        if value and value not in axes:
            axes.append(value)

    def question_has(axis: str) -> bool:
        return any(term in question_norm for term in aliases.get(axis, []))

    if result.get("requested_manage_corps") or question_has("manage_corp"):
        append_unique("manage_corp")

    if "子品牌" in question or result.get("requested_brand_children"):
        append_unique("brand_child")
    if question_has("brand") and "子品牌" not in question:
        append_unique("brand")

    if result.get("requested_areas") or question_has("area"):
        append_unique("area")

    if result.get("requested_hotels") or question_has("hotel"):
        append_unique("hotel")

    if result.get("requested_departments") or result.get("requested_accounts") or question_has("subject_hierarchy"):
        append_unique("subject_hierarchy")

    if result.get("time_scope_explicit") or _MONTH_IN_QUESTION_RE.search(question) or _YEAR_MONTH_IN_QUESTION_RE.search(question) or question_has("month"):
        append_unique("month")

    for dimension in group_by_dimensions:
        if dimension == "manage_corp_area":
            append_unique("manage_corp")
            append_unique("area")
        elif dimension == "brand_child":
            append_unique("brand_child")
        else:
            append_unique(dimension)

    if follow_up_mode == "compare_shift":
        append_unique("comparison_shift")
    elif follow_up_mode == "driver":
        append_unique("driver_focus")
    elif follow_up_mode == "refine_scope":
        append_unique("scope_refinement")
    elif follow_up_mode == "continue":
        append_unique("context_continuation")

    return axes


def build_contract_primary_dimensions(
    object_type: str,
    group_by_dimensions: list[str],
    dimension_axes: list[str],
) -> list[str]:
    pseudo_axes = {"comparison_shift", "driver_focus", "scope_refinement", "context_continuation"}
    primary_dimensions = [axis for axis in dimension_axes if axis not in pseudo_axes]
    if primary_dimensions:
        return primary_dimensions

    fallback_map = {
        "single_hotel": ["hotel"],
        "hotel_group": ["hotel_group"],
        "area_scope": ["area"],
        "manage_corp_scope": ["manage_corp"],
        "brand_scope": ["brand_child"],
        "current_scope": ["current_scope"],
    }
    if group_by_dimensions:
        return list(dict.fromkeys(group_by_dimensions))
    return fallback_map.get(object_type, ["current_scope"])


def build_contract_objective_code(analysis_focus: str, analysis_mode: str, follow_up_mode: str | None) -> str:
    if analysis_focus and analysis_focus != "metric_snapshot":
        return analysis_focus
    if follow_up_mode == "compare_shift":
        return "comparison_shift"
    if analysis_mode:
        return analysis_mode
    return "metric_snapshot"


def build_contract_response_shape(analysis_mode: str, query_grain: str, object_type: str, analysis_focus: str) -> str:
    template_map = {
        "scope_stat_snapshot": "executive_portfolio",
        "group_by_dimension_report": "executive_group_dimension",
        "portfolio_overview": "executive_portfolio",
        "management_report": "executive_portfolio",
        "driver_analysis": "executive_hotel_snapshot" if query_grain != "portfolio" and object_type != "hotel_group" else "executive_portfolio",
        "ranking_overview": "executive_portfolio",
        "hotel_metric_snapshot": "executive_hotel_snapshot",
    }
    if analysis_focus == "pnl_hierarchy":
        return "executive_hotel_snapshot"
    return template_map.get(analysis_mode, "executive_hotel_snapshot")


def build_contract_comparison_label(compare_mode: str) -> str:
    mapping = {
        "actual": "实际口径",
        "budget": "预算对比",
        "yoy": "去年同期对比",
    }
    return mapping.get(compare_mode, "默认对比")


def build_contract_block_sequence(
    analysis_mode: str,
    analysis_focus: str,
    query_grain: str,
    report_template_code: str,
) -> list[str]:
    if analysis_focus == "pnl_hierarchy":
        return ["scope_overview", "pnl_hierarchy", "driver_breakdown", "follow_up_prompt"]
    if analysis_mode == "scope_stat_snapshot":
        return ["scope_overview", "scope_inventory", "stat_summary"]
    if analysis_mode == "group_by_dimension_report":
        return [
            "scope_overview",
            "dimension_summary",
            "dimension_breakdown",
            "income_quality",
            "room_efficiency",
            "profit_quality",
            "cost_efficiency",
            "horizontal_benchmark",
            "follow_up_prompt",
        ]
    if analysis_mode in {"portfolio_overview", "management_report"}:
        return [
            "scope_overview",
            "portfolio_summary",
            "income_quality",
            "room_efficiency",
            "profit_quality",
            "cost_efficiency",
            "horizontal_benchmark",
            "follow_up_prompt",
        ]
    if analysis_mode == "driver_analysis":
        return [
            "scope_overview",
            "driver_summary",
            "driver_breakdown",
            "horizontal_benchmark",
            "follow_up_prompt",
        ]
    if analysis_mode == "ranking_overview":
        return ["scope_overview", "ranking_list", "horizontal_benchmark", "follow_up_prompt"]
    if analysis_mode == "hotel_metric_snapshot":
        return [
            "scope_overview",
            "hotel_summary",
            "income_quality",
            "room_efficiency",
            "profit_quality",
            "cost_efficiency",
            "horizontal_benchmark",
            "follow_up_prompt",
        ]
    return [report_template_code or "analysis_brief", "follow_up_prompt"]


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
    group_by_dimensions = detect_group_by_dimensions(question)
    follow_up_mode = str(result.get("follow_up_mode") or "").strip() or None
    dimension_axes = detect_dimension_axes(question, result, group_by_dimensions, follow_up_mode)
    analysis_focus = detect_analysis_focus(question_norm, metric_code, intent, portfolio_like, group_by_dimensions, follow_up_mode, dimension_axes)
    contextual_step = "inherit_context" if follow_up_mode and isinstance(result.get("conversation_context"), dict) and result.get("conversation_context") else None

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
    elif group_by_dimensions:
        analysis_mode = "group_by_dimension_report"
        themes = ["income_quality", "room_efficiency", "profit_quality", "cost_efficiency", "dimension_comparison"]
        execution_order = ["resolve_scope", "aggregate_metrics", "group_by_dimensions", "identify_outliers", "compose_report"]
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

    bundle_code = "hotel_snapshot"
    report_template_code = "executive_hotel_snapshot"
    if analysis_mode == "scope_stat_snapshot":
        bundle_code = "scope_inventory"
    elif analysis_mode == "driver_analysis":
        bundle_code = "operation_overview" if metric_code in {"OWNER_PROFIT", "OPERATING_PROFIT", "TOTAL_INCOME", "ROOM_INCOME", "RESTAURANT_INCOME", "BANQUET_INCOME", "REVPAR"} else "income_overview"
        report_template_code = "executive_portfolio" if query_grain == "portfolio" else "executive_hotel_snapshot"
    elif analysis_mode in {"portfolio_overview", "management_report"}:
        bundle_code = "operation_overview" if metric_code in {"OWNER_PROFIT", "OPERATING_PROFIT"} else "income_overview"
        report_template_code = "executive_portfolio"
    elif analysis_mode == "group_by_dimension_report":
        bundle_code = "group_dimension_overview"
        report_template_code = "executive_group_dimension"
    elif metric_code == "TOTAL_INCOME":
        bundle_code = "income_overview"

    bundles = load_metric_bundles()
    bundle = bundles.get(bundle_code, {}) if isinstance(bundles.get(bundle_code), dict) else {}
    bundle_metrics = bundle.get("metrics", [])
    configured_themes = bundle.get("themes", [])
    if isinstance(configured_themes, list) and configured_themes:
        themes = [str(item).strip() for item in configured_themes if str(item).strip()]

    if contextual_step:
        execution_order = [contextual_step] + execution_order

    primary_dimensions = build_contract_primary_dimensions(object_type, group_by_dimensions, dimension_axes)
    objective_code = build_contract_objective_code(analysis_focus, analysis_mode, follow_up_mode)
    response_shape = build_contract_response_shape(analysis_mode, query_grain, object_type, analysis_focus)
    comparison_label = build_contract_comparison_label(str(result.get("compare_mode") or "actual").strip() or "actual")
    block_sequence = build_contract_block_sequence(analysis_mode, analysis_focus, query_grain, report_template_code)

    fast_steps = {"resolve_scope", "inherit_context", "count_entities", "query_metric", "query_ranked_rows", "aggregate_metrics", "compose_stat", "compose_snapshot", "compose_ranking"}
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
    dimension_signature = " > ".join(dimension_axes) if dimension_axes else None
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
        "metrics": (
            [{"code": metric_code, "name": _METRIC_LABELS.get(metric_code, metric_name)}]
            if not isinstance(bundle_metrics, list) or not bundle_metrics
            else [{"code": str(code), "name": _METRIC_LABELS.get(str(code), str(code))} for code in bundle_metrics]
        ),
        "metric_bundle_code": bundle_code,
        "report_template_code": report_template_code,
        "comparison_mode": result.get("compare_mode"),
        "filters": filters,
        "query_object_type": object_type,
        "query_object_label": object_label,
        "query_grain": query_grain,
        "analysis_mode": analysis_mode,
        "analysis_focus": analysis_focus,
        "follow_up_mode": follow_up_mode,
        "group_by_dimensions": group_by_dimensions,
        "dimension_axes": dimension_axes,
        "dimension_signature": dimension_signature,
        "themes": themes,
        "execution_order": execution_order,
        "query_steps": query_steps,
        "evidence_needed": list(dict.fromkeys(evidence_needed)),
        "fast_path": [item["step"] for item in query_steps if item["must_be_fast"]],
        "async_path": [item["step"] for item in query_steps if item["can_async"]],
        "analysis_contract": {
            "contract_version": "1.1",
            "objective_code": objective_code,
            "response_shape": response_shape,
            "headline_metric": {"code": metric_code, "name": _METRIC_LABELS.get(metric_code, metric_name)},
            "comparison_label": comparison_label,
            "primary_dimensions": primary_dimensions,
            "block_sequence": block_sequence,
        },
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
    values.add("OWNER_PROFIT")
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
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if fenced:
            try:
                data = json.loads(fenced.group(1))
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                pass
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


def _llm_entity_hints(question: str) -> dict[str, list[str]]:
    hints: dict[str, list[str]] = {}
    for entity_name in ("hotel", "area", "brand_child", "manage_corp", "city", "department", "account"):
        matches = match_catalog_entities(question, entity_name)
        if matches:
            hints[entity_name] = matches[:10]
            continue
        catalog = load_entity_catalog().get(entity_name, [])
        if catalog:
            hints[entity_name] = [str(item).strip() for item in catalog[:8] if str(item).strip()]
    return hints


def _llm_metric_hints() -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for row in load_semantic_metric_templates()[:20]:
        metric_code = str(row.get("metric_code") or "").strip()
        if not metric_code:
            continue
        items.append(
            {
                "metric_code": metric_code,
                "name_cn": str(row.get("name_cn") or "").strip(),
                "aliases": [item.strip() for item in str(row.get("aliases") or "").split("|") if item.strip()],
                "default_compare_mode": str(row.get("default_compare_mode") or "").strip(),
            }
        )
    return items


def _llm_parse_user_payload(question: str, time_scope: str, cfg: dict, include_metric_hints: bool = True) -> dict[str, object]:
    payload: dict[str, object] = {
        "question": question,
        "time_scope": time_scope,
        "allowed_intents": allowed_intents(cfg),
        "allowed_metrics": allowed_metrics(cfg),
        "entity_hints": _llm_entity_hints(question),
        "manage_corp_aliases": load_entity_aliases().get("manage_corp", {}),
        "output_schema_example": {
            "intent": "query",
            "metric_code": "OWNER_PROFIT",
            "compare_mode": "yoy",
            "variance_direction": "all",
            "follow_up_mode": "",
            "time_scope": time_scope,
            "requested_areas": [],
            "requested_hotels": [],
            "requested_manage_corps": [],
            "requested_brand_children": [],
            "requested_builders": [],
            "requested_brand_levels": [],
            "requested_city_levels": [],
            "requested_departments": [],
            "requested_accounts": [],
            "confidence": 0.82,
        },
    }
    if include_metric_hints:
        payload["metric_hints"] = _llm_metric_hints()
    return payload


def normalize_llm_parse_result(llm_result: dict | None, rule_result: dict, cfg: dict, time_scope: str) -> dict | None:
    if not isinstance(llm_result, dict):
        return None
    result = dict(llm_result)
    result["intent"] = str(result.get("intent") or rule_result.get("intent") or cfg.get("defaults", {}).get("intent", "query")).strip() or "query"
    if result["intent"] not in allowed_intents(cfg):
        result["intent"] = str(rule_result.get("intent") or "query").strip() or "query"

    result["metric_code"] = str(result.get("metric_code") or rule_result.get("metric_code") or cfg.get("defaults", {}).get("default_metric_code", "TOTAL_INCOME")).strip() or "TOTAL_INCOME"
    if result["metric_code"] not in allowed_metrics(cfg):
        result["metric_code"] = str(rule_result.get("metric_code") or "TOTAL_INCOME").strip() or "TOTAL_INCOME"

    compare_mode = str(result.get("compare_mode") or rule_result.get("compare_mode") or cfg.get("defaults", {}).get("compare_mode", "actual")).strip() or "actual"
    result["compare_mode"] = compare_mode if compare_mode in {"actual", "budget", "yoy"} else str(rule_result.get("compare_mode") or "actual")

    variance_direction = str(result.get("variance_direction") or rule_result.get("variance_direction") or "all").strip() or "all"
    result["variance_direction"] = variance_direction if variance_direction in {"below", "above", "all"} else str(rule_result.get("variance_direction") or "all")

    follow_up_mode = str(result.get("follow_up_mode") or "").strip()
    result["follow_up_mode"] = follow_up_mode if follow_up_mode in {"driver", "refine_scope", "compare_shift", "continue"} else ""

    for list_field in (
        "requested_areas",
        "requested_hotels",
        "requested_manage_corps",
        "requested_brand_children",
        "requested_builders",
        "requested_brand_levels",
        "requested_city_levels",
        "requested_departments",
        "requested_accounts",
    ):
        values = result.get(list_field)
        if isinstance(values, list):
            cleaned = [str(item).strip() for item in values if str(item).strip()]
            if list_field == "requested_hotels":
                cleaned = [clean_hotel_name(item) for item in cleaned if clean_hotel_name(item)]
            if list_field == "requested_manage_corps":
                cleaned = [normalize_manage_corp(item) for item in cleaned]
            result[list_field] = cleaned
        else:
            result[list_field] = []

    result["time_scope"] = normalize_time_scope(str(result.get("time_scope") or time_scope), cfg.get("defaults", {}), [], seed_time_scope=time_scope)
    confidence = result.get("confidence")
    try:
        result["confidence"] = max(0.0, min(float(confidence), 0.99))
    except (TypeError, ValueError):
        result["confidence"] = float(rule_result.get("confidence", 0.6))
    return result


def call_llm_parse(question: str, time_scope: str, cfg: dict) -> dict | None:
    system_prompt = (
        "你是酒店经营AI的语义路由器。"
        "你的任务是把用户问题转成一个JSON对象。"
        "只能返回JSON对象，不要解释，不要Markdown，不要代码块。"
        "必须输出全部字段："
        "intent, metric_code, compare_mode, variance_direction, follow_up_mode, time_scope, "
        "requested_areas, requested_hotels, requested_manage_corps, requested_brand_children, "
        "requested_builders, requested_brand_levels, requested_city_levels, requested_departments, "
        "requested_accounts, confidence。"
        "未识别时数组字段返回[]，字符串字段返回默认值。"
        "intent 只能是 query/report/explain/rank。"
        "compare_mode 只能是 actual/budget/yoy。"
        "variance_direction 只能是 below/above/all。"
        "follow_up_mode 只能是 driver/refine_scope/compare_shift/continue，无法判断时返回空字符串。"
        "经营情况/经营状况/经营表现这类宽泛问法，默认 intent=query, metric_code=OWNER_PROFIT。"
        "收入情况/利润情况/RevPAR情况/怎么样/如何，如果没有明确同比或预算，默认 compare_mode=yoy。"
        "酒店名必须尽量从提供的基础主数据中选择最接近的一项，不要带修饰词。"
    )
    raw_result = call_llm_json(
        FAST_LLM_MODEL,
        system_prompt,
        _llm_parse_user_payload(question, time_scope, cfg, include_metric_hints=True),
    )
    if not raw_result:
        raw_result = call_llm_json(
            FAST_LLM_MODEL,
            system_prompt,
            _llm_parse_user_payload(question, time_scope, cfg, include_metric_hints=False),
        )
    return normalize_llm_parse_result(raw_result, {"intent": "query", "metric_code": "OWNER_PROFIT", "compare_mode": "actual", "variance_direction": "all", "confidence": 0.55}, cfg, time_scope)


def build_rule_parse(payload: Req, cfg: dict) -> dict:
    defaults = cfg.get("defaults", {})
    question_norm = normalize_text(payload.question)
    context = normalize_context(payload.conversation_context)
    follow_up_mode = detect_follow_up_mode(question_norm)
    warnings: list[str] = []
    matched_skill = match_skill(question_norm)
    skill_defaults = matched_skill.get("defaults", {}) if isinstance(matched_skill, dict) and isinstance(matched_skill.get("defaults"), dict) else {}
    metric_code, matched_metric_term = extract_metric_code(cfg, question_norm)
    explicit_metric_code = metric_code
    explicit_metric_term = matched_metric_term
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
    if follow_up_mode == "driver":
        intent = "explain"
        if not matched_intent_term:
            matched_intent_term = "follow_up_driver"
    if explicit_metric_code == "OPERATING_PROFIT" and normalize_text(str(explicit_metric_term or "")) in {"经营利润", "gop", "operatingprofit"}:
        metric_code = "OPERATING_PROFIT"
        matched_metric_term = str(explicit_metric_term)
    if matched_metric_term and is_situation_question(question_norm) and not matched_compare_term:
        compare_mode = "yoy"
        matched_compare_term = "默认去年同期对比"
    variance_direction = extract_variance_direction(question_norm)
    skill_variance = str(skill_defaults.get("variance_direction", "")).strip()
    if matched_skill and skill_variance in {"below", "above", "all"} and variance_direction == "all":
        variance_direction = skill_variance
    parsed_context_intent = context.get("parsed_intent") if isinstance(context.get("parsed_intent"), dict) else {}
    parsed_context_query_plan = context.get("query_plan") if isinstance(context.get("query_plan"), dict) else {}
    parsed_context_metric = ""
    parsed_context_metrics = parsed_context_query_plan.get("metrics")
    if isinstance(parsed_context_metrics, list) and parsed_context_metrics:
        first_metric = parsed_context_metrics[0]
        if isinstance(first_metric, dict):
            parsed_context_metric = str(first_metric.get("code") or "").strip()
    context_metric_code = str(
        context.get("metric_code")
        or context.get("last_metric_code")
        or parsed_context_intent.get("metric_code")
        or parsed_context_query_plan.get("metric_code")
        or parsed_context_metric
        or ""
    ).strip()
    context_compare_mode = str(
        context.get("compare_mode")
        or context.get("last_compare_mode")
        or parsed_context_intent.get("compare_mode")
        or parsed_context_query_plan.get("comparison_mode")
        or ""
    ).strip()
    context_time_scope = str(
        context.get("time_scope")
        or context.get("last_time_scope")
        or parsed_context_intent.get("time_scope")
        or parsed_context_query_plan.get("time_scope")
        or ""
    ).strip()
    time_scope = normalize_time_scope(payload.time_scope, defaults, warnings, payload.question, seed_time_scope=context_time_scope)
    time_scope_explicit = bool(_YEAR_MONTH_IN_QUESTION_RE.search(payload.question) or _MONTH_IN_QUESTION_RE.search(payload.question))
    period_type = str(skill_defaults.get("period_type") or defaults.get("period_type", "MTD")).strip() or "MTD"
    scope = extract_scope(payload.question)
    has_explicit_scope = any(
        scope.get(key)
        for key in (
            "requested_areas",
            "requested_hotels",
            "requested_manage_corps",
            "requested_brand_children",
            "requested_builders",
            "requested_brand_levels",
            "requested_city_levels",
        )
    )
    if context and not has_explicit_scope and follow_up_mode:
        for key in (
            "requested_areas",
            "requested_hotels",
            "requested_manage_corps",
            "requested_brand_children",
            "requested_builders",
            "requested_brand_levels",
            "requested_city_levels",
            "requested_departments",
            "requested_accounts",
        ):
            if scope.get(key):
                continue
            values = context.get(key)
            if isinstance(values, list):
                normalized = [str(item).strip() for item in values if str(item).strip()]
                if normalized:
                    scope[key] = normalized
        if not explicit_metric_term and context_metric_code in allowed_metrics(cfg):
            metric_code = context_metric_code
            matched_metric_term = f"context:{context_metric_code}"
        if not matched_compare_term and context_compare_mode in {"actual", "budget", "yoy"}:
            compare_mode = context_compare_mode
            matched_compare_term = f"context:{context_compare_mode}"
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
    if context:
        confidence += 0.03
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
        "follow_up_mode": follow_up_mode,
        "conversation_context": context,
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
            "follow_up_mode": follow_up_mode,
            "context_used": bool(context),
            "fast_model": FAST_LLM_MODEL or None,
        },
        "parse_version": "1.3-rule",
    }


def build_semantic_draft(rule_result: dict, llm_result: dict | None, cfg: dict) -> dict | None:
    if not llm_result:
        return None
    draft: dict[str, object] = {
        "source": "fast_llm",
        "confidence": llm_result.get("confidence"),
        "raw": llm_result,
        "candidates": {},
    }
    candidates = draft["candidates"] if isinstance(draft.get("candidates"), dict) else {}

    llm_metric = str(llm_result.get("metric_code", "")).strip()
    llm_intent = str(llm_result.get("intent", "")).strip()
    llm_compare_mode = str(llm_result.get("compare_mode", "")).strip()
    llm_variance_direction = str(llm_result.get("variance_direction", "")).strip()
    llm_follow_up_mode = str(llm_result.get("follow_up_mode", "")).strip()

    if llm_metric:
        candidates["metric_code"] = {
            "value": llm_metric,
            "accepted": llm_metric in allowed_metrics(cfg),
        }
    if llm_intent:
        candidates["intent"] = {
            "value": llm_intent,
            "accepted": llm_intent in allowed_intents(cfg),
        }
    if llm_compare_mode:
        candidates["compare_mode"] = {
            "value": llm_compare_mode,
            "accepted": llm_compare_mode in {"actual", "budget", "yoy"},
        }
    if llm_variance_direction:
        candidates["variance_direction"] = {
            "value": llm_variance_direction,
            "accepted": llm_variance_direction in {"below", "above", "all"},
        }
    if llm_follow_up_mode:
        candidates["follow_up_mode"] = {
            "value": llm_follow_up_mode,
            "accepted": llm_follow_up_mode in {"driver", "refine_scope", "compare_shift", "continue"},
        }
    for list_field in (
        "requested_areas",
        "requested_hotels",
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
            if normalized:
                candidates[list_field] = {"value": normalized, "accepted": True}
    draft["rule_confidence"] = rule_result.get("confidence")
    return draft


def merge_rule_and_llm(rule_result: dict, semantic_draft: dict | None, cfg: dict) -> dict:
    llm_result = semantic_draft.get("raw") if isinstance(semantic_draft, dict) and isinstance(semantic_draft.get("raw"), dict) else None
    if not llm_result:
        return rule_result

    merged = dict(rule_result)
    llm_metric = str(llm_result.get("metric_code", "")).strip()
    llm_intent = str(llm_result.get("intent", "")).strip()
    llm_compare_mode = str(llm_result.get("compare_mode", "")).strip()
    llm_variance_direction = str(llm_result.get("variance_direction", "")).strip()
    llm_follow_up_mode = str(llm_result.get("follow_up_mode", "")).strip()
    llm_confidence = llm_result.get("confidence")

    if llm_metric in allowed_metrics(cfg):
        merged["metric_code"] = llm_metric
    if llm_intent in allowed_intents(cfg):
        merged["intent"] = llm_intent
    rule_compare_is_default = rule_result.get("matched_terms", {}).get("compare") == "默认去年同期对比"
    if llm_compare_mode in {"actual", "budget", "yoy"} and not (rule_compare_is_default and llm_compare_mode == "actual"):
        merged["compare_mode"] = llm_compare_mode
    if llm_variance_direction in {"below", "above", "all"}:
        merged["variance_direction"] = llm_variance_direction
    if llm_follow_up_mode in {"driver", "refine_scope", "compare_shift", "continue"}:
        merged["follow_up_mode"] = llm_follow_up_mode

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
        "llm_follow_up_mode": llm_follow_up_mode or None,
    }
    merged["parse_version"] = "1.3-fast-llm"
    return merged


def detect_conversation_action(result: dict, question: str) -> str:
    follow_up_mode = str(result.get("follow_up_mode") or "").strip()
    intent = str(result.get("intent") or "").strip()
    if follow_up_mode == "driver":
        return "follow_up_continue"
    if follow_up_mode == "refine_scope":
        return "refine_scope"
    if follow_up_mode == "compare_shift":
        return "shift_compare_mode"
    if intent == "report":
        return "management_summary"
    if has_context_anchor(result) and len(question.strip()) <= 12:
        return "follow_up_continue"
    return "new_query"


def route_mode(result: dict) -> str:
    parse_debug = result.get("parse_debug") if isinstance(result.get("parse_debug"), dict) else {}
    if parse_debug.get("llm_used"):
        return "fast_llm_parse"
    return "deterministic"


def detect_clarification_type(result: dict, question: str) -> str | None:
    question_text = question.strip()
    if len(question_text) <= 4:
        return "weak_context_anchor" if has_context_anchor(result) else "missing_scope"
    has_scope = bool(
        result.get("requested_areas")
        or result.get("requested_hotels")
        or result.get("requested_manage_corps")
        or result.get("requested_brand_children")
        or result.get("requested_builders")
        or result.get("requested_brand_levels")
        or result.get("requested_city_levels")
    )
    matched_terms = result.get("matched_terms", {}) if isinstance(result.get("matched_terms"), dict) else {}
    has_compare = bool(matched_terms.get("compare"))
    has_business_overview = bool(matched_terms.get("metric") == "经营情况")
    context_anchor = has_context_anchor(result)
    generic_prompt = re.search(r"(看一下|帮我分析|帮我看看|讲讲|说说|汇报一下|分析一下)", question_text)
    if generic_prompt is not None and not has_scope and not has_business_overview and not context_anchor:
        return "missing_scope"
    if bool(matched_terms.get("metric")) and not has_scope and not has_compare and len(question_text) <= 10 and not context_anchor:
        return "missing_scope"
    if not context_anchor and detect_conversation_action(result, question) != "new_query" and len(question_text) <= 8:
        return "weak_context_anchor"
    return None


def should_clarify(result: dict, question: str) -> bool:
    return detect_clarification_type(result, question) is not None


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
    clarification_type = detect_clarification_type(result, question) or "missing_scope"
    if clarification_type == "weak_context_anchor":
        message = "我先确认一下：你这句是在延续上一轮结果，还是想发起一个新的经营问题？"
    else:
        scope_hint = "你更想先看区域还是单店？"
        compare_hint = "要看预算对比，还是同比变化？"
        message = f"我先快速确认一下：你这次是想看 {metric} 的哪个范围和口径？{scope_hint}{compare_hint}"
    return {
        "needs_clarification": True,
        "clarification_type": clarification_type,
        "clarification_question": message,
        "clarification_options": build_clarification_options(result),
    }


def has_context_anchor(result: dict) -> bool:
    context = result.get("conversation_context")
    if not isinstance(context, dict) or not context:
        return False
    anchor_keys = (
        "metric_code",
        "time_scope",
        "requested_areas",
        "requested_hotels",
        "requested_manage_corps",
        "requested_brand_children",
        "requested_builders",
        "requested_brand_levels",
        "requested_city_levels",
    )
    return any(context.get(key) for key in anchor_keys)


def build_semantic_notes(result: dict, question: str) -> list[str]:
    notes: list[str] = []
    if route_mode(result) == "fast_llm_parse":
        notes.append("本轮先由快模型做语义归一化。")
    else:
        notes.append("本轮命中确定性规则解析。")
    conversation_action = detect_conversation_action(result, question)
    action_notes = {
        "new_query": "系统判断这是一个新问题。",
        "follow_up_continue": "系统判断这是在承接上一轮继续追问。",
        "refine_scope": "系统判断你在收窄分析范围。",
        "shift_compare_mode": "系统判断你在切换对比口径。",
        "management_summary": "系统判断你想直接获取经营摘要。",
    }
    if conversation_action in action_notes:
        notes.append(action_notes[conversation_action])
    if result.get("needs_clarification"):
        clarification_type = str(result.get("clarification_type") or "").strip()
        if clarification_type == "weak_context_anchor":
            notes.append("当前上下文锚点不足，需要先确认承接关系。")
        else:
            notes.append("当前信息还不足以稳定落到执行口径，需要先澄清。")
    return notes


@app.post("/api/v1/semantic/parse")
def parse(payload: Req):
    cfg = load_config()
    question_norm = normalize_text(payload.question)
    if not question_norm:
        raise HTTPException(status_code=400, detail="question is required")

    rule_result = build_rule_parse(payload, cfg)
    use_llm = should_use_llm_parse(rule_result, payload.question)
    llm_result = call_llm_parse(payload.question, rule_result["time_scope"], cfg) if use_llm else None
    semantic_draft = build_semantic_draft(rule_result, llm_result, cfg)
    merged = merge_rule_and_llm(rule_result, semantic_draft, cfg)
    if isinstance(payload.conversation_context, dict) and payload.conversation_context:
        merged["conversation_context"] = payload.conversation_context
    if not use_llm:
        merged = dict(merged)
        merged["parse_debug"] = {
            **dict(merged.get("parse_debug", {})),
            "llm_used": False,
            "llm_skip_reason": "high_confidence_rule_parse",
            "llm_parse_policy": LLM_PARSE_POLICY,
        }
    merged["semantic_draft"] = semantic_draft
    merged["resolved_entities"] = build_resolved_entities(payload.question, merged)
    merged["query_plan"] = build_query_plan(payload.question, merged)
    if should_clarify(merged, payload.question):
        merged.update(build_clarification_prompt(payload.question, merged))
    else:
        merged["needs_clarification"] = False
        merged["clarification_type"] = None
        merged["clarification_question"] = None
        merged["clarification_options"] = []
    merged["route_mode"] = route_mode(merged)
    merged["conversation_action"] = detect_conversation_action(merged, payload.question)
    merged["semantic_notes"] = build_semantic_notes(merged, payload.question)
    return merged
