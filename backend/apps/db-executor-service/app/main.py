import csv
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import create_engine, text

try:
    import duckdb
except Exception:  # pragma: no cover - optional local warehouse dependency
    duckdb = None

app = FastAPI(title="db-executor-service")

_IN_CLAUSE_RE = re.compile(r"(?P<column>[A-Za-z_][A-Za-z0-9_]*)\s+IN\s*\((?P<values>[^)]+)\)", re.IGNORECASE)
_CALMONTH_RE = re.compile(r"CALMONTH\s*=\s*'(?P<value>\d{6})'", re.IGNORECASE)
_LIMIT_RE = re.compile(r"LIMIT\s+(?P<value>\d+)", re.IGNORECASE)
_HOTEL_LIKE_RE = re.compile(r"hotel_name[^)]*\)?\s+LIKE\s+'%?(?P<value>[^%']+)%?'", re.IGNORECASE)
_OVERVIEW_FIELD_RE = re.compile(
    r"(?P<actual>(?:[A-Za-z_][A-Za-z0-9_]*\.)?[A-Za-z_][A-Za-z0-9_]*)\s+AS\s+actual_value,\s+(?P<compare>(?:[A-Za-z_][A-Za-z0-9_]*\.)?[A-Za-z_][A-Za-z0-9_]*)\s+AS\s+compare_value",
    re.IGNORECASE | re.DOTALL,
)
_DETAIL_FIELD_RE = re.compile(
    r"SELECT\s+hotel_name_s AS hotel_name,\s+Dept AS dept,\s+account_name,\s+mtd_a AS actual_value,\s+(?P<compare>[A-Za-z0-9_]+)\s+AS compare_value",
    re.IGNORECASE | re.DOTALL,
)

REAL_DATA_DIR = Path(os.getenv("REAL_DATA_DIR", Path(__file__).resolve().parents[5] / "real-data"))
WAREHOUSE_DIR = Path(os.getenv("WAREHOUSE_DIR", Path(__file__).resolve().parents[3] / "runtime" / "warehouse"))
DUCKDB_PATH = Path(os.getenv("WAREHOUSE_DUCKDB_PATH", WAREHOUSE_DIR / "hotel_warehouse.duckdb"))
WAREHOUSE_MANIFEST = Path(os.getenv("WAREHOUSE_MANIFEST", WAREHOUSE_DIR / "sync_manifest.json"))
USE_LOCAL_WAREHOUSE = os.getenv("USE_LOCAL_WAREHOUSE", "1").strip().lower() not in {"0", "false", "no"}

