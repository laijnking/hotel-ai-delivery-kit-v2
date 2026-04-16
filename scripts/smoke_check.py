from __future__ import annotations

import json
import socket
import sys
import urllib.error
import urllib.request


SERVICES = {
    "frontend": "http://127.0.0.1:3000",
    "auth-service": "http://127.0.0.1:8105/health",
    "metric-service": "http://127.0.0.1:8102/health",
    "semantic-service": "http://127.0.0.1:8101/health",
    "sql-guardrail-service": "http://127.0.0.1:8103/health",
    "db-executor-service": "http://127.0.0.1:8106/health",
    "explanation-service": "http://127.0.0.1:8104/health",
    "audit-service": "http://127.0.0.1:8107/health",
    "ai-query-service": "http://127.0.0.1:8100/health",
}


def fetch_json(url: str, payload: dict | None = None, timeout: int = 30) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def assert_port_open(host: str, port: int) -> None:
    with socket.create_connection((host, port), timeout=10):
        return None


def main() -> int:
    failures: list[str] = []

    for name, url in SERVICES.items():
        try:
            if name == "frontend":
                assert_port_open("127.0.0.1", 3000)
                continue
            result = fetch_json(url)
            if result.get("status") != "ok":
                failures.append(f"{name} returned unexpected payload: {result}")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            failures.append(f"{name} health check failed: {exc}")

    try:
        query_result = fetch_json(
            "http://127.0.0.1:8100/api/v1/ai/query",
            {
                "question": "本月华南区哪些酒店经营利润未达预算？",
                "context": {"time_scope": "202601", "language": "zh-CN"},
                "auth": {"user_id": "u001", "role": "AREA_MANAGER"},
            },
            timeout=75,
        )
        if "summary" not in query_result:
            failures.append(f"ai-query-service returned invalid query payload: {query_result}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        failures.append(f"ai-query-service query failed: {exc}")

    try:
        report_result = fetch_json(
            "http://127.0.0.1:8100/api/v1/ai/report",
            {
                "question": "生成本月华南区经营利润管理摘要",
                "context": {"time_scope": "202601", "language": "zh-CN"},
                "auth": {"user_id": "u001", "role": "AREA_MANAGER"},
            },
            timeout=75,
        )
        if "report_markdown" not in report_result:
            failures.append(f"ai-query-service returned invalid report payload: {report_result}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        failures.append(f"ai-query-service report failed: {exc}")

    if failures:
        for item in failures:
            print(f"[FAIL] {item}")
        return 1

    print("[OK] All services passed smoke check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
