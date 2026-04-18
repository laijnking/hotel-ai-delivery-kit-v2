from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evals" / "cases" / "semantic_sql_cases.yaml"
REPORT_DIR = ROOT / "evals" / "reports"


def load_module(name: str, relative_path: str):
    module_path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def load_cases(path: Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    cases = data.get("cases", []) if isinstance(data, dict) else []
    if not isinstance(cases, list):
        raise ValueError(f"cases must be a list: {path}")
    return [case for case in cases if isinstance(case, dict)]


def normalize(value: Any) -> Any:
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    return value


def assert_expected(case: dict[str, Any], parsed: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    expected = case.get("expected", {})
    if not isinstance(expected, dict):
        return ["expected must be a mapping"]

    for key, expected_value in expected.items():
        actual_value = parsed.get(key)
        if normalize(actual_value) != normalize(expected_value):
            failures.append(f"expected parsed.{key}={expected_value!r}, got {actual_value!r}")
    return failures


def value_at_path(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def assert_expected_paths(case: dict[str, Any], parsed: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    expected = case.get("expected_paths", {})
    if not isinstance(expected, dict):
        return failures
    for path, expected_value in expected.items():
        actual_value = value_at_path(parsed, str(path))
        if normalize(actual_value) != normalize(expected_value):
            failures.append(f"expected parsed.{path}={expected_value!r}, got {actual_value!r}")
    return failures


def assert_sql(case: dict[str, Any], sql: str) -> list[str]:
    failures: list[str] = []
    assertions = case.get("sql_assertions", {})
    if not isinstance(assertions, dict):
        return failures

    for item in assertions.get("contains", []) or []:
        text = str(item)
        if text not in sql:
            failures.append(f"SQL should contain {text!r}")

    for item in assertions.get("not_contains", []) or []:
        text = str(item)
        if text in sql:
            failures.append(f"SQL should not contain {text!r}")

    return failures


def answer_text(answer: dict[str, Any]) -> str:
    sections = answer.get("report_sections", [])
    section_text = ""
    if isinstance(sections, list):
        section_text = "\n".join(
            f"{item.get('title', '')}\n{item.get('content', '')}"
            for item in sections
            if isinstance(item, dict)
        )
    return "\n".join(
        [
            str(answer.get("summary") or ""),
            section_text,
            "\n".join(str(item) for item in answer.get("key_points", []) if item) if isinstance(answer.get("key_points"), list) else "",
        ]
    )


def assert_answer(case: dict[str, Any], answer: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    assertions = case.get("answer_assertions", {})
    if not isinstance(assertions, dict):
        return failures

    text = answer_text(answer)
    section_titles = [
        str(item.get("title") or "")
        for item in answer.get("report_sections", [])
        if isinstance(item, dict)
    ]

    expected_sections = assertions.get("sections", []) or []
    for section in expected_sections:
        if str(section) not in section_titles:
            failures.append(f"answer should include section {str(section)!r}")

    for item in assertions.get("must_mention", []) or []:
        value = str(item)
        if value not in text:
            failures.append(f"answer should mention {value!r}")

    for item in assertions.get("not_mention", []) or []:
        value = str(item)
        if value in text:
            failures.append(f"answer should not mention {value!r}")

    return failures


def build_sql_for_case(ai_query_main, metric_main, parsed: dict[str, Any]) -> str:
    metric_def = metric_main.get_metric(parsed["metric_code"])
    if parsed.get("intent") == "explain":
        return ai_query_main.build_explain_sql(
            parsed,
            allowed_hotels=["ALL"],
            requested_hotels=parsed.get("requested_hotels", []),
            requested_areas=parsed.get("requested_areas", []),
        )
    query_route = ai_query_main._query_route(parsed)
    if query_route.startswith("portfolio"):
        return ai_query_main.build_portfolio_sql(
            metric_def,
            parsed,
            allowed_hotels=["ALL"],
            requested_hotels=ai_query_main.effective_requested_hotels(parsed),
            requested_areas=parsed.get("requested_areas", []),
        )
    return ai_query_main.build_sql(
        metric_def,
        parsed,
        allowed_hotels=["ALL"],
        requested_hotels=parsed.get("requested_hotels", []),
        requested_areas=parsed.get("requested_areas", []),
    )


def build_answer_for_case(explanation_main, case: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    rows = case.get("answer_sample_rows", [])
    if not isinstance(rows, list):
        rows = []
    with patch.object(explanation_main, "_call_llm_summary", return_value=None):
        return explanation_main.explain(
            explanation_main.Req(
                question=str(case.get("question") or ""),
                parsed_intent=parsed,
                rows=[row for row in rows if isinstance(row, dict)],
            )
        )


def run_eval(cases_path: Path) -> tuple[int, list[dict[str, Any]]]:
    semantic_main = load_module("eval_semantic_main", "apps/semantic-service/app/main.py")
    metric_main = load_module("eval_metric_main", "apps/metric-service/app/main.py")
    ai_query_main = load_module("eval_ai_query_main", "apps/ai-query-service/app/main.py")
    explanation_main = load_module("eval_explanation_main", "apps/explanation-service/app/main.py")

    results: list[dict[str, Any]] = []
    cases = load_cases(cases_path)

    for case in cases:
        case_id = str(case.get("id") or "unnamed_case")
        question = str(case.get("question") or "")
        time_scope = str(case.get("time_scope") or "202601")
        failures: list[str] = []
        parsed: dict[str, Any] = {}
        sql = ""
        answer: dict[str, Any] = {}

        try:
            with patch.object(semantic_main, "call_llm_parse", return_value=None):
                parsed = semantic_main.parse(semantic_main.Req(question=question, time_scope=time_scope))
            failures.extend(assert_expected(case, parsed))
            failures.extend(assert_expected_paths(case, parsed))
            sql = build_sql_for_case(ai_query_main, metric_main, parsed)
            failures.extend(assert_sql(case, sql))
            if isinstance(case.get("answer_assertions"), dict):
                answer = build_answer_for_case(explanation_main, case, parsed)
                failures.extend(assert_answer(case, answer))
        except Exception as exc:  # pragma: no cover - surfaced in report
            failures.append(f"exception: {type(exc).__name__}: {exc}")

        results.append(
            {
                "id": case_id,
                "question": question,
                "passed": not failures,
                "failures": failures,
                "parsed": parsed,
                "sql": sql,
                "answer": answer,
            }
        )

    failed_count = sum(1 for item in results if not item["passed"])
    return failed_count, results


def write_report(results: list[dict[str, Any]]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = REPORT_DIR / f"eval_report_{timestamp}.md"
    total = len(results)
    failed = sum(1 for item in results if not item["passed"])
    passed = total - failed

    lines = [
        "# Hotel AI Eval Report",
        "",
        f"- Generated at: {timestamp}",
        f"- Total: {total}",
        f"- Passed: {passed}",
        f"- Failed: {failed}",
        "",
    ]
    for item in results:
        status = "PASS" if item["passed"] else "FAIL"
        lines.extend(
            [
                f"## {status} {item['id']}",
                "",
                f"Question: {item['question']}",
                "",
            ]
        )
        if item["failures"]:
            lines.append("Failures:")
            for failure in item["failures"]:
                lines.append(f"- {failure}")
            lines.append("")
        lines.append("Parsed:")
        lines.append("```json")
        lines.append(json.dumps(item["parsed"], ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
        lines.append("SQL:")
        lines.append("```sql")
        lines.append(item["sql"])
        lines.append("```")
        lines.append("")
        if item.get("answer"):
            lines.append("Answer:")
            lines.append("```json")
            lines.append(json.dumps(item["answer"], ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Hotel AI semantic/SQL eval cases.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="Path to eval case yaml.")
    parser.add_argument("--write-report", action="store_true", help="Write a markdown report under backend/evals/reports.")
    args = parser.parse_args()

    failed_count, results = run_eval(Path(args.cases))
    total = len(results)
    passed = total - failed_count

    for item in results:
        status = "PASS" if item["passed"] else "FAIL"
        print(f"[{status}] {item['id']}")
        for failure in item["failures"]:
            print(f"  - {failure}")

    print(f"[SUMMARY] total={total} passed={passed} failed={failed_count}")

    if args.write_report:
        report_path = write_report(results)
        print(f"[REPORT] {report_path}")

    return 1 if failed_count else 0


if __name__ == "__main__":
    sys.exit(main())