OVERVIEW_COLUMN_MAP = {
    "æŠ¥å‘Šæœˆä»½": "CALMONTH",
    "Time": "time",
    "å“ç‰Œ": "brand",
    "å­å“ç‰Œ": "brand_child",
    "é…’åº—åç§°": "HOTEL_NAME_s",
    "åŒºåŸŸ": "area",
    "å»ºè®¾æ–¹": "Builder",
    "é…’åº—ç­‰çº§": "brand_level",
    "åŸŽå¸‚çº§åˆ«": "city_level",
    "æˆ¿é—´æ•°": "rooms",
    "é…’åº—é¢ç§¯": "build_area",
    "ç»è¥åˆ©æ¶¦æœˆå®žé™…å€¼": "OPERATING_PROFIT_MTD_A",
    "ç»è¥åˆ©æ¶¦æœˆé¢„ç®—å€¼": "OPERATING_PROFIT_MTD_B",
    "ç»è¥åˆ©æ¶¦æœˆåŽ»å¹´åŒæœŸ": "OPERATING_PROFIT_MTD_L",
    "ä¸šä¸»åˆ©æ¶¦æœˆå®žé™…": "OWNER_PROFIT_MTD_A",
    "ä¸šä¸»åˆ©æ¶¦æœˆé¢„ç®—": "OWNER_PROFIT_MTD_B",
    "ä¸šä¸»åˆ©æ¶¦æœˆåŽ»å¹´åŒæœŸ": "OWNER_PROFIT_MTD_L",
    "æœˆå®¢æˆ¿æ”¶å…¥å®žé™…": "ROOM_INCOME_MTD_A",
    "æœˆå®¢æˆ¿æ”¶å…¥é¢„ç®—": "ROOM_INCOME_MTD_B",
    "æœˆå®¢æˆ¿æ”¶å…¥åŒæœŸ": "ROOM_INCOME_MTD_L",
    "æœˆå®žé™…å‡ºç§Ÿæˆ¿é—´æ•°": "RENTAL_ROOMS_NUM_MTD_A",
    "æœˆé¢„ç®—å‡ºç§Ÿæˆ¿é—´æ•°": "RENTAL_ROOMS_NUM_MTD_B",
    "æœˆåŒæœŸå‡ºç§Ÿæˆ¿é—´æ•°": "RENTAL_ROOMS_NUM_MTD_L",
    "å¹³å‡æˆ¿ä»·æœˆå®žé™…": "AVE_HOUSE_PRICE_MTD_A",
    "å¹³å‡æˆ¿ä»·æœˆé¢„ç®—": "AVE_HOUSE_PRICE_MTD_B",
    "å¹³å‡æˆ¿ä»·æœˆåŒæœŸ": "AVE_HOUSE_PRICE_MTD_L",
    "å…¥ä½çŽ‡æœˆå®žé™…": "OCCUPANCY_RATE_MTD_A",
    "å…¥ä½çŽ‡æœˆé¢„ç®—": "OCCUPANCY_RATE_MTD_B",
    "å…¥ä½çŽ‡æœˆåŒæœŸ": "OCCUPANCY_RATE_MTD_L",
    "æ¯æˆ¿æ”¶ç›Šæœˆå®žé™…": "INCOME_PER_ROOM_MTD_A",
    "æ¯æˆ¿æ”¶ç›Šæœˆé¢„ç®—": "INCOME_PER_ROOM_MTD_B",
    "æ¯æˆ¿æ”¶ç›ŠæœˆåŒæœŸ": "INCOME_PER_ROOM_MTD_L",
    "æ€»æ”¶å…¥æœˆå®žé™…": "TOTAL_INCOME_MTD_A",
    "æ€»æ”¶å…¥æœˆé¢„ç®—": "TOTAL_INCOME_MTD_B",
    "æ€»æ”¶å…¥æœˆåŒæœŸ": "TOTAL_INCOME_MTD_L",
    "é¤åŽ…æ”¶å…¥æœˆå®žé™…": "RESTAURANT_INCOME_MTD_A",
    "é¤åŽ…æ”¶å…¥æœˆé¢„ç®—": "RESTAURANT_INCOME_MTD_B",
    "é¤åŽ…æ”¶å…¥æœˆåŒæœŸ": "RESTAURANT_INCOME_MTD_L",
    "å®´ä¼šæ”¶å…¥æœˆå®žé™…": "BANQUET_INCOME_MTD_A",
    "å®´ä¼šæ”¶å…¥æœˆé¢„ç®—": "BANQUET_INCOME_MTD_B",
    "å®´ä¼šæ”¶å…¥æœˆåŒæœŸ": "BANQUET_INCOME_MTD_L",
    "å…¶å®ƒè¥ä¸šéƒ¨é—¨æ”¶å…¥æœˆå®žé™…": "OTHER_DEPT_INCOME_MTD_A",
    "å…¶å®ƒè¥ä¸šéƒ¨é—¨æ”¶å…¥æœˆé¢„ç®—": "OTHER_DEPT_INCOME_MTD_B",
    "å…¶å®ƒè¥ä¸šéƒ¨é—¨æ”¶å…¥æœˆåŒæœŸ": "OTHER_DEPT_INCOME_MTD_L",
    "ç§Ÿé‡‘åŠå…¶å®ƒæ”¶å…¥æœˆå®žé™…": "OTHER_RATE_INCOME_MTD_A",
    "ç§Ÿé‡‘åŠå…¶å®ƒæ”¶å…¥æœˆé¢„ç®—": "OTHER_RATE_INCOME_MTD_B",
    "ç§Ÿé‡‘åŠå…¶å®ƒæ”¶å…¥æœˆåŒæœŸ": "OTHER_RATE_INCOME_MTD_L",
    "å®¢æˆ¿æˆæœ¬æœˆå®žé™…": "ROOM_COST_MTD_A",
    "å®¢æˆ¿æˆæœ¬æœˆé¢„ç®—": "ROOM_COST_MTD_B",
    "å®¢æˆ¿æˆæœ¬æœˆåŒæœŸ": "ROOM_COST_MTD_L",
    "é¤é¥®æˆæœ¬æœˆå®žé™…": "RESTAURANT_COST_MTD_A",
    "é¤é¥®æˆæœ¬æœˆé¢„ç®—": "RESTAURANT_COST_MTD_B",
    "é¤é¥®æˆæœ¬æœˆåŒæœŸ": "RESTAURANT_COST_MTD_L",
    "é£Ÿå“æˆæœ¬æœˆå®žé™…": "FOOD_COST_MTD_A",
    "é£Ÿå“æˆæœ¬æœˆé¢„ç®—": "FOOD_COST_MTD_B",
    "é£Ÿå“æˆæœ¬æœˆåŒæœŸ": "FOOD_COST_MTD_L",
    "é…’æ°´æˆæœ¬æœˆå®žé™…": "WINE_COSE_MTD_A",
    "é…’æ°´æˆæœ¬æœˆé¢„ç®—": "WINE_COSE_MTD_B",
    "é…’æ°´æˆæœ¬æœˆåŒæœŸ": "WINE_COSE_MTD_L",
    "è¡Œæ”¿è´¹ç”¨æœˆå®žé™…": "ADMINI_EXPENSES_MTD_A",
    "è¡Œæ”¿è´¹ç”¨æœˆé¢„ç®—": "ADMINI_EXPENSES_MTD_B",
    "è¡Œæ”¿è´¹ç”¨æœˆåŒæœŸ": "ADMINI_EXPENSES_MTD_L",
    "èƒ½æºè´¹ç”¨æœˆå®žé™…": "ENERGY_EXPENSES_MTD_A",
    "èƒ½æºè´¹ç”¨æœˆé¢„ç®—": "ENERGY_EXPENSES_MTD_B",
    "èƒ½æºè´¹ç”¨æœˆåŒæœŸ": "ENERGY_EXPENSES_MTD_L",
    "äººå·¥æˆæœ¬æœˆå®žé™…": "PEOPLE_COST_MTD_A",
    "äººå·¥æˆæœ¬æœˆé¢„ç®—": "PEOPLE_COST_MTD_B",
    "äººå·¥æˆæœ¬æœˆåŒæœŸ": "PEOPLE_COST_MTD_L",
    "ç»è¥åˆ©æ¶¦å¹´å®žé™…": "OPERATING_PROFIT_YTD_A",
    "ç»è¥åˆ©æ¶¦å¹´é¢„ç®—": "OPERATING_PROFIT_YTD_B",
    "ç»è¥åˆ©æ¶¦å¹´åŒæœŸ": "OPERATING_PROFIT_YTD_L",
    "æ€»æ”¶å…¥å¹´å®žé™…": "TOTAL_INCOME_YTD_A",
    "æ€»æ”¶å…¥å¹´é¢„ç®—": "TOTAL_INCOME_YTD_B",
    "æ€»æ”¶å…¥å¹´åŒæœŸ": "TOTAL_INCOME_YTD_L",
    "é¤é¥®åˆ©æ¶¦æœˆå®žé™…": "RESTAURANT_PROFIT_MTD_A",
    "é¤é¥®åˆ©æ¶¦æœˆé¢„ç®—": "RESTAURANT_PROFIT_MTD_B",
    "é¤é¥®åˆ©æ¶¦æœˆåŒæœŸ": "RESTAURANT_PROFIT_MTD_L",
    "å®¢æˆ¿åˆ©æ¶¦æœˆå®žé™…": "ROOM_PROFIT_MTD_A",
    "å®¢æˆ¿åˆ©æ¶¦æœˆé¢„ç®—": "ROOM_PROFIT_MTD_B",
    "å®¢æˆ¿åˆ©æ¶¦æœˆåŒæœŸ": "ROOM_PROFIT_MTD_L",
}


