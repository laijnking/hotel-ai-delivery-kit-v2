from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE_DIR = Path(os.getenv("WAREHOUSE_DIR", ROOT / "backend" / "runtime" / "warehouse"))
REAL_DATA_DIR = Path(os.getenv("REAL_DATA_DIR", ROOT.parent / "real-data"))
DUCKDB_PATH = WAREHOUSE_DIR / "hotel_warehouse.duckdb"
MANIFEST_PATH = WAREHOUSE_DIR / "sync_manifest.json"
STAGING_DIR = WAREHOUSE_DIR / "staging"
PARQUET_DIR = WAREHOUSE_DIR / "parquet"

SYNC_TABLES = {
    "wddm_dim_overview_cockpit_f": "SELECT * FROM wddm_dim_overview_cockpit_f",
    "vw_pnl_fact": "SELECT * FROM vw_pnl_fact",
    "dim_allhotel_slcp": "SELECT * FROM dim_allhotel_slcp",
}


def load_windows_user_env(names: list[str]) -> None:
    if os.name != "nt":
        return
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            for name in names:
                if os.getenv(name):
                    continue
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                except FileNotFoundError:
                    continue
                if value:
                    os.environ[name] = str(value)
    except Exception:
        return


def get_engine():
    env_names = ["DB_DIALECT", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    load_windows_user_env(env_names)
    dialect = os.getenv("DB_DIALECT", "mysql+pymysql")
    host = os.getenv("DB_HOST", "")
    port = os.getenv("DB_PORT", "3306")
    db = os.getenv("DB_NAME", "")
    user = os.getenv("DB_USER", "")
    password = os.getenv("DB_PASSWORD", "")
    missing = [name for name in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD") if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"missing database environment variables: {', '.join(missing)}")
    return create_engine(f"{dialect}://{user}:{password}@{host}:{port}/{db}", pool_pre_ping=True)


def ensure_dirs(reset: bool) -> None:
    WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)
    if reset and DUCKDB_PATH.exists():
        DUCKDB_PATH.unlink()
    if reset and PARQUET_DIR.exists():
        shutil.rmtree(PARQUET_DIR)
    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)


def write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> int:
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in keys})
    return len(rows)


def export_database_table(table_name: str, query: str) -> Path:
    path = STAGING_DIR / f"{table_name}.csv"
    engine = get_engine()
    with engine.connect() as conn, path.open("w", encoding="utf-8-sig", newline="") as file:
        result = conn.execution_options(stream_results=True).execute(text(query))
        columns = list(result.keys())
        writer = csv.writer(file)
        writer.writerow(columns)
        while True:
            batch = result.fetchmany(5000)
            if not batch:
                break
            for row in batch:
                writer.writerow([row._mapping.get(column) for column in columns])
    return path


def load_db_executor_module():
    module_path = ROOT / "backend" / "apps" / "db-executor-service" / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("warehouse_db_executor", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def export_csv_fallback_tables() -> dict[str, Path]:
    db_executor = load_db_executor_module()
    data = db_executor.load_real_data()
    paths: dict[str, Path] = {}

    overview_rows: list[dict[str, Any]] = []
    dim_rows_by_name: dict[str, dict[str, Any]] = {}
    for row in data.get("overview", []):
        item = dict(row)
        item["hotel_name"] = item.get("HOTEL_NAME_s")
        overview_rows.append(item)
        hotel_name = str(item.get("HOTEL_NAME_s") or "").strip()
        if hotel_name:
            dim_rows_by_name[hotel_name] = {
                "hotel_name_f": hotel_name,
                "hotel_name_s": hotel_name,
                "brand": item.get("brand"),
                "brand_child": item.get("brand_child"),
                "area": item.get("area"),
                "Builder": item.get("Builder"),
                "brand_level": item.get("brand_level"),
                "city_level": item.get("city_level"),
                "rooms": item.get("rooms"),
                "build_area": item.get("build_area"),
            }

    paths["wddm_dim_overview_cockpit_f"] = STAGING_DIR / "wddm_dim_overview_cockpit_f.csv"
    write_rows_csv(paths["wddm_dim_overview_cockpit_f"], overview_rows)
    paths["dim_allhotel_slcp"] = STAGING_DIR / "dim_allhotel_slcp.csv"
    write_rows_csv(paths["dim_allhotel_slcp"], list(dim_rows_by_name.values()))
    paths["vw_pnl_fact"] = STAGING_DIR / "vw_pnl_fact.csv"
    write_rows_csv(paths["vw_pnl_fact"], data.get("detail", []))
    return paths


def create_duckdb_tables(csv_paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    table_stats: dict[str, dict[str, Any]] = {}
    with duckdb.connect(str(DUCKDB_PATH)) as conn:
        for table_name, csv_path in csv_paths.items():
            conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            conn.execute(
                f"""
                CREATE TABLE {table_name} AS
                SELECT * FROM read_csv_auto(?, header=true, union_by_name=true, sample_size=-1)
                """,
                [str(csv_path)],
            )
            row_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            months: list[str] = []
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()]
            calmonth_column = next((column for column in columns if str(column).casefold() == "calmonth"), None)
            if calmonth_column:
                months = [
                    str(row[0])
                    for row in conn.execute(
                        f"SELECT DISTINCT {calmonth_column} FROM {table_name} WHERE {calmonth_column} IS NOT NULL ORDER BY {calmonth_column}"
                    ).fetchall()
                ]
            parquet_path = PARQUET_DIR / table_name
            parquet_path.mkdir(parents=True, exist_ok=True)
            conn.execute(f"COPY {table_name} TO ? (FORMAT PARQUET)", [str(parquet_path / "data.parquet")])
            table_stats[table_name] = {
                "rows": row_count,
                "months": months,
                "parquet_path": str(parquet_path),
            }
    return table_stats


def write_manifest(source: str, table_stats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    all_months = sorted({month for stats in table_stats.values() for month in stats.get("months", [])})
    manifest = {
        "schema_version": 1,
        "source": source,
        "synced_at_utc": datetime.now(timezone.utc).isoformat(),
        "duckdb_path": str(DUCKDB_PATH),
        "parquet_dir": str(PARQUET_DIR),
        "latest_month": all_months[-1] if all_months else None,
        "tables": table_stats,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def sync(source: str, reset: bool) -> dict[str, Any]:
    ensure_dirs(reset)
    if source == "database":
        csv_paths = {table: export_database_table(table, query) for table, query in SYNC_TABLES.items()}
    elif source == "csv":
        csv_paths = export_csv_fallback_tables()
    else:
        raise ValueError(f"unsupported source: {source}")
    table_stats = create_duckdb_tables(csv_paths)
    return write_manifest(source, table_stats)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Sync Hotel AI source data into a local DuckDB warehouse.")
    parser.add_argument("--source", choices=["database", "csv"], default="database", help="Source to sync from.")
    parser.add_argument("--reset", action="store_true", help="Recreate local DuckDB and parquet outputs.")
    args = parser.parse_args()

    manifest = sync(args.source, args.reset)
    print(
        json.dumps(
            {
                "source": manifest["source"],
                "latest_month": manifest["latest_month"],
                "duckdb_path": manifest["duckdb_path"],
                "tables": {name: stats["rows"] for name, stats in manifest["tables"].items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
