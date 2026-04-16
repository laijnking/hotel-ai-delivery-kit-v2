from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="auth-service")


ROLE_CATALOG = {
    "GROUP_ADMIN": {
        "role_label": "集团管理员",
        "scope_level": "global",
        "permissions": [
            "auth:read",
            "report:read",
            "report:export",
            "sql:unrestricted",
            "sql:scope:all",
        ],
    },
    "AREA_MANAGER": {
        "role_label": "区域经理",
        "scope_level": "area",
        "permissions": [
            "auth:read",
            "report:read",
            "report:export",
            "report:compare",
            "sql:scoped",
            "sql:scope:area",
        ],
    },
    "HOTEL_MANAGER": {
        "role_label": "酒店经理",
        "scope_level": "hotel",
        "permissions": [
            "auth:read",
            "report:read",
            "report:export",
            "sql:scoped",
            "sql:scope:hotel",
        ],
    },
}

DEFAULT_ROLE = "AREA_MANAGER"


class Req(BaseModel):
    user_id: str
    role: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/auth/context")
def auth_context(payload: Req):
    requested_role = (payload.role or DEFAULT_ROLE).strip().upper()
    resolved_role = requested_role if requested_role in ROLE_CATALOG else DEFAULT_ROLE
    effective_role = ROLE_CATALOG[resolved_role]
    allowed_areas = ["ALL"]
    allowed_hotels = ["ALL"]

    return {
        "user_id": payload.user_id,
        "requested_role": requested_role,
        "resolved_role": resolved_role,
        "role_label": effective_role["role_label"],
        "scope_level": effective_role["scope_level"],
        "permissions": effective_role["permissions"],
        "allowed_areas": allowed_areas,
        "allowed_hotels": allowed_hotels,
        "sql_scope": {
            "area_column": "area",
            "hotel_column": "HOTEL_NAME_s",
            "allowed_areas": allowed_areas,
            "allowed_hotels": allowed_hotels,
        },
        "can": {
            "view_reports": "report:read" in effective_role["permissions"],
            "export_reports": "report:export" in effective_role["permissions"],
            "audit_logs": False,
            "bypass_sql_guardrail": "sql:unrestricted" in effective_role["permissions"],
        },
        "is_fallback_role": requested_role not in ROLE_CATALOG,
    }