class Req(BaseModel):
    sql: str


def get_engine():
    dialect = os.getenv("DB_DIALECT", "mysql+pymysql")
    host = os.getenv("DB_HOST", "mysql")
    port = os.getenv("DB_PORT", "3306")
    db = os.getenv("DB_NAME", "hotel_ai")
    user = os.getenv("DB_USER", "hotel_ai_user")
    password = os.getenv("DB_PASSWORD", "change_me")
    return create_engine(f"{dialect}://{user}:{password}@{host}:{port}/{db}", pool_pre_ping=True)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "real_data_dir": str(REAL_DATA_DIR),
        "warehouse_enabled": USE_LOCAL_WAREHOUSE,
        "warehouse_available": local_warehouse_available(),
        "warehouse_manifest": load_warehouse_manifest(),
    }


def normalize_header(value: str) -> str:
    return value.replace("\ufeff", "").replace("\t", "").strip()


def normalize_scalar(value: str) -> Any:
    text_value = value.strip()
    if text_value == "":
        return None
    if re.fullmatch(r"-?\d+", text_value):
        try:
            return int(text_value)
        except ValueError:
            return text_value
    if re.fullmatch(r"-?\d+\.\d+", text_value):
        try:
            return float(text_value)
        except ValueError:
            return text_value
    return text_value


