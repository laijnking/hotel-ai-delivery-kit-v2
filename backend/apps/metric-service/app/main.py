from functools import lru_cache
from pathlib import Path
import re

import yaml
from fastapi import FastAPI, HTTPException

app = FastAPI(title="metric-service")
CONFIG = Path(__file__).resolve().parents[3] / "configs" / "metric_dictionary.yaml"
_NORMALIZE_RE = re.compile(r"\s+")


@app.get("/health")
def health():
    return {"status": "ok"}


@lru_cache(maxsize=1)
def load_metrics() -> list[dict]:
    with open(CONFIG, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    metrics = cfg.get("metrics", [])
    if not isinstance(metrics, list):
        raise HTTPException(status_code=500, detail="metric dictionary is invalid")
    return metrics


def normalize(value: str | None) -> str:
    if not value:
        return ""
    return _NORMALIZE_RE.sub("", value).casefold()


def metric_candidates(item: dict) -> list[str]:
    candidates = [
        item.get("metric_code", ""),
        item.get("name_cn", ""),
    ]
    aliases = item.get("aliases", [])
    if isinstance(aliases, list):
        candidates.extend(aliases)
    return [str(candidate).strip() for candidate in candidates if str(candidate).strip()]


@app.get("/api/v1/metrics/{metric_code}")
def get_metric(metric_code: str):
    requested = metric_code.strip()
    requested_norm = normalize(requested)
    items = load_metrics()
    for item in items:
        candidates = metric_candidates(item)
        if any(normalize(candidate) == requested_norm for candidate in candidates):
            response = dict(item)
            response.setdefault("aliases", [])
            response.setdefault("compare_modes", ["actual", "budget", "yoy"])
            response.setdefault("period_fields", {})
            return response
    available_codes = [str(item.get("metric_code", "")) for item in items if item.get("metric_code")]
    raise HTTPException(
        status_code=404,
        detail={
            "message": "metric not found",
            "metric_code": requested,
            "available_metric_codes": available_codes,
        },
    )
