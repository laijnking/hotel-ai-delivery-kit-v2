from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI(title="audit-service")

LOG_DIR = Path(
    os.getenv(
        "AUDIT_LOG_DIR",
        Path(__file__).resolve().parents[3] / "runtime" / "audit",
    )
)
LOG_LOCK = threading.Lock()


class Req(BaseModel):
    model_config = ConfigDict(extra="allow")

    trace_id: str
    user_id: str | None = None
    role: str | None = None
    question: str
    request_id: str | None = None
    endpoint: str | None = None
    parsed_intent: dict[str, Any] | None = None
    sql_text: str | None = None
    rewritten_sql: str | None = None
    sql_safe: bool | None = None
    sql_reasons: list[str] = Field(default_factory=list)
    result_summary: str | None = None
    status: str | None = None
    latency_ms: int | None = None
    error_message: str | None = None
    scope: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _log_path_for_now() -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return LOG_DIR / f"audit-{today}.jsonl"


def _write_jsonl(record: dict[str, Any]) -> Path:
    target = _log_path_for_now()
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with LOG_LOCK:
        with target.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
    return target


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/audit/log")
def audit(payload: Req):
    record = payload.model_dump(exclude_none=True)
    record.update(
        {
            "service": "audit-service",
            "schema_version": 1,
            "event_type": record.get("event_type", "query_execution"),
            "received_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )

    try:
        stored_at = _write_jsonl(record)
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail={"accepted": False, "error": f"failed to persist audit record: {exc}"},
        ) from exc

    return {
        "accepted": True,
        "stored_at": str(stored_at),
        "trace_id": payload.trace_id,
    }