def find_real_data_file(suffix: str) -> Path | None:
    if not REAL_DATA_DIR.exists():
        return None
    matches = sorted(path for path in REAL_DATA_DIR.iterdir() if path.is_file() and path.name.endswith(suffix))
    return matches[0] if matches else None


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows: list[dict[str, Any]] = []
        for raw_row in reader:
            row = {normalize_header(key): normalize_scalar(value or "") for key, value in raw_row.items() if key is not None}
            rows.append(row)
        return rows


def normalize_overview_rows(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        row: dict[str, Any] = {}
        for source_key, target_key in OVERVIEW_COLUMN_MAP.items():
            if source_key in raw:
                row[target_key] = raw[source_key]
        if row:
            normalized_rows.append(row)
    return normalized_rows


def normalize_detail_rows(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        row = {normalize_header(key): value for key, value in raw.items()}
        row["hotel_name_s"] = row.get("hotel_name_s")
        row["CALMONTH"] = str(row.get("CALMONTH") or "")
        normalized_rows.append(row)
    return normalized_rows


@lru_cache(maxsize=1)
def load_real_data() -> dict[str, list[dict[str, Any]]]:
    overview_file = find_real_data_file("demo2.csv")
    detail_file = find_real_data_file("demo1.csv")
    overview_rows = normalize_overview_rows(read_csv_rows(overview_file)) if overview_file else []
    detail_rows = normalize_detail_rows(read_csv_rows(detail_file)) if detail_file else []
    return {
        "overview": overview_rows,
        "detail": detail_rows,
    }


def extract_in_values(sql: str, column: str) -> list[str]:
    values: list[str] = []
    for match in _IN_CLAUSE_RE.finditer(sql):
        if match.group("column").casefold() != column.casefold():
            continue
        raw_values = match.group("values").split(",")
        for value in raw_values:
            cleaned = value.strip().strip("'").strip('"')
            if cleaned:
                values.append(cleaned)
    return values


def extract_hotel_values(sql: str) -> list[str]:
    values = list(dict.fromkeys(extract_in_values(sql, "HOTEL_NAME_s") + extract_in_values(sql, "hotel_name_s")))
    for match in _HOTEL_LIKE_RE.finditer(sql):
        value = match.group("value").strip()
        if value and value not in values:
            values.append(value)
    return values


def extract_limit(sql: str, default: int) -> int:
    match = _LIMIT_RE.search(sql)
    if not match:
        return default
    return int(match.group("value"))


def normalize_sql_field(field: str) -> str:
    return field.split(".")[-1]


def local_warehouse_available() -> bool:
    return bool(USE_LOCAL_WAREHOUSE and duckdb is not None and DUCKDB_PATH.exists())


def load_warehouse_manifest() -> dict[str, Any] | None:
    if not WAREHOUSE_MANIFEST.exists():
        return None
    try:
        data = json.loads(WAREHOUSE_MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return {
        "source": data.get("source"),
        "synced_at_utc": data.get("synced_at_utc"),
        "latest_month": data.get("latest_month"),
        "tables": {
            name: {"rows": stats.get("rows"), "months": stats.get("months", [])}
            for name, stats in (data.get("tables") or {}).items()
            if isinstance(stats, dict)
        },
    }


def run_local_warehouse_query(sql: str) -> list[dict[str, Any]]:
    if not local_warehouse_available():
        raise RuntimeError("local warehouse is not available")
    assert duckdb is not None
    with duckdb.connect(str(DUCKDB_PATH), read_only=True) as conn:
        result = conn.execute(sql)
        columns = [item[0] for item in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]


def filter_rows(rows: list[dict[str, Any]], calmonth: str | None, hotels: list[str], areas: list[str], hotel_key: str) -> list[dict[str, Any]]:
    filtered = rows
    if calmonth:
        filtered = [row for row in filtered if str(row.get("CALMONTH") or "") == calmonth]
    if hotels:
        filtered = [
            row
            for row in filtered
            if any(hotel == str(row.get(hotel_key) or "") or hotel in str(row.get(hotel_key) or "") for hotel in hotels)
        ]
    if areas:
        filtered = [row for row in filtered if str(row.get("area") or "") in areas]
    return filtered


def run_real_overview_query(sql: str) -> list[dict[str, Any]]:
    field_match = _OVERVIEW_FIELD_RE.search(sql)
    if not field_match:
        return []
    actual_field = normalize_sql_field(field_match.group("actual"))
    compare_field = normalize_sql_field(field_match.group("compare"))
    calmonth_match = _CALMONTH_RE.search(sql)
    calmonth = calmonth_match.group("value") if calmonth_match else None
    hotels = extract_hotel_values(sql)
    areas = list(dict.fromkeys(extract_in_values(sql, "area")))
    limit = extract_limit(sql, 50)

    rows = filter_rows(load_real_data()["overview"], calmonth, hotels, areas, "HOTEL_NAME_s")
    result_rows: list[dict[str, Any]] = []
    for row in rows[:limit]:
        actual_value = row.get(actual_field)
        compare_value = row.get(compare_field)
        diff_rate = None
        if isinstance(actual_value, (int, float)) and isinstance(compare_value, (int, float)) and compare_value not in (0, 0.0):
            diff_rate = (actual_value - compare_value) / compare_value
        result_rows.append(
            {
                "hotel_name": row.get("HOTEL_NAME_s"),
                "area": row.get("area"),
                "brand": row.get("brand"),
                "brand_child": row.get("brand_child"),
                "builder": row.get("Builder"),
                "brand_level": row.get("brand_level"),
                "city_level": row.get("city_level"),
                "rooms": row.get("rooms"),
                "build_area": row.get("build_area"),
                "total_income_actual": row.get("TOTAL_INCOME_MTD_A"),
                "total_income_budget": row.get("TOTAL_INCOME_MTD_B"),
                "total_income_last_year": row.get("TOTAL_INCOME_MTD_L"),
                "room_income_actual": row.get("ROOM_INCOME_MTD_A"),
                "room_income_budget": row.get("ROOM_INCOME_MTD_B"),
                "room_income_last_year": row.get("ROOM_INCOME_MTD_L"),
                "restaurant_income_actual": row.get("RESTAURANT_INCOME_MTD_A"),
                "restaurant_income_budget": row.get("RESTAURANT_INCOME_MTD_B"),
                "restaurant_income_last_year": row.get("RESTAURANT_INCOME_MTD_L"),
                "banquet_income_actual": row.get("BANQUET_INCOME_MTD_A"),
                "banquet_income_budget": row.get("BANQUET_INCOME_MTD_B"),
                "banquet_income_last_year": row.get("BANQUET_INCOME_MTD_L"),
                "other_dept_income_actual": row.get("OTHER_DEPT_INCOME_MTD_A"),
                "other_rate_income_actual": row.get("OTHER_RATE_INCOME_MTD_A"),
                "operating_profit_actual": row.get("OPERATING_PROFIT_MTD_A"),
                "operating_profit_budget": row.get("OPERATING_PROFIT_MTD_B"),
                "operating_profit_last_year": row.get("OPERATING_PROFIT_MTD_L"),
                "owner_profit_actual": row.get("OWNER_PROFIT_MTD_A"),
                "room_profit_actual": row.get("ROOM_PROFIT_MTD_A"),
                "restaurant_profit_actual": row.get("RESTAURANT_PROFIT_MTD_A"),
                "rental_rooms_actual": row.get("RENTAL_ROOMS_NUM_MTD_A"),
                "adr_actual": row.get("AVE_HOUSE_PRICE_MTD_A"),
                "adr_budget": row.get("AVE_HOUSE_PRICE_MTD_B"),
                "adr_last_year": row.get("AVE_HOUSE_PRICE_MTD_L"),
                "occupancy_rate_actual": row.get("OCCUPANCY_RATE_MTD_A"),
                "occupancy_rate_budget": row.get("OCCUPANCY_RATE_MTD_B"),
                "occupancy_rate_last_year": row.get("OCCUPANCY_RATE_MTD_L"),
                "revpar_actual": row.get("INCOME_PER_ROOM_MTD_A"),
                "revpar_budget": row.get("INCOME_PER_ROOM_MTD_B"),
                "revpar_last_year": row.get("INCOME_PER_ROOM_MTD_L"),
                "room_cost_actual": row.get("ROOM_COST_MTD_A"),
                "restaurant_cost_actual": row.get("RESTAURANT_COST_MTD_A"),
                "food_cost_actual": row.get("FOOD_COST_MTD_A"),
                "wine_cost_actual": row.get("WINE_COSE_MTD_A"),
                "admin_expenses_actual": row.get("ADMINI_EXPENSES_MTD_A"),
                "energy_expenses_actual": row.get("ENERGY_EXPENSES_MTD_A"),
                "people_cost_actual": row.get("PEOPLE_COST_MTD_A"),
                "actual_value": actual_value,
                "compare_value": compare_value,
                "diff_value": actual_value - compare_value if isinstance(actual_value, (int, float)) and isinstance(compare_value, (int, float)) else None,
                "diff_rate": diff_rate,
            }
        )
    return result_rows


def run_real_detail_query(sql: str) -> list[dict[str, Any]]:
    field_match = _DETAIL_FIELD_RE.search(sql)
    if not field_match:
        return []
    compare_field = field_match.group("compare")
    calmonth_match = _CALMONTH_RE.search(sql)
    calmonth = calmonth_match.group("value") if calmonth_match else None
    hotels = extract_hotel_values(sql)
    limit = extract_limit(sql, 20)

    rows = filter_rows(load_real_data()["detail"], calmonth, hotels, [], "hotel_name_s")
    rows = [row for row in rows if not row.get("is_total")]

    result_rows: list[dict[str, Any]] = []
    for row in rows:
        actual_value = row.get("mtd_a")
        compare_value = row.get(compare_field)
        diff_value = None
        diff_rate = None
        if isinstance(actual_value, (int, float)) and isinstance(compare_value, (int, float)):
            diff_value = actual_value - compare_value
            if compare_value not in (0, 0.0):
                diff_rate = diff_value / compare_value
        result_rows.append(
            {
                "hotel_name": row.get("hotel_name_s"),
                "area": row.get("area"),
                "dept": row.get("Dept"),
                "account_name": row.get("account_name"),
                "actual_value": actual_value,
                "compare_value": compare_value,
                "diff_value": diff_value,
                "diff_rate": diff_rate,
            }
        )

    result_rows.sort(key=lambda item: abs(item.get("diff_value") or 0), reverse=True)
    return result_rows[:limit]


def fallback_rows(sql_upper: str) -> list[dict[str, Any]]:
    # Synthetic fallbacks are intentionally disabled to avoid leaking fake data.
    return []


@app.post("/api/v1/db/query")
def db_query(payload: Req):
    if local_warehouse_available():
        try:
            rows = run_local_warehouse_query(payload.sql)
            return {
                "rows": rows,
                "row_count": len(rows),
                "source": "local_warehouse",
                "warehouse_manifest": load_warehouse_manifest(),
            }
        except Exception:
            pass

    try:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text(payload.sql))
            rows = [dict(row._mapping) for row in result]
            return {"rows": rows, "row_count": len(rows), "source": "database"}
    except Exception:
        sql_upper = payload.sql.upper()
        if "VW_PNL_FACT" in sql_upper or "ADS_HOTEL_PNL_DETAIL_WIDE" in sql_upper:
            rows = run_real_detail_query(payload.sql)
        elif "WDDM_DIM_OVERVIEW_COCKPIT_F" in sql_upper or "ADS_HOTEL_OPERATION_OVERVIEW_WIDE" in sql_upper:
            rows = run_real_overview_query(payload.sql)
        else:
            rows = []

        if not rows:
            return {"rows": [], "row_count": 0, "source": "empty_result"}
        return {"rows": rows, "row_count": len(rows), "source": "real_csv"}


