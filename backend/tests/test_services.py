import importlib.util
import json
import shutil
import unittest
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
TEST_TMP_ROOT = ROOT.parent / "runtime" / "tmp-tests"


@contextmanager
def workspace_temp_dir():
    TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    temp_dir = TEST_TMP_ROOT / f"tmp-{uuid4().hex[:8]}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield str(temp_dir)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def load_module(name: str, relative_path: str):
    module_path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def try_load_module(name: str, relative_path: str):
    try:
        return load_module(name, relative_path), None
    except ModuleNotFoundError as exc:
        return None, str(exc)


semantic_main, semantic_error = try_load_module("semantic_main", "apps/semantic-service/app/main.py")
metric_main, metric_error = try_load_module("metric_main", "apps/metric-service/app/main.py")
guardrail_main, guardrail_error = try_load_module("guardrail_main", "apps/sql-guardrail-service/app/main.py")
explanation_main, explanation_error = try_load_module("explanation_main", "apps/explanation-service/app/main.py")
ai_query_main, ai_query_error = try_load_module("ai_query_main", "apps/ai-query-service/app/main.py")
db_executor_main, db_executor_error = try_load_module("db_executor_main", "apps/db-executor-service/app/main.py")
eval_runner, eval_error = try_load_module("eval_runner", "evals/run_eval.py")


class ServiceSmokeTests(unittest.TestCase):
    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_parse_budget_question(self):
        req = semantic_main.Req(question="本月哪些酒店经营利润未达预算？", time_scope="202601")
        result = semantic_main.parse(req)
        self.assertEqual(result["metric_code"], "OPERATING_PROFIT")
        self.assertEqual(result["compare_mode"], "budget")
        self.assertEqual(result["variance_direction"], "below")

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_requests_clarification_for_generic_prompt(self):
        req = semantic_main.Req(question="帮我分析一下经营利润", time_scope="202601")
        result = semantic_main.parse(req)
        self.assertTrue(result["needs_clarification"])
        self.assertTrue(result["clarification_question"])
        self.assertGreaterEqual(len(result["clarification_options"]), 2)

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_parse_hotel_month_business_overview(self):
        req = semantic_main.Req(question="看一下江门嘉华酒店3月的经营情况", time_scope="202601")
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(req)
        self.assertEqual(result["metric_code"], "OWNER_PROFIT")
        self.assertEqual(result["compare_mode"], "yoy")
        self.assertEqual(result["time_scope"], "202603")
        self.assertEqual(result["requested_hotels"], ["江门嘉华"])
        self.assertEqual(result["skill_id"], "hotel_operation_overview")
        self.assertFalse(result["needs_clarification"])

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_parse_hotel_month_income_situation(self):
        req = semantic_main.Req(question="广州丽思卡尔顿酒店3月的收入情况怎么样？", time_scope="202601")
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(req)
        self.assertEqual(result["metric_code"], "TOTAL_INCOME")
        self.assertEqual(result["compare_mode"], "yoy")
        self.assertEqual(result["time_scope"], "202603")
        self.assertEqual(result["requested_hotels"], ["广州丽思卡尔顿酒店"])
        self.assertEqual(result["skill_id"], "hotel_income_overview")
        self.assertFalse(result["needs_clarification"])

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_skill_registry_matches_business_phrases(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            income_result = semantic_main.parse(semantic_main.Req(question="广州柏悦3月营收表现", time_scope="202601"))
            profit_result = semantic_main.parse(semantic_main.Req(question="江门嘉华3月利润情况", time_scope="202601"))
            operation_result = semantic_main.parse(semantic_main.Req(question="北京富力万丽酒店1月的经营情况怎么样？", time_scope="202601"))
        self.assertEqual(income_result["skill_id"], "hotel_income_overview")
        self.assertEqual(income_result["metric_code"], "TOTAL_INCOME")
        self.assertEqual(income_result["compare_mode"], "yoy")
        self.assertEqual(income_result["requested_hotels"], ["广州柏悦"])
        self.assertEqual(profit_result["skill_id"], "hotel_profit_overview")
        self.assertEqual(profit_result["metric_code"], "OWNER_PROFIT")
        self.assertEqual(profit_result["compare_mode"], "yoy")
        self.assertEqual(profit_result["requested_hotels"], ["江门嘉华"])
        self.assertEqual(operation_result["skill_id"], "hotel_operation_overview")
        self.assertEqual(operation_result["metric_code"], "OWNER_PROFIT")
        self.assertEqual(operation_result["requested_hotels"], ["北京富力万丽酒店"])

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_parse_company_all_hotels_as_portfolio_scope(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(semantic_main.Req(question="请分析一下3月份公司的所有酒店的经营情况", time_scope="202601"))
        self.assertEqual(result["compare_mode"], "yoy")
        self.assertEqual(result["query_plan"]["query_grain"], "portfolio")
        self.assertEqual(result["query_plan"]["query_object_type"], "hotel_group")
        self.assertEqual(result["query_plan"]["query_object_label"], "公司全部酒店")

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_detects_management_area_group_by_dimensions(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(
                semantic_main.Req(
                    question="请分析一下公司所有酒店3月份的经营情况，请汇总到管理公司和区域维度输出",
                    time_scope="202601",
                )
            )
        self.assertEqual(result["query_plan"]["query_grain"], "portfolio")
        self.assertEqual(result["query_plan"]["analysis_mode"], "group_by_dimension_report")
        self.assertEqual(result["query_plan"]["group_by_dimensions"], ["manage_corp", "area", "manage_corp_area"])
        self.assertEqual(result["query_plan"]["metric_bundle_code"], "group_dimension_overview")
        self.assertEqual(result["query_plan"]["report_template_code"], "executive_group_dimension")
        self.assertEqual(result["query_plan"]["analysis_focus"], "dimension_comparison")

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_detects_group_by_brand_with_dimension_plan(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(
                semantic_main.Req(
                    question="请分析一下公司所有酒店3月份的经营情况，请汇总到管理公司、区域和品牌维度输出",
                    time_scope="202601",
                )
            )
        self.assertEqual(result["query_plan"]["analysis_mode"], "group_by_dimension_report")
        self.assertIn("brand_child", result["query_plan"]["group_by_dimensions"])
        self.assertEqual(result["query_plan"]["metric_bundle_code"], "group_dimension_overview")
        self.assertEqual(result["query_plan"]["report_template_code"], "executive_group_dimension")

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_continues_from_context_for_follow_up_reason(self):
        req = semantic_main.Req(
            question="继续展开原因",
            time_scope="202603",
            conversation_context={
                "metric_code": "OWNER_PROFIT",
                "compare_mode": "yoy",
                "time_scope": "202603",
                "requested_hotels": ["江门嘉华酒店"],
            },
        )
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(req)
        self.assertEqual(result["metric_code"], "OWNER_PROFIT")
        self.assertEqual(result["compare_mode"], "yoy")
        self.assertEqual(result["requested_hotels"], ["江门嘉华酒店"])
        self.assertEqual(result["query_plan"]["analysis_mode"], "driver_analysis")
        self.assertEqual(result["query_plan"]["follow_up_mode"], "driver")
        self.assertEqual(result["query_plan"]["report_template_code"], "executive_hotel_snapshot")
        self.assertFalse(result["needs_clarification"])

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_refines_scope_without_carrying_previous_hotel_filter(self):
        req = semantic_main.Req(
            question="只看华南区经营情况",
            time_scope="202603",
            conversation_context={
                "metric_code": "OWNER_PROFIT",
                "compare_mode": "yoy",
                "time_scope": "202603",
                "requested_hotels": ["江门嘉华酒店"],
            },
        )
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(req)
        self.assertEqual(result["metric_code"], "OWNER_PROFIT")
        self.assertEqual(result["requested_areas"], ["华南区"])
        self.assertEqual(result["requested_hotels"], [])
        self.assertEqual(result["query_plan"]["follow_up_mode"], "refine_scope")
        self.assertFalse(result["needs_clarification"])

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_uses_entity_catalog_for_area_and_hotel(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            area_result = semantic_main.parse(semantic_main.Req(question="只看海南区本月收入情况", time_scope="202601"))
            hotel_result = semantic_main.parse(semantic_main.Req(question="广州丽思卡尔顿公寓3月收入情况", time_scope="202601"))
        self.assertEqual(area_result["requested_areas"], ["海南区"])
        self.assertEqual(hotel_result["requested_hotels"], ["广州丽思卡尔顿公寓"])
        self.assertNotEqual(hotel_result["requested_hotels"], ["广州丽思卡尔顿酒店"])

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_recognizes_business_dimensions(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(
                semantic_main.Req(question="看华南区万达管理嘉华品牌自建奢华级酒店3月经营情况", time_scope="202601")
            )
        self.assertEqual(result["requested_areas"], ["华南区"])
        self.assertEqual(result["requested_manage_corps"], ["万达品牌"])
        self.assertEqual(result["requested_brand_children"], ["嘉华"])
        self.assertEqual(result["requested_builders"], ["自建"])
        self.assertEqual(result["requested_brand_levels"], ["奢华级"])
        self.assertEqual(result["time_scope"], "202603")

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_tracks_brand_area_month_axes_for_grouped_overview(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(
                semantic_main.Req(question="请按品牌汇总看一下华南区3月份经营情况", time_scope="202601")
            )
        self.assertEqual(result["query_plan"]["analysis_mode"], "group_by_dimension_report")
        self.assertIn("brand_child", result["query_plan"]["group_by_dimensions"])
        self.assertIn("brand", result["query_plan"]["dimension_axes"])
        self.assertIn("area", result["query_plan"]["dimension_axes"])
        self.assertIn("month", result["query_plan"]["dimension_axes"])
        self.assertEqual(result["query_plan"]["analysis_focus"], "dimension_comparison")

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_marks_compare_shift_follow_up_and_inherits_context(self):
        req = semantic_main.Req(
            question="换成同比",
            time_scope="202603",
            conversation_context={
                "metric_code": "OWNER_PROFIT",
                "compare_mode": "budget",
                "time_scope": "202603",
                "requested_areas": ["华南区"],
                "requested_brand_children": ["嘉华"],
            },
        )
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(req)
        self.assertEqual(result["follow_up_mode"], "compare_shift")
        self.assertEqual(result["compare_mode"], "yoy")
        self.assertEqual(result["requested_areas"], ["华南区"])
        self.assertEqual(result["requested_brand_children"], ["嘉华"])
        self.assertEqual(result["query_plan"]["analysis_focus"], "comparison_shift")
        self.assertEqual(result["query_plan"]["query_steps"][0]["step"], "inherit_context")
        self.assertIn("comparison_shift", result["query_plan"]["dimension_axes"])

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_detects_subject_hierarchy_axes(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(
                semantic_main.Req(question="请解释一下江门嘉华餐饮部酒水成本的科目上下级关系", time_scope="202601")
            )
        self.assertIn("餐饮部", result["requested_departments"])
        self.assertIn("酒水成本", result["requested_accounts"])
        self.assertEqual(result["query_plan"]["analysis_focus"], "pnl_hierarchy")
        self.assertIn("subject_hierarchy", result["query_plan"]["dimension_axes"])

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_recognizes_pnl_department_and_account(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(
                semantic_main.Req(question="解释江门嘉华3月餐饮部酒水成本为什么偏高", time_scope="202601")
            )
        self.assertIn("餐饮部", result["requested_departments"])
        self.assertIn("酒水成本", result["requested_accounts"])
        self.assertEqual(result["intent"], "explain")

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_builds_query_plan_for_hotel_group_overview(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(
                semantic_main.Req(question="查一下1月份富力所有酒店的总体经营情况", time_scope="202601")
            )
        self.assertEqual(result["time_scope"], "202601")
        self.assertEqual(result["query_plan"]["query_object_type"], "hotel_group")
        self.assertEqual(result["query_plan"]["query_grain"], "portfolio")
        self.assertEqual(result["query_plan"]["analysis_mode"], "portfolio_overview")
        self.assertEqual(result["query_plan"]["planner_contract_version"], "1.0")
        self.assertEqual(result["query_plan"]["intent"], "query")
        self.assertEqual(result["query_plan"]["time_scope"], "202601")
        self.assertEqual(result["query_plan"]["metrics"][0]["code"], "OWNER_PROFIT")
        self.assertIn("resolve_scope", result["query_plan"]["fast_path"])
        self.assertIn("peer_benchmark", result["query_plan"]["async_path"])
        self.assertIn("pnl_fact", result["query_plan"]["evidence_needed"])
        self.assertGreaterEqual(result["query_plan"]["resolved_hotel_count"], 2)
        self.assertEqual(result["resolved_entities"]["hotel_group"]["group_token"], "富力")
        self.assertEqual(result["resolved_entities"]["hotel_group"]["resolution_basis"], "company_root_all_hotels")
        self.assertFalse(result["resolved_entities"]["hotel_group"]["use_group_token_as_filter"])

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_treats_implicit_summary_as_company_portfolio(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(
                semantic_main.Req(question="汇总一下这个月的经营情况", time_scope="202603")
            )
        self.assertEqual(result["query_plan"]["query_object_type"], "hotel_group")
        self.assertEqual(result["query_plan"]["query_object_label"], "公司全部酒店")
        self.assertEqual(result["query_plan"]["query_grain"], "portfolio")
        self.assertEqual(result["query_plan"]["analysis_mode"], "portfolio_overview")
        self.assertEqual(result["resolved_entities"]["hotel_group"]["resolution_basis"], "company_root_all_hotels")
        self.assertFalse(result["resolved_entities"]["hotel_group"]["use_group_token_as_filter"])

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_treats_all_hotels_summary_as_company_portfolio(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(
                semantic_main.Req(question="汇总一下本月所有酒店的经营情况", time_scope="202603")
            )
        self.assertEqual(result["query_plan"]["query_object_type"], "hotel_group")
        self.assertEqual(result["query_plan"]["query_object_label"], "公司全部酒店")
        self.assertEqual(result["query_plan"]["query_grain"], "portfolio")
        self.assertEqual(result["resolved_entities"]["hotel_group"]["resolution_basis"], "company_root_all_hotels")

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_recognizes_operating_hotel_count_metric(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(
                semantic_main.Req(question="目前在运营的酒店有多少家？", time_scope="202601")
            )
        self.assertEqual(result["metric_code"], "OPERATING_HOTEL_COUNT")

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_recognizes_monthly_operating_hotel_count_question(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(
                semantic_main.Req(question="3月份总共有多少家酒店在运营", time_scope="202601")
            )
        self.assertEqual(result["metric_code"], "OPERATING_HOTEL_COUNT")
        self.assertEqual(result["time_scope"], "202603")
        self.assertTrue(result["time_scope_explicit"])
        self.assertEqual(result["query_plan"]["analysis_mode"], "scope_stat_snapshot")

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_builds_scope_collection_for_area_portfolio(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(
                semantic_main.Req(question="查一下华南区所有酒店的总体经营情况", time_scope="202601")
            )
        self.assertEqual(result["query_plan"]["query_object_type"], "area_scope")
        self.assertEqual(result["query_plan"]["query_grain"], "portfolio")
        self.assertGreaterEqual(result["query_plan"]["resolved_hotel_count"], 2)
        self.assertEqual(result["resolved_entities"]["scope_collection"]["scope_type"], "area_scope")

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_builds_scope_collection_for_manage_corp_portfolio(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(
                semantic_main.Req(question="查一下万达所有酒店的总体经营情况", time_scope="202601")
            )
        self.assertEqual(result["query_plan"]["query_object_type"], "manage_corp_scope")
        self.assertEqual(result["query_plan"]["query_grain"], "portfolio")
        self.assertGreaterEqual(result["query_plan"]["resolved_hotel_count"], 2)
        self.assertEqual(result["resolved_entities"]["scope_collection"]["scope_type"], "manage_corp_scope")

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_uses_entity_alias_catalog_for_manage_corp_scope(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(
                semantic_main.Req(question="请分析一下万达所有酒店3月份经营情况，按区域维度输出", time_scope="202601")
            )
        self.assertEqual(result["requested_manage_corps"], ["万达品牌"])
        self.assertEqual(result["query_plan"]["query_object_type"], "manage_corp_scope")
        self.assertEqual(result["query_plan"]["analysis_mode"], "group_by_dimension_report")
        self.assertEqual(result["query_plan"]["group_by_dimensions"], ["area"])
        self.assertEqual(result["query_plan"]["metric_bundle_code"], "group_dimension_overview")

    @unittest.skipIf(metric_main is None, f"metric-service deps missing: {metric_error}")
    def test_metric_alias_lookup(self):
        result = metric_main.get_metric("revenue")
        self.assertEqual(result["metric_code"], "TOTAL_INCOME")

    @unittest.skipIf(metric_main is None, f"metric-service deps missing: {metric_error}")
    def test_metric_alias_lookup_for_operating_hotel_count(self):
        result = metric_main.get_metric("在营酒店数")
        self.assertEqual(result["metric_code"], "OPERATING_HOTEL_COUNT")
        result = metric_main.get_metric("总共有多少家酒店在运营")
        self.assertEqual(result["metric_code"], "OPERATING_HOTEL_COUNT")

    @unittest.skipIf(guardrail_main is None, f"guardrail-service deps missing: {guardrail_error}")
    def test_guardrail_injects_scope(self):
        req = guardrail_main.Req(
            sql="SELECT HOTEL_NAME_s AS hotel_name FROM ads_hotel_operation_overview_wide WHERE CALMONTH = '202601' LIMIT 10",
            metric_code="OPERATING_PROFIT",
            allowed_hotels=["示例酒店A"],
            allowed_areas=["华南区"],
            hotel_column="HOTEL_NAME_s",
            area_column="area",
        )
        result = guardrail_main.validate(req)
        self.assertTrue(result["safe"])
        self.assertIn("HOTEL_NAME_s IN ('示例酒店A')", result["rewritten_sql"])
        self.assertIn("area IN ('华南区')", result["rewritten_sql"])

    @unittest.skipIf(explanation_main is None, f"explanation-service deps missing: {explanation_error}")
    def test_explanation_returns_drivers_for_explain(self):
        req = explanation_main.Req(
            question="为什么示例酒店A经营利润低于预算？",
            parsed_intent={"metric_code": "OPERATING_PROFIT", "intent": "explain"},
            rows=[
                {"account_name": "客房收入", "diff_value": -80234.5, "diff_rate": -0.16},
                {"account_name": "人工成本", "diff_value": 25123.6, "diff_rate": 0.18},
            ],
        )
        result = explanation_main.explain(req)
        self.assertIn("summary", result)
        self.assertGreaterEqual(len(result["drivers"]), 1)
        titles = [item["title"] for item in result["report_sections"]]
        self.assertEqual(titles[0], "分析范围")
        self.assertIn("收入质量", titles)
        self.assertIn("利润质量", titles)
        self.assertIn("横向对标", " ".join(titles))
        self.assertIn("80,234.50", result["drivers"][0]["evidence"])

    @unittest.skipIf(explanation_main is None, f"explanation-service deps missing: {explanation_error}")
    def test_report_builder_returns_markdown(self):
        req = explanation_main.ReportReq(
            question="生成示例酒店A摘要",
            parsed_intent={"metric_code": "OPERATING_PROFIT", "intent": "query"},
            rows=[{"hotel_name": "示例酒店A", "actual_value": 1234567.89, "compare_value": 987654.32, "diff_rate": -0.1667}],
        )
        result = explanation_main.build_report(req)
        self.assertIn("report_markdown", result)
        self.assertIn("分析范围", result["report_markdown"])
        self.assertIn("收入质量", result["report_markdown"])
        self.assertIn("客房效率", result["report_markdown"])
        self.assertIn("1,234,567.89", result["report_markdown"])

    @unittest.skipIf(explanation_main is None, f"explanation-service deps missing: {explanation_error}")
    def test_metric_response_uses_objective_operation_breakdown(self):
        req = explanation_main.Req(
            question="广州丽思卡尔顿酒店3月的收入情况怎么样？",
            parsed_intent={"metric_code": "TOTAL_INCOME", "intent": "query", "compare_mode": "budget"},
            rows=[{"hotel_name": "广州丽思卡尔顿酒店", "area": "华南区", "actual_value": 24229360.0, "compare_value": 22228028.0, "diff_value": 2001332.0, "diff_rate": 0.09003642}],
        )
        result = explanation_main.explain(req)
        titles = [item["title"] for item in result["report_sections"]]
        self.assertEqual(titles, ["分析范围", "经营总览", "收入质量", "客房效率", "利润质量", "成本效率", "横向对标"])
        overview_section = next(item for item in result["report_sections"] if item["title"] == "经营总览")
        income_section = next(item for item in result["report_sections"] if item["title"] == "收入质量")
        self.assertIn("当前结果已完成经营拆解", overview_section["content"])
        self.assertIn("总收入", income_section["content"])
        self.assertNotIn("经营状态偏健康", result["summary"])

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_sql_targets_real_overview_table(self):
        sql = ai_query_main.build_sql(
            {
                "source_table": "wddm_dim_overview_cockpit_f",
                "period_fields": {
                    "MTD": {
                        "actual": "OPERATING_PROFIT_MTD_A",
                        "budget": "OPERATING_PROFIT_MTD_B",
                        "last_year": "OPERATING_PROFIT_MTD_L",
                    }
                },
            },
            {"period_type": "MTD", "compare_mode": "budget", "time_scope": "202601"},
            requested_areas=["华南区"],
            requested_hotels=["广州柏悦"],
        )
        self.assertIn("FROM wddm_dim_overview_cockpit_f o LEFT JOIN dim_allhotel_slcp s", sql)
        self.assertIn("o.CALMONTH = '202601'", sql)
        self.assertIn("o.TOTAL_INCOME_MTD_A AS total_income_actual", sql)
        self.assertIn("o.OCCUPANCY_RATE_MTD_A AS occupancy_rate_actual", sql)
        self.assertIn("o.PEOPLE_COST_MTD_A AS people_cost_actual", sql)
        self.assertIn("s.area IN ('华南区')", sql)
        self.assertIn("CONCAT_WS('|'", sql)
        self.assertIn("LIKE", sql)
        self.assertNotIn("LIMIT 50", sql)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_sql_uses_metric_bundle_for_hotel_snapshot_fields(self):
        sql = ai_query_main.build_sql(
            {
                "source_table": "wddm_dim_overview_cockpit_f",
                "period_fields": {
                    "MTD": {
                        "actual": "OPERATING_PROFIT_MTD_A",
                        "budget": "OPERATING_PROFIT_MTD_B",
                        "last_year": "OPERATING_PROFIT_MTD_L",
                    }
                },
            },
            {
                "period_type": "MTD",
                "compare_mode": "yoy",
                "time_scope": "202603",
                "query_plan": {
                    "query_object_type": "single_hotel",
                    "query_grain": "hotel",
                    "metric_bundle_code": "hotel_snapshot",
                    "report_template_code": "executive_hotel_snapshot",
                },
            },
            requested_hotels=["广州丽思卡尔顿酒店"],
        )
        self.assertIn("s.Builder AS builder", sql)
        self.assertIn("s.rooms AS rooms", sql)
        self.assertIn("s.build_area AS build_area", sql)
        self.assertIn("o.ROOM_INCOME_MTD_A AS room_income_actual", sql)
        self.assertIn("o.RESTAURANT_INCOME_MTD_B AS restaurant_income_budget", sql)
        self.assertIn("o.OCCUPANCY_RATE_MTD_L AS occupancy_rate_last_year", sql)
        self.assertIn("o.ROOM_PROFIT_MTD_A AS room_profit_actual", sql)
        self.assertIn("o.RESTAURANT_PROFIT_MTD_A AS restaurant_profit_actual", sql)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_sql_uses_metric_bundle_to_trim_group_dimension_detail_fields(self):
        sql = ai_query_main.build_sql(
            {
                "source_table": "wddm_dim_overview_cockpit_f",
                "period_fields": {
                    "MTD": {
                        "actual": "OWNER_PROFIT_MTD_A",
                        "budget": "OWNER_PROFIT_MTD_B",
                        "last_year": "OWNER_PROFIT_MTD_L",
                    }
                },
            },
            {
                "period_type": "MTD",
                "compare_mode": "yoy",
                "time_scope": "202603",
                "query_plan": {
                    "query_object_type": "hotel_group",
                    "query_grain": "portfolio",
                    "metric_bundle_code": "group_dimension_overview",
                    "report_template_code": "executive_group_dimension",
                },
            },
            requested_areas=["华南区"],
        )
        self.assertNotIn("s.Builder AS builder", sql)
        self.assertNotIn("s.rooms AS rooms", sql)
        self.assertNotIn("s.build_area AS build_area", sql)
        self.assertNotIn("o.ROOM_PROFIT_MTD_A AS room_profit_actual", sql)
        self.assertNotIn("o.RESTAURANT_PROFIT_MTD_A AS restaurant_profit_actual", sql)
        self.assertIn("o.OWNER_PROFIT_MTD_B AS owner_profit_budget", sql)
        self.assertIn("o.INCOME_PER_ROOM_MTD_A AS revpar_actual", sql)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_sql_uses_analysis_contract_block_sequence_to_trim_metric_fields(self):
        sql = ai_query_main.build_sql(
            {
                "source_table": "wddm_dim_overview_cockpit_f",
                "period_fields": {
                    "MTD": {
                        "actual": "OWNER_PROFIT_MTD_A",
                        "budget": "OWNER_PROFIT_MTD_B",
                        "last_year": "OWNER_PROFIT_MTD_L",
                    }
                },
            },
            {
                "metric_code": "OWNER_PROFIT",
                "period_type": "MTD",
                "compare_mode": "yoy",
                "time_scope": "202603",
                "query_plan": {
                    "query_object_type": "single_hotel",
                    "query_grain": "hotel",
                    "metric_bundle_code": "hotel_snapshot",
                    "report_template_code": "executive_hotel_snapshot",
                    "analysis_contract": {
                        "headline_metric": {"code": "OWNER_PROFIT", "name": "NOP业主净利润"},
                        "block_sequence": ["scope_overview", "income_quality", "profit_quality"],
                    },
                },
            },
            requested_hotels=["广州丽思卡尔顿酒店"],
        )
        self.assertIn("o.OWNER_PROFIT_MTD_A AS owner_profit_actual", sql)
        self.assertIn("o.TOTAL_INCOME_MTD_A AS total_income_actual", sql)
        self.assertIn("o.ROOM_INCOME_MTD_A AS room_income_actual", sql)
        self.assertNotIn("o.INCOME_PER_ROOM_MTD_A AS revpar_actual", sql)
        self.assertNotIn("o.PEOPLE_COST_MTD_A AS people_cost_actual", sql)
        self.assertNotIn("o.ENERGY_EXPENSES_MTD_A AS energy_expenses_actual", sql)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_portfolio_sql_uses_bundle_aggregations(self):
        sql = ai_query_main.build_portfolio_sql(
            {
                "source_table": "wddm_dim_overview_cockpit_f",
                "period_fields": {
                    "MTD": {
                        "actual": "OWNER_PROFIT_MTD_A",
                        "budget": "OWNER_PROFIT_MTD_B",
                        "last_year": "OWNER_PROFIT_MTD_L",
                    }
                },
            },
            {
                "period_type": "MTD",
                "compare_mode": "yoy",
                "time_scope": "202603",
                "query_plan": {
                    "query_object_type": "hotel_group",
                    "query_object_label": "公司全部酒店",
                    "query_grain": "portfolio",
                    "metric_bundle_code": "group_dimension_overview",
                    "report_template_code": "executive_group_dimension",
                },
            },
            requested_areas=["华南区"],
        )
        self.assertIn("SUM(o.OWNER_PROFIT_MTD_A) AS owner_profit_actual", sql)
        self.assertIn("SUM(o.TOTAL_INCOME_MTD_B) AS total_income_budget", sql)
        self.assertIn("AVG(o.AVE_HOUSE_PRICE_MTD_A) AS adr_actual", sql)
        self.assertIn("AVG(o.OCCUPANCY_RATE_MTD_L) AS occupancy_rate_last_year", sql)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_sql_filters_under_budget_hotels(self):
        sql = ai_query_main.build_sql(
            {
                "source_table": "wddm_dim_overview_cockpit_f",
                "period_fields": {
                    "MTD": {
                        "actual": "OPERATING_PROFIT_MTD_A",
                        "budget": "OPERATING_PROFIT_MTD_B",
                        "last_year": "OPERATING_PROFIT_MTD_L",
                    }
                },
            },
            {"period_type": "MTD", "compare_mode": "budget", "variance_direction": "below", "time_scope": "202601"},
            requested_areas=["华南区"],
        )
        self.assertIn("o.OPERATING_PROFIT_MTD_A < o.OPERATING_PROFIT_MTD_B", sql)
        self.assertIn("ORDER BY (o.OPERATING_PROFIT_MTD_A - o.OPERATING_PROFIT_MTD_B) ASC", sql)
        self.assertIn("s.area AS area", sql)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_sql_accepts_hotel_full_name_or_short_name(self):
        sql = ai_query_main.build_sql(
            {
                "source_table": "wddm_dim_overview_cockpit_f",
                "period_fields": {
                    "MTD": {
                        "actual": "OPERATING_PROFIT_MTD_A",
                        "budget": "OPERATING_PROFIT_MTD_B",
                        "last_year": "OPERATING_PROFIT_MTD_L",
                    }
                },
            },
            {"period_type": "MTD", "compare_mode": "actual", "time_scope": "202603"},
            requested_hotels=["江门嘉华酒店"],
        )
        self.assertIn("o.CALMONTH = '202603'", sql)
        self.assertIn("CONCAT_WS('|'", sql)
        self.assertIn("LIKE", sql)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_sql_filters_business_dimensions(self):
        sql = ai_query_main.build_sql(
            {
                "source_table": "wddm_dim_overview_cockpit_f",
                "period_fields": {
                    "MTD": {
                        "actual": "OPERATING_PROFIT_MTD_A",
                        "budget": "OPERATING_PROFIT_MTD_B",
                        "last_year": "OPERATING_PROFIT_MTD_L",
                    }
                },
            },
            {
                "period_type": "MTD",
                "compare_mode": "budget",
                "time_scope": "202603",
                "requested_manage_corps": ["万达品牌"],
                "requested_brand_children": ["嘉华"],
                "requested_builders": ["自建"],
                "requested_brand_levels": ["奢华级"],
            },
            requested_areas=["华南区"],
        )
        self.assertIn("CONCAT_WS('|', COALESCE(o.manage_corp", sql)
        self.assertIn("LIKE '%万达品牌%'", sql)
        self.assertIn("LIKE '%万达%'", sql)
        self.assertIn("COALESCE(o.hotel_brand", sql)
        self.assertIn("s.Builder", sql)
        self.assertIn("s.brand_level", sql)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_hotel_count_sql_uses_dim_hotel_info_status(self):
        sql = ai_query_main.build_hotel_count_sql(
            {
                "requested_areas": ["华南区"],
                "requested_brand_children": ["万豪"],
            },
            requested_areas=["华南区"],
        )
        self.assertIn("FROM dim_hotel_info", sql)
        self.assertIn("status = 1", sql)
        self.assertIn("area IN ('华南区')", sql)
        self.assertIn("hotel_brand IN ('万豪')", sql)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_effective_requested_hotels_prefers_scope_collection_members(self):
        result = ai_query_main.effective_requested_hotels(
            {
                "query_plan": {"query_object_type": "brand_scope"},
                "resolved_entities": {
                    "scope_collection": {
                        "member_hotels": ["广州富力丽思卡尔顿酒店", "成都富力丽思卡尔顿酒店"]
                    }
                },
                "requested_hotels": [],
            }
        )
        self.assertEqual(result, ["广州富力丽思卡尔顿酒店", "成都富力丽思卡尔顿酒店"])

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_effective_requested_hotels_adds_hotel_group_token_fallback(self):
        result = ai_query_main.effective_requested_hotels(
            {
                "query_plan": {"query_object_type": "hotel_group"},
                "resolved_entities": {
                    "hotel_group": {
                        "group_token": "富力",
                        "member_hotels": ["广州富力丽思卡尔顿酒店", "香水湾富力万豪度假酒店"],
                    }
                },
                "requested_hotels": [],
            }
        )
        self.assertEqual(result, ["广州富力丽思卡尔顿酒店", "香水湾富力万豪度假酒店", "富力"])

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_effective_requested_hotels_does_not_filter_company_all_hotels_by_fuli_name(self):
        result = ai_query_main.effective_requested_hotels(
            {
                "query_plan": {"query_object_type": "hotel_group"},
                "resolved_entities": {
                    "hotel_group": {
                        "group_token": "富力",
                        "member_hotels": ["广州丽思卡尔顿酒店", "成都万达瑞华酒店"],
                        "resolution_basis": "company_root_all_hotels",
                        "use_group_token_as_filter": False,
                    }
                },
                "requested_hotels": [],
            }
        )
        self.assertEqual(result, [])

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_company_all_hotels_portfolio_can_build_breakdown_without_hotel_filter(self):
        with patch.object(ai_query_main, "request_json", return_value={"rows": [{"hotel_name": "长沙文华", "diff_value": 1}]} ) as mocked:
            rows = ai_query_main.build_portfolio_breakdown(
                {
                    "source_table": "wddm_dim_overview_cockpit_f",
                    "period_fields": {
                        "MTD": {
                            "actual": "OPERATING_PROFIT_MTD_A",
                            "budget": "OPERATING_PROFIT_MTD_B",
                            "last_year": "OPERATING_PROFIT_MTD_L",
                        }
                    },
                },
                {
                    "period_type": "MTD",
                    "compare_mode": "budget",
                    "time_scope": "202601",
                    "query_plan": {"query_object_label": "公司全部酒店", "query_object_type": "hotel_group", "query_grain": "portfolio"},
                    "resolved_entities": {"hotel_group": {"group_token": "富力", "use_group_token_as_filter": False}},
                },
                allowed_hotels=["ALL"],
                requested_hotels=[],
                requested_areas=[],
            )
        self.assertEqual(rows, [{"hotel_name": "长沙文华", "diff_value": 1}])
        sql = mocked.call_args.args[2]["sql"]
        self.assertIn("WHERE o.CALMONTH = '202601'", sql)
        self.assertNotIn("LIKE '%富力%'", sql)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_dimension_breakdown_sql_groups_by_manage_corp_and_area(self):
        sql = ai_query_main.build_dimension_breakdown_sql(
            {
                "source_table": "wddm_dim_overview_cockpit_f",
                "period_fields": {
                    "MTD": {
                        "actual": "OPERATING_PROFIT_MTD_A",
                        "budget": "OPERATING_PROFIT_MTD_B",
                        "last_year": "OPERATING_PROFIT_MTD_L",
                    }
                },
            },
            {
                "period_type": "MTD",
                "compare_mode": "yoy",
                "time_scope": "202603",
                "query_plan": {
                    "query_object_label": "公司全部酒店",
                    "query_object_type": "hotel_group",
                    "query_grain": "portfolio",
                    "group_by_dimensions": ["manage_corp", "area", "manage_corp_area"],
                },
            },
            "manage_corp_area",
            allowed_hotels=["ALL"],
            requested_hotels=[],
            requested_areas=[],
        )
        self.assertIn("COALESCE(NULLIF(TRIM(COALESCE(o.manage_corp, s.brand)), ''), '未标注') AS manage_corp", sql)
        self.assertIn("COALESCE(NULLIF(TRIM(s.area), ''), '未标注') AS area", sql)
        self.assertIn("GROUP BY 1, 2", sql)
        self.assertIn("SUM(o.OPERATING_PROFIT_MTD_A) AS actual_value", sql)
        self.assertIn("SUM(o.OPERATING_PROFIT_MTD_L) AS compare_value", sql)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_explain_sql_filters_pnl_hierarchy(self):
        sql = ai_query_main.build_explain_sql(
            {
                "time_scope": "202603",
                "compare_mode": "budget",
                "requested_departments": ["餐饮部"],
                "requested_accounts": ["酒水成本"],
                "requested_brand_children": ["嘉华"],
            },
            requested_hotels=["江门嘉华"],
        )
        self.assertIn("Dept", sql)
        self.assertIn("餐饮部", sql)
        self.assertIn("account_nameF01", sql)
        self.assertIn("酒水成本", sql)
        self.assertIn("brand_child", sql)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_internal_benchmark_sql_contains_peer_metrics(self):
        sql = ai_query_main.build_internal_benchmark_sql(
            {"source_table": "wddm_dim_overview_cockpit_f"},
            {"time_scope": "202603"},
            {
                "hotel_name": "江门嘉华",
                "area": "华南区",
                "brand_child": "嘉华",
                "brand_level": "奢华级",
                "city_level": "一线城市",
            },
            [("area", "area_filter"), ("brand_child", "brand_child_filter"), ("brand_level", "brand_level_filter"), ("city_level", "city_level_filter")],
        )
        self.assertIsNotNone(sql)
        assert sql is not None
        self.assertIn("COUNT(*) AS peer_count", sql)
        self.assertIn("AVG(o.TOTAL_INCOME_MTD_A)", sql)
        self.assertIn("AVG(o.INCOME_PER_ROOM_MTD_A)", sql)
        self.assertIn("AVG(o.OPERATING_PROFIT_MTD_A / NULLIF(o.TOTAL_INCOME_MTD_A, 0))", sql)
        self.assertIn("NOT (", sql)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_portfolio_sql_aggregates_group_scope(self):
        sql = ai_query_main.build_portfolio_sql(
            {
                "source_table": "wddm_dim_overview_cockpit_f",
                "period_fields": {
                    "MTD": {
                        "actual": "OPERATING_PROFIT_MTD_A",
                        "budget": "OPERATING_PROFIT_MTD_B",
                        "last_year": "OPERATING_PROFIT_MTD_L",
                    }
                },
            },
            {
                "period_type": "MTD",
                "compare_mode": "budget",
                "time_scope": "202601",
                "query_plan": {"query_object_label": "富力体系酒店集合", "query_object_type": "hotel_group", "query_grain": "portfolio"},
                "resolved_entities": {"hotel_group": {"group_token": "富力"}},
            },
            requested_hotels=["广州富力丽思卡尔顿酒店及公寓", "香水湾富力万豪度假酒店", "富力"],
        )
        self.assertIn("'富力体系酒店集合' AS hotel_name", sql)
        self.assertIn("COUNT(DISTINCT TRIM(COALESCE(s.hotel_name_s, o.hotel_name))) AS portfolio_member_count", sql)
        self.assertIn("SUM(o.TOTAL_INCOME_MTD_A) AS total_income_actual", sql)
        self.assertIn("SUM(o.OPERATING_PROFIT_MTD_A) AS actual_value", sql)
        self.assertIn("LIKE '%富力%'", sql)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_portfolio_sql_uses_metric_bundle_for_group_summary_fields(self):
        sql = ai_query_main.build_portfolio_sql(
            {
                "source_table": "wddm_dim_overview_cockpit_f",
                "period_fields": {
                    "MTD": {
                        "actual": "OWNER_PROFIT_MTD_A",
                        "budget": "OWNER_PROFIT_MTD_B",
                        "last_year": "OWNER_PROFIT_MTD_L",
                    }
                },
            },
            {
                "period_type": "MTD",
                "compare_mode": "yoy",
                "time_scope": "202603",
                "query_plan": {
                    "query_object_label": "公司全部酒店",
                    "query_object_type": "hotel_group",
                    "query_grain": "portfolio",
                    "metric_bundle_code": "group_dimension_overview",
                    "report_template_code": "executive_group_dimension",
                },
            },
            requested_hotels=["富力"],
        )
        self.assertIn("SUM(o.TOTAL_INCOME_MTD_A) AS total_income_actual", sql)
        self.assertIn("SUM(o.OWNER_PROFIT_MTD_A) AS owner_profit_actual", sql)
        self.assertNotIn("SUM(o.ROOM_PROFIT_MTD_A) AS room_profit_actual", sql)
        self.assertNotIn("SUM(o.RESTAURANT_PROFIT_MTD_A) AS restaurant_profit_actual", sql)
        self.assertNotIn("SUM(o.OTHER_DEPT_INCOME_MTD_A) AS other_dept_income_actual", sql)

    @unittest.skipIf(explanation_main is None, f"explanation-service deps missing: {explanation_error}")
    def test_metric_response_uses_portfolio_breakdown_for_group_overview(self):
        req = explanation_main.Req(
            question="???2024?2??????????????",
            parsed_intent={
                "metric_code": "OPERATING_PROFIT",
                "intent": "query",
                "compare_mode": "budget",
                "query_plan": {
                    "query_object_type": "hotel_group",
                    "query_object_label": "????????",
                    "query_grain": "portfolio",
                    "analysis_mode": "portfolio_overview",
                },
            },
            rows=[{
                "hotel_name": "????????",
                "portfolio_member_count": 7,
                "actual_value": -147636.58,
                "compare_value": 0.0,
                "diff_value": -147636.58,
                "diff_rate": None,
                "total_income_actual": 1200000.0,
                "room_income_actual": 800000.0,
                "restaurant_income_actual": 250000.0,
                "banquet_income_actual": 50000.0,
                "owner_profit_actual": -177636.58,
                "operating_profit_actual": -147636.58,
                "people_cost_actual": 300000.0,
                "energy_expenses_actual": 80000.0,
                "restaurant_cost_actual": 120000.0,
                "room_cost_actual": 60000.0,
                "admin_expenses_actual": 50000.0,
            }],
            portfolio_breakdown=[
                {"hotel_name": "??????????????", "actual_value": 500000, "compare_value": 400000, "diff_value": 100000, "diff_rate": 0.25, "owner_profit_actual": 210000, "operating_profit_actual": 260000},
                {"hotel_name": "?????????", "actual_value": -200000, "compare_value": 0, "diff_value": -200000, "diff_rate": None, "owner_profit_actual": -360000, "operating_profit_actual": -300000},
            ],
            portfolio_outliers={
                "income": {
                    "best": {"hotel_name": "??????????????", "diff_value": 100000},
                    "worst": {"hotel_name": "?????????", "diff_value": -200000},
                },
                "profit": {
                    "best": {"hotel_name": "??????????????", "owner_profit_actual": 210000, "operating_profit_actual": 260000},
                    "worst": {"hotel_name": "?????????", "owner_profit_actual": -360000, "operating_profit_actual": -300000},
                },
                "cost": {
                    "worst": {"hotel_name": "?????????", "people_cost_actual": 180000},
                },
            },
        )
        result = explanation_main.explain(req)
        self.assertIn("本次组合样本 7 家", result["summary"])
        self.assertIn("拉动较强的是", result["summary"])
        self.assertIn("人工成本偏高的是", result["summary"])
        self.assertGreaterEqual(len(result["weakest_hotels"]), 2)
        self.assertGreaterEqual(len(result["management_summary"]), 2)
        self.assertIn("组合观察", result["management_summary"][0])
        section_titles = [item["title"] for item in result["report_sections"]]
        self.assertIn("经营总览", section_titles)
        self.assertIn("收入质量", section_titles)
        self.assertIn("横向对标", " ".join(section_titles))
        self.assertEqual(len(result["suggestions"]), 3)

    @unittest.skipIf(explanation_main is None, f"explanation-service deps missing: {explanation_error}")
    def test_report_sections_follow_template_order_for_group_dimension_report(self):
        req = explanation_main.Req(
            question="请分析一下公司所有酒店1月份的经营情况，请汇总到管理公司和区域维度输出",
            parsed_intent={
                "metric_code": "OWNER_PROFIT",
                "intent": "query",
                "compare_mode": "yoy",
                "time_scope": "202603",
                "analysis_focus": "dimension_comparison",
                "query_plan": {
                    "query_object_type": "hotel_group",
                    "query_object_label": "公司全部酒店",
                    "query_grain": "portfolio",
                    "analysis_mode": "group_by_dimension_report",
                    "report_template_code": "executive_group_dimension",
                },
            },
            rows=[{
                "hotel_name": "公司全部酒店",
                "portfolio_member_count": 83,
                "actual_value": 57076326.51,
                "compare_value": 73118911.34,
                "diff_value": -16042584.83,
                "diff_rate": -0.2194,
                "total_income_actual": 349364837.12,
                "owner_profit_actual": 57076326.51,
                "operating_profit_actual": 81120537.96,
            }],
            dimension_breakdowns={
                "manage_corp": [{"manage_corp": "国际品牌", "hotel_count": 32, "total_income_actual": 185573325.12, "owner_profit_actual": 34576303.42, "operating_profit_actual": 50403677.71, "revpar_actual": 406.2}],
                "area": [{"area": "华南区", "hotel_count": 16, "total_income_actual": 98899370.88, "owner_profit_actual": 21158918.18, "operating_profit_actual": 29527649.86, "revpar_actual": 464.83}],
            },
        )
        result = explanation_main.explain(req)
        section_titles = [item["title"] for item in result["report_sections"]]
        self.assertLess(section_titles.index("分维度经营摘要"), section_titles.index("管理公司/区域汇总"))
        self.assertLess(section_titles.index("管理公司/区域汇总"), section_titles.index("收入质量"))
        self.assertNotIn("重点酒店与梯队", section_titles)
        self.assertIn("结论", section_titles)
        self.assertIn("管理公司、区域、品牌的相对位置", result["management_summary"][0])

    @unittest.skipIf(explanation_main is None, f"explanation-service deps missing: {explanation_error}")
    def test_portfolio_management_report_puts_structure_before_watchlist(self):
        req = explanation_main.Req(
            question="汇总一下本月所有酒店的经营情况",
            parsed_intent={
                "metric_code": "OWNER_PROFIT",
                "intent": "query",
                "compare_mode": "yoy",
                "time_scope": "202603",
                "analysis_focus": "management_report",
                "query_plan": {
                    "query_object_type": "hotel_group",
                    "query_object_label": "公司全部酒店",
                    "query_grain": "portfolio",
                    "analysis_mode": "management_report",
                    "report_template_code": "executive_portfolio",
                },
            },
            rows=[{
                "hotel_name": "公司全部酒店",
                "portfolio_member_count": 83,
                "actual_value": 57076326.51,
                "compare_value": 73118911.34,
                "diff_value": -16042584.83,
                "diff_rate": -0.2194,
                "total_income_actual": 349364837.12,
                "owner_profit_actual": 57076326.51,
                "operating_profit_actual": 81120537.96,
            }],
            portfolio_breakdown=[
                {"hotel_name": "重庆万州希尔顿逸林", "total_income_actual": 1727765.38, "owner_profit_actual": 94469.52, "operating_profit_actual": 198362.69, "revpar_actual": 141.11, "diff_value": 101902.88},
                {"hotel_name": "太原文华", "total_income_actual": 2254909.25, "owner_profit_actual": -397444.53, "operating_profit_actual": -338219.09, "revpar_actual": 90.07, "diff_value": -398952.29},
            ],
            dimension_breakdowns={
                "manage_corp": [{"manage_corp": "国际品牌", "hotel_count": 32, "total_income_actual": 185573325.12, "owner_profit_actual": 34576303.42, "operating_profit_actual": 50403677.71, "revpar_actual": 406.2}],
                "area": [{"area": "华南区", "hotel_count": 16, "total_income_actual": 98899370.88, "owner_profit_actual": 21158918.18, "operating_profit_actual": 29527649.86, "revpar_actual": 464.83}],
            },
        )
        result = explanation_main.explain(req)
        section_titles = [item["title"] for item in result["report_sections"]]
        self.assertLess(section_titles.index("组合经营摘要"), section_titles.index("经营总览"))
        self.assertLess(section_titles.index("经营总览"), section_titles.index("管理公司/区域汇总"))
        self.assertLess(section_titles.index("管理公司/区域汇总"), section_titles.index("重点酒店与梯队"))
        self.assertLess(section_titles.index("横向对标与继续追问"), section_titles.index("结论"))
        summary_text = next(item["content"] for item in result["report_sections"] if item["title"] == "组合经营摘要")
        self.assertNotIn("重庆万州希尔顿逸林", summary_text)
        self.assertIn("先看板块差异", summary_text)
        conclusion_text = next(item["content"] for item in result["report_sections"] if item["title"] == "结论")
        self.assertIn("管理结论：", conclusion_text)

    @unittest.skipIf(explanation_main is None, f"explanation-service deps missing: {explanation_error}")
    def test_hotel_snapshot_template_filters_portfolio_only_sections(self):
        req = explanation_main.Req(
            question="北京富力万丽酒店1月的经营情况怎么样？",
            parsed_intent={
                "metric_code": "OWNER_PROFIT",
                "intent": "query",
                "compare_mode": "yoy",
                "time_scope": "202601",
                "query_plan": {
                    "query_object_type": "single_hotel",
                    "query_object_label": "北京富力万丽酒店",
                    "query_grain": "hotel",
                    "analysis_mode": "hotel_metric_snapshot",
                    "report_template_code": "executive_hotel_snapshot",
                },
            },
            rows=[{
                "hotel_name": "北京万丽",
                "actual_value": 3095227.5,
                "compare_value": 2132912.0,
                "diff_value": 962315.5,
                "diff_rate": 0.4512,
                "total_income_actual": 12642100.0,
                "room_income_actual": 9225748.0,
                "restaurant_income_actual": 1534594.125,
                "banquet_income_actual": 1543950.0,
                "owner_profit_actual": 3095227.5,
                "operating_profit_actual": 4204313.0,
                "occupancy_rate_actual": 0.636,
                "adr_actual": 896.4,
                "revpar_actual": 570.12,
                "people_cost_actual": 3948258.66,
                "energy_expenses_actual": 931929.75,
                "restaurant_cost_actual": 3023520.75,
                "room_cost_actual": 2294809.75,
                "admin_expenses_actual": 2151581.25,
                "area": "华北区",
                "brand": "国际品牌",
                "brand_child": "万豪",
                "brand_level": "标准五星级",
                "city_level": "一线城市",
            }],
        )
        result = explanation_main.explain(req)
        section_titles = [item["title"] for item in result["report_sections"]]
        self.assertIn("经营结果", section_titles)
        self.assertIn("问题归因", section_titles)
        self.assertNotIn("分维度经营摘要", section_titles)
        self.assertNotIn("重点酒店与梯队", section_titles)
        self.assertIn("横向对标", section_titles)
        self.assertIn("结论", section_titles)

    @unittest.skipIf(explanation_main is None, f"explanation-service deps missing: {explanation_error}")
    def test_income_structure_focus_prioritizes_income_sections_and_prompts(self):
        req = explanation_main.Req(
            question="广州丽思卡尔顿酒店3月的收入结构怎么样？",
            parsed_intent={
                "metric_code": "TOTAL_INCOME",
                "intent": "query",
                "compare_mode": "yoy",
                "time_scope": "202603",
                "analysis_focus": "income_structure",
                "query_plan": {
                    "query_object_type": "single_hotel",
                    "query_object_label": "广州丽思卡尔顿酒店",
                    "query_grain": "hotel",
                    "analysis_mode": "hotel_metric_snapshot",
                    "report_template_code": "executive_hotel_snapshot",
                },
            },
            rows=[{
                "hotel_name": "广州丽思卡尔顿酒店",
                "actual_value": 24229360.0,
                "compare_value": 22228028.0,
                "diff_value": 2001332.0,
                "diff_rate": 0.09003642,
                "total_income_actual": 24229360.0,
                "room_income_actual": 17000000.0,
                "restaurant_income_actual": 3800000.0,
                "banquet_income_actual": 2000000.0,
                "owner_profit_actual": 5100000.0,
                "operating_profit_actual": 6800000.0,
                "occupancy_rate_actual": 0.71,
                "adr_actual": 960.0,
                "revpar_actual": 680.0,
                "people_cost_actual": 3000000.0,
                "energy_expenses_actual": 500000.0,
                "restaurant_cost_actual": 1200000.0,
            }],
        )
        result = explanation_main.explain(req)
        section_titles = [item["title"] for item in result["report_sections"]]
        self.assertEqual(section_titles[2], "收入质量")
        self.assertLess(section_titles.index("收入质量"), section_titles.index("问题归因"))
        self.assertIn("收入结构", result["management_summary"][0])
        self.assertIn("客房收入", "；".join(result["suggestions"]))

    @unittest.skipIf(explanation_main is None, f"explanation-service deps missing: {explanation_error}")
    def test_profit_cost_efficiency_focus_prioritizes_profit_and_cost_sections(self):
        req = explanation_main.Req(
            question="广州丽思卡尔顿酒店3月的利润和成本效率怎么样？",
            parsed_intent={
                "metric_code": "OWNER_PROFIT",
                "intent": "query",
                "compare_mode": "yoy",
                "time_scope": "202603",
                "analysis_focus": "profit_cost_efficiency",
                "query_plan": {
                    "query_object_type": "single_hotel",
                    "query_object_label": "广州丽思卡尔顿酒店",
                    "query_grain": "hotel",
                    "analysis_mode": "hotel_metric_snapshot",
                    "report_template_code": "executive_hotel_snapshot",
                },
            },
            rows=[{
                "hotel_name": "广州丽思卡尔顿酒店",
                "actual_value": 5100000.0,
                "compare_value": 4800000.0,
                "diff_value": 300000.0,
                "diff_rate": 0.0625,
                "total_income_actual": 24229360.0,
                "room_income_actual": 17000000.0,
                "restaurant_income_actual": 3800000.0,
                "banquet_income_actual": 2000000.0,
                "owner_profit_actual": 5100000.0,
                "operating_profit_actual": 6800000.0,
                "occupancy_rate_actual": 0.71,
                "adr_actual": 960.0,
                "revpar_actual": 680.0,
                "people_cost_actual": 3000000.0,
                "energy_expenses_actual": 500000.0,
                "restaurant_cost_actual": 1200000.0,
            }],
        )
        result = explanation_main.explain(req)
        section_titles = [item["title"] for item in result["report_sections"]]
        self.assertEqual(section_titles[2], "利润质量")
        self.assertLess(section_titles.index("利润质量"), section_titles.index("问题归因"))
        self.assertLess(section_titles.index("成本效率"), section_titles.index("问题归因"))
        self.assertIn("利润与成本", result["management_summary"][0])
        self.assertIn("人工成本", "；".join(result["suggestions"]))

    @unittest.skipIf(explanation_main is None, f"explanation-service deps missing: {explanation_error}")
    def test_hotel_snapshot_conclusion_uses_fixed_three_sentence_structure(self):
        req = explanation_main.Req(
            question="广州丽思卡尔顿酒店3月的经营情况怎么样？",
            parsed_intent={
                "metric_code": "OWNER_PROFIT",
                "intent": "query",
                "compare_mode": "budget",
                "time_scope": "202603",
                "analysis_focus": "management_report",
                "query_plan": {
                    "query_object_type": "single_hotel",
                    "query_object_label": "广州丽思卡尔顿酒店",
                    "query_grain": "hotel",
                    "analysis_mode": "hotel_metric_snapshot",
                    "report_template_code": "executive_hotel_snapshot",
                },
            },
            rows=[{
                "hotel_name": "广州丽思卡尔顿酒店",
                "actual_value": 5100000.0,
                "compare_value": 5400000.0,
                "diff_value": -300000.0,
                "diff_rate": -0.0556,
                "total_income_actual": 24229360.0,
                "total_income_budget": 25229360.0,
                "total_income_last_year": 23229360.0,
                "room_income_actual": 17000000.0,
                "room_income_budget": 18000000.0,
                "restaurant_income_actual": 3800000.0,
                "restaurant_income_budget": 4200000.0,
                "banquet_income_actual": 2000000.0,
                "banquet_income_budget": 2500000.0,
                "owner_profit_actual": 5100000.0,
                "owner_profit_budget": 5600000.0,
                "owner_profit_last_year": 4900000.0,
                "operating_profit_actual": 6800000.0,
                "operating_profit_budget": 7300000.0,
                "operating_profit_last_year": 6500000.0,
                "room_profit_actual": 9200000.0,
                "room_profit_budget": 9800000.0,
                "restaurant_profit_actual": 800000.0,
                "restaurant_profit_budget": 1200000.0,
                "occupancy_rate_actual": 0.68,
                "occupancy_rate_budget": 0.72,
                "adr_actual": 930.0,
                "adr_budget": 980.0,
                "revpar_actual": 632.4,
                "revpar_budget": 705.6,
                "revpar_last_year": 620.0,
                "people_cost_actual": 8200000.0,
                "energy_expenses_actual": 2300000.0,
                "admin_expenses_actual": 5100000.0,
            }],
        )
        result = explanation_main.explain(req)
        conclusion = next(item["content"] for item in result["report_sections"] if item["title"] == "结论")
        self.assertIn("一句话经营判断：", conclusion)
        self.assertIn("两个核心问题：", conclusion)
        self.assertIn("三个改进动作：", conclusion)

    @unittest.skipIf(explanation_main is None, f"explanation-service deps missing: {explanation_error}")
    def test_hotel_snapshot_llm_enhancement_only_replaces_conclusion_section(self):
        req = explanation_main.Req(
            question="广州丽思卡尔顿酒店3月的经营情况怎么样？",
            parsed_intent={
                "metric_code": "OWNER_PROFIT",
                "intent": "query",
                "compare_mode": "budget",
                "time_scope": "202603",
                "analysis_focus": "management_report",
                "query_plan": {
                    "query_object_type": "single_hotel",
                    "query_object_label": "广州丽思卡尔顿酒店",
                    "query_grain": "hotel",
                    "analysis_mode": "hotel_metric_snapshot",
                    "report_template_code": "executive_hotel_snapshot",
                },
            },
            rows=[{
                "hotel_name": "广州丽思卡尔顿酒店",
                "actual_value": 5100000.0,
                "compare_value": 5400000.0,
                "diff_value": -300000.0,
                "diff_rate": -0.0556,
                "total_income_actual": 24229360.0,
                "total_income_budget": 25229360.0,
                "total_income_last_year": 23229360.0,
                "room_income_actual": 17000000.0,
                "owner_profit_actual": 5100000.0,
                "owner_profit_budget": 5600000.0,
                "owner_profit_last_year": 4900000.0,
                "revpar_actual": 632.4,
                "revpar_budget": 705.6,
                "revpar_last_year": 620.0,
                "occupancy_rate_actual": 0.68,
                "adr_actual": 930.0,
                "restaurant_income_actual": 3800000.0,
                "banquet_income_actual": 2000000.0,
                "restaurant_profit_actual": 800000.0,
                "people_cost_actual": 8200000.0,
                "energy_expenses_actual": 2300000.0,
                "admin_expenses_actual": 5100000.0,
            }],
        )
        with patch.object(explanation_main, "should_use_llm_enhancement", return_value=True), patch.object(
            explanation_main,
            "_call_llm_summary",
            return_value={
                "summary": "模型已基于当前单店事实完成经营判断。",
                "risks": [
                    "收入质量保持客观拆解。",
                    "客房效率保持客观拆解。",
                    "利润质量保持客观拆解。",
                    "成本效率保持客观拆解。",
                    "横向对标保持客观拆解。",
                ],
                "suggestions": ["继续看房务价格带。"],
                "conclusion": "一句话经营判断：模型认为本月经营承压。 两个核心问题：1. 客房效率偏弱；2. 费用率偏高。 三个改进动作：1. 调整价格策略；2. 强化宴会引流；3. 压降行政费用。",
            },
        ):
            result = explanation_main.explain(req)
        section_titles = [item["title"] for item in result["report_sections"]]
        self.assertEqual(section_titles[:5], ["分析范围", "经营结果", "问题归因", "横向对标", "结论"])
        conclusion = next(item["content"] for item in result["report_sections"] if item["title"] == "结论")
        self.assertIn("模型认为本月经营承压", conclusion)
        self.assertEqual(result["llm_enhancement"]["used"], True)

    @unittest.skipIf(explanation_main is None, f"explanation-service deps missing: {explanation_error}")
    def test_portfolio_llm_enhancement_only_replaces_conclusion_section(self):
        req = explanation_main.Req(
            question="汇总一下本月所有酒店的经营情况",
            parsed_intent={
                "metric_code": "OWNER_PROFIT",
                "intent": "query",
                "compare_mode": "yoy",
                "time_scope": "202603",
                "analysis_focus": "management_report",
                "query_plan": {
                    "query_object_type": "hotel_group",
                    "query_object_label": "公司全部酒店",
                    "query_grain": "portfolio",
                    "analysis_mode": "management_report",
                    "report_template_code": "executive_portfolio",
                },
            },
            rows=[{
                "hotel_name": "公司全部酒店",
                "portfolio_member_count": 83,
                "actual_value": 57076326.51,
                "compare_value": 73118911.34,
                "diff_value": -16042584.83,
                "diff_rate": -0.2194,
                "total_income_actual": 349364837.12,
                "total_income_last_year": 390700472.12,
                "owner_profit_actual": 57076326.51,
                "owner_profit_last_year": 73118911.34,
                "operating_profit_actual": 81120537.96,
                "revpar_actual": 280.25,
                "revpar_last_year": 306.22,
            }],
            dimension_breakdowns={
                "manage_corp": [{"manage_corp": "国际品牌", "hotel_count": 32, "total_income_actual": 185573325.12, "owner_profit_actual": 34576303.42, "operating_profit_actual": 50403677.71, "revpar_actual": 406.2}],
                "area": [{"area": "华南区", "hotel_count": 16, "total_income_actual": 98899370.88, "owner_profit_actual": 21158918.18, "operating_profit_actual": 29527649.86, "revpar_actual": 464.83}],
            },
        )
        with patch.object(explanation_main, "should_use_llm_enhancement", return_value=True), patch.object(
            explanation_main,
            "_call_llm_summary",
            return_value={
                "summary": "模型已基于组合事实完成管理结论。",
                "risks": [
                    "收入质量保持客观拆解。",
                    "客房效率保持客观拆解。",
                    "利润质量保持客观拆解。",
                    "成本效率保持客观拆解。",
                    "横向对标保持客观拆解。",
                ],
                "suggestions": ["继续看华南区和国际品牌的差异。"],
                "conclusion": "管理结论：模型认为集团整体承压。 两个核心问题：1. 区域分化明显；2. 利润转化不足。 三个优先动作：1. 先盯管理公司差异；2. 再抓重点区域；3. 最后下钻异常酒店。",
            },
        ):
            result = explanation_main.explain(req)
        section_titles = [item["title"] for item in result["report_sections"]]
        self.assertEqual(section_titles[:4], ["分析范围", "组合经营摘要", "经营总览", "管理公司/区域汇总"])
        self.assertIn("结论", section_titles)
        conclusion = next(item["content"] for item in result["report_sections"] if item["title"] == "结论")
        self.assertIn("模型认为集团整体承压", conclusion)
        self.assertEqual(result["llm_enhancement"]["used"], True)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_external_benchmark_stub_returns_provider_metadata(self):
        result = ai_query_main.build_external_benchmark_stub(
            {
                "requested_areas": ["华南区"],
                "requested_brand_children": ["嘉华"],
                "requested_brand_levels": ["奢华级"],
            },
            {"peer_count": 6, "scope_used": "同区域同品牌"},
            True,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["status"], "awaiting_provider")
        self.assertEqual(result["provider"], ai_query_main.EXTERNAL_BENCHMARK_PROVIDER)
        self.assertIn("区域：华南区", result["dimensions"])
        self.assertIn("内部已找到", " ".join(result["disclaimers"]))

    @unittest.skipIf(explanation_main is None, f"explanation-service deps missing: {explanation_error}")
    def test_metric_response_uses_internal_benchmark_when_available(self):
        req = explanation_main.Req(
            question="江门嘉华3月经营情况怎么样",
            parsed_intent={"metric_code": "OPERATING_PROFIT", "intent": "query", "compare_mode": "budget"},
            rows=[{
                "hotel_name": "江门嘉华",
                "area": "华南区",
                "brand": "国际品牌",
                "brand_child": "嘉华",
                "brand_level": "奢华级",
                "city_level": "一线城市",
                "actual_value": 120.0,
                "compare_value": 100.0,
                "diff_value": 20.0,
                "diff_rate": 0.2,
                "total_income_actual": 1200000.0,
                "revpar_actual": 888.0,
                "operating_profit_actual": 260000.0,
                "people_cost_actual": 100000.0,
                "energy_expenses_actual": 30000.0,
                "restaurant_cost_actual": 60000.0,
                "room_cost_actual": 50000.0,
                "admin_expenses_actual": 40000.0,
            }],
            peer_benchmark={
                "peer_count": 5,
                "scope_used": "同区域同品牌同档次",
                "scope": {"area": "华南区", "brand_child": "嘉华", "brand_level": "奢华级", "city_level": "一线城市"},
                "current": {"hotel_name": "江门嘉华", "total_income": 1200000.0, "revpar": 888.0, "operating_profit": 260000.0, "profit_margin": 0.2167, "cost_rate": 0.2333},
                "peer_avg": {"total_income": 980000.0, "revpar": 760.0, "operating_profit": 180000.0, "profit_margin": 0.183, "cost_rate": 0.271},
            },
            external_benchmark_requested=True,
        )
        result = explanation_main.explain(req)
        self.assertIn("内部对标采用 同区域同品牌同档次", result["report_sections"][-1]["content"])
        self.assertIn("外部行业对标", result["report_sections"][-1]["content"])
        self.assertGreaterEqual(len(result["management_summary"]), 2)
        self.assertIn("本次按 江门嘉华", result["management_summary"][0])
        self.assertEqual(len(result["suggestions"]), 3)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_system_settings_exposes_tuning_config(self):
        result = ai_query_main.system_settings()
        self.assertIn("quick_questions", result)
        self.assertIn("model_config", result)
        self.assertIn("answer_templates", result)
        self.assertIn("tuning_stages", result)
        self.assertGreaterEqual(len(result["quick_questions"]), 1)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_learning_inbox_records_actionable_samples(self):
        self.assertEqual(ai_query_main.learning_reason({"needs_clarification": True}, [], []), "clarification_required")
        self.assertEqual(ai_query_main.learning_reason({"confidence": 0.5}, [{"hotel_name": "A"}], []), "low_confidence_parse")
        self.assertEqual(ai_query_main.learning_reason({"confidence": 0.9}, [], []), "empty_result")

        with workspace_temp_dir() as temp_dir:
            original_dir = ai_query_main.LEARNING_INBOX_DIR
            ai_query_main.LEARNING_INBOX_DIR = Path(temp_dir)
            try:
                path = ai_query_main.write_learning_sample(
                    trace_id="trace_test",
                    question="测试问题",
                    stage="semantic",
                    reason="low_confidence_parse",
                    parsed={"confidence": 0.5},
                    row_count=0,
                    warnings=["test_warning"],
                )
                record = json.loads(path.read_text(encoding="utf-8").strip())
                self.assertEqual(record["trace_id"], "trace_test")
                self.assertEqual(record["reason"], "low_confidence_parse")
                self.assertEqual(record["parsed_intent"]["confidence"], 0.5)
            finally:
                ai_query_main.LEARNING_INBOX_DIR = original_dir

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_learning_sample_schema_v2_includes_trace_guardrail_and_proposals(self):
        with workspace_temp_dir() as temp_dir:
            original_dir = ai_query_main.LEARNING_INBOX_DIR
            ai_query_main.LEARNING_INBOX_DIR = Path(temp_dir)
            try:
                path = ai_query_main.write_learning_sample(
                    trace_id="trace_learning_v2",
                    question="看一下江门嘉华酒店3月的经营情况",
                    stage="query",
                    reason="empty_result",
                    parsed={
                        "metric_code": "OWNER_PROFIT",
                        "compare_mode": "yoy",
                        "time_scope": "202603",
                        "requested_hotels": ["江门嘉华酒店"],
                        "query_plan": {
                            "query_object_type": "single_hotel",
                            "query_grain": "hotel",
                            "analysis_contract": {
                                "headline_metric": {"code": "OWNER_PROFIT", "name": "NOP业主净利润"},
                                "block_sequence": ["income_quality", "profit_quality"],
                            },
                        },
                    },
                    row_count=0,
                    analysis_blocks=[{"code": "profit_quality", "data_status": "missing"}],
                    guardrail={"status": "warning", "warnings": [{"code": "missing_data_overstated"}]},
                    trace_events=[{"stage": "parse_intent", "status": "completed", "duration_ms": 8}],
                )
                record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
                self.assertEqual(record["schema_version"], 2)
                self.assertEqual(record["review_status"], "pending_review")
                self.assertEqual(record["analysis_contract"]["headline_metric"]["code"], "OWNER_PROFIT")
                self.assertEqual(record["analysis_blocks"][0]["code"], "profit_quality")
                self.assertEqual(record["guardrail"]["status"], "warning")
                self.assertEqual(record["trace_events"][0]["stage"], "parse_intent")
                self.assertEqual(record["alias_proposal"]["status"], "proposed")
                self.assertEqual(record["eval_case_proposal"]["expected"]["metric_code"], "OWNER_PROFIT")
                self.assertIn("OWNER_PROFIT_MTD_A", record["eval_case_proposal"]["sql_assertions"]["contains"])
            finally:
                ai_query_main.LEARNING_INBOX_DIR = original_dir

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_system_learning_summary_aggregates_recent_samples(self):
        with workspace_temp_dir() as temp_dir:
            original_dir = ai_query_main.LEARNING_INBOX_DIR
            ai_query_main.LEARNING_INBOX_DIR = Path(temp_dir)
            try:
                ai_query_main.write_learning_sample(
                    trace_id="trace_1",
                    question="为什么没有结果",
                    stage="query",
                    reason="empty_result",
                    parsed={"metric_code": "TOTAL_INCOME", "query_plan": {"query_object_type": "single_hotel"}},
                    row_count=0,
                    extra={"metric_code": "TOTAL_INCOME", "query_object_type": "single_hotel"},
                )
                ai_query_main.write_learning_sample(
                    trace_id="trace_2",
                    question="查一下万达所有酒店",
                    stage="semantic",
                    reason="clarification_required",
                    parsed={"metric_code": "OPERATING_PROFIT", "query_plan": {"query_object_type": "manage_corp_scope"}},
                    row_count=0,
                    extra={"metric_code": "OPERATING_PROFIT", "query_object_type": "manage_corp_scope"},
                )
                result = ai_query_main.system_learning_summary(days=7)
                summary = result["summary"]
                self.assertEqual(summary["sample_count"], 2)
                self.assertEqual(summary["reason_breakdown"][0]["count"], 1)
                self.assertEqual(len(summary["latest_samples"]), 2)
                self.assertIn(summary["metric_breakdown"][0]["metric_code"], {"TOTAL_INCOME", "OPERATING_PROFIT"})
            finally:
                ai_query_main.LEARNING_INBOX_DIR = original_dir

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_external_benchmark_uploaded_dataset_reports_missing_dataset(self):
        with workspace_temp_dir() as temp_dir:
            original_dir = ai_query_main.EXTERNAL_BENCHMARK_DATASET_DIR
            original_provider = ai_query_main.EXTERNAL_BENCHMARK_PROVIDER
            ai_query_main.EXTERNAL_BENCHMARK_DATASET_DIR = Path(temp_dir)
            ai_query_main.EXTERNAL_BENCHMARK_PROVIDER = "uploaded_dataset"
            try:
                result = ai_query_main.build_external_benchmark_stub({"requested_areas": ["华南区"]}, None, True)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(result["status"], "dataset_missing")
                self.assertEqual(result["provider"], "uploaded_dataset")
            finally:
                ai_query_main.EXTERNAL_BENCHMARK_DATASET_DIR = original_dir
                ai_query_main.EXTERNAL_BENCHMARK_PROVIDER = original_provider

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_system_learning_harness_candidates_returns_eval_ready_cases(self):
        with workspace_temp_dir() as temp_dir:
            original_dir = ai_query_main.LEARNING_INBOX_DIR
            ai_query_main.LEARNING_INBOX_DIR = Path(temp_dir)
            try:
                ai_query_main.write_learning_sample(
                    trace_id="trace_eval_1",
                    question="江门嘉华3月经营情况",
                    stage="query",
                    reason="low_confidence_parse",
                    parsed={
                        "metric_code": "OPERATING_PROFIT",
                        "compare_mode": "budget",
                        "time_scope": "202603",
                        "skill_id": "hotel_operation_overview",
                        "requested_hotels": ["江门嘉华"],
                        "query_plan": {"query_object_type": "single_hotel", "query_grain": "hotel"},
                    },
                    row_count=0,
                    extra={"metric_code": "OPERATING_PROFIT", "query_object_type": "single_hotel"},
                )
                result = ai_query_main.system_learning_harness_candidates(days=7, limit=5)
                self.assertEqual(result["candidate_count"], 1)
                candidate = result["candidates"][0]
                self.assertEqual(candidate["expected"]["metric_code"], "OPERATING_PROFIT")
                self.assertEqual(candidate["expected"]["skill_id"], "hotel_operation_overview")
                self.assertEqual(candidate["expected"]["requested_hotels"], ["江门嘉华"])
                self.assertIn("OPERATING_PROFIT_MTD_A", candidate["sql_assertions"]["contains"])
            finally:
                ai_query_main.LEARNING_INBOX_DIR = original_dir

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_explain_sql_targets_real_detail_table(self):
        sql = ai_query_main.build_explain_sql(
            {"compare_mode": "budget", "time_scope": "202601"},
            requested_hotels=["广州柏悦"],
            requested_areas=["华南区"],
        )
        self.assertIn("FROM vw_pnl_fact", sql)
        self.assertIn("mtd_B AS compare_value", sql)
        self.assertIn("area IN ('华南区')", sql)
        self.assertIn("hotel_name_s IN ('广州柏悦')", sql)

    @unittest.skipIf(explanation_main is None, f"explanation-service deps missing: {explanation_error}")
    def test_metric_response_uses_overview_context_when_available(self):
        req = explanation_main.Req(
            question="广州丽思卡尔顿酒店3月的经营情况",
            parsed_intent={"metric_code": "OPERATING_PROFIT", "intent": "query", "compare_mode": "budget"},
            rows=[
                {
                    "hotel_name": "广州丽思卡尔顿酒店",
                    "area": "华南区",
                    "brand": "国际品牌",
                    "brand_child": "丽思卡尔顿",
                    "brand_level": "奢华级",
                    "actual_value": 9000000.0,
                    "compare_value": 8500000.0,
                    "diff_value": 500000.0,
                    "diff_rate": 0.0588,
                    "total_income_actual": 24000000.0,
                    "total_income_budget": 23000000.0,
                    "total_income_last_year": 22000000.0,
                    "room_income_actual": 15000000.0,
                    "restaurant_income_actual": 3000000.0,
                    "banquet_income_actual": 2000000.0,
                    "other_dept_income_actual": 500000.0,
                    "other_rate_income_actual": 300000.0,
                    "occupancy_rate_actual": 0.72,
                    "occupancy_rate_budget": 0.68,
                    "occupancy_rate_last_year": 0.7,
                    "adr_actual": 1200.0,
                    "revpar_actual": 864.0,
                    "operating_profit_actual": 9000000.0,
                    "operating_profit_budget": 8500000.0,
                    "operating_profit_last_year": 8300000.0,
                    "people_cost_actual": 3800000.0,
                    "energy_expenses_actual": 900000.0,
                    "restaurant_cost_actual": 1800000.0,
                }
            ],
        )
        result = explanation_main.explain(req)
        income_section = next(item for item in result["report_sections"] if item["title"] == "收入质量")
        room_section = next(item for item in result["report_sections"] if item["title"] == "客房效率")
        profit_section = next(item for item in result["report_sections"] if item["title"] == "利润质量")
        cost_section = next(item for item in result["report_sections"] if item["title"] == "成本效率")
        self.assertIn("总收入", income_section["content"])
        self.assertIn("ADR", room_section["content"])
        self.assertIn("NOP业主净利润", profit_section["content"])
        self.assertIn("GOP率", profit_section["content"])
        self.assertIn("人工成本", cost_section["content"])

    @unittest.skipIf(semantic_main is None, f"semantic-service deps missing: {semantic_error}")
    def test_semantic_query_plan_exposes_analysis_contract_for_group_dimension(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(
                semantic_main.Req(
                    question="请分析一下公司所有酒店3月份的经营情况，请汇总到管理公司和区域维度输出",
                    time_scope="202601",
                )
            )
        contract = result["query_plan"].get("analysis_contract")
        self.assertIsInstance(contract, dict)
        self.assertEqual(contract["objective_code"], "dimension_comparison")
        self.assertEqual(contract["response_shape"], "executive_group_dimension")
        self.assertEqual(contract["headline_metric"]["code"], "OWNER_PROFIT")
        self.assertIn("manage_corp", contract["primary_dimensions"])
        self.assertIn("area", contract["primary_dimensions"])
        self.assertIn("scope_overview", contract["block_sequence"])
        self.assertIn("dimension_summary", contract["block_sequence"])

    @unittest.skipIf(explanation_main is None, f"explanation-service deps missing: {explanation_error}")
    def test_explanation_returns_analysis_blocks_and_narrative_brief(self):
        req = explanation_main.Req(
            question="请分析一下公司所有酒店3月份的经营情况，请汇总到管理公司和区域维度输出",
            parsed_intent={
                "metric_code": "OWNER_PROFIT",
                "intent": "query",
                "compare_mode": "yoy",
                "analysis_focus": "dimension_comparison",
                "query_plan": {
                    "query_object_type": "hotel_group",
                    "query_object_label": "公司全部酒店",
                    "query_grain": "portfolio",
                    "analysis_mode": "group_by_dimension_report",
                    "metric_bundle_code": "group_dimension_overview",
                    "report_template_code": "executive_group_dimension",
                    "analysis_contract": {
                        "objective_code": "dimension_comparison",
                        "response_shape": "executive_group_dimension",
                        "headline_metric": {"code": "OWNER_PROFIT", "name": "NOP业主净利润"},
                        "primary_dimensions": ["manage_corp", "area"],
                        "block_sequence": ["scope_overview", "dimension_summary", "income_quality", "profit_quality", "benchmark"],
                    },
                },
            },
            rows=[
                {
                    "hotel_name": "公司全部酒店",
                    "area": "全部范围",
                    "actual_value": 81120537.96,
                    "compare_value": 88417506.18,
                    "diff_value": -7297068.22,
                    "diff_rate": -0.083,
                    "portfolio_member_count": 83,
                    "total_income_actual": 302120537.96,
                    "room_income_actual": 188120537.96,
                    "restaurant_income_actual": 45120537.96,
                    "banquet_income_actual": 32120537.96,
                    "occupancy_rate_actual": 0.64,
                    "adr_actual": 688.0,
                    "revpar_actual": 440.32,
                    "owner_profit_actual": 81120537.96,
                    "operating_profit_actual": 93210537.96,
                    "people_cost_actual": 5785484.02,
                }
            ],
            dimension_breakdowns={
                "manage_corp": [
                    {
                        "dimension_value": "国际品牌",
                        "actual_value": 52000000.0,
                        "compare_value": 55000000.0,
                        "diff_value": -3000000.0,
                        "diff_rate": -0.0545,
                        "hotel_count": 32,
                    }
                ],
                "area": [
                    {
                        "dimension_value": "华南区",
                        "actual_value": 33000000.0,
                        "compare_value": 35000000.0,
                        "diff_value": -2000000.0,
                        "diff_rate": -0.0571,
                        "hotel_count": 16,
                    }
                ],
            },
        )
        result = explanation_main.explain(req)
        self.assertIsInstance(result.get("analysis_blocks"), list)
        self.assertEqual(result.get("analysis_agent", {}).get("agent"), "analysis_agent")
        self.assertEqual(result.get("analysis_agent", {}).get("contract_version"), "1.0")
        block_codes = [item.get("code") for item in result["analysis_blocks"]]
        self.assertIn("scope_overview", block_codes)
        self.assertIn("dimension_summary", block_codes)
        self.assertIn("profit_quality", block_codes)
        self.assertIsInstance(result.get("narrative_brief"), dict)
        self.assertEqual(result.get("narrative_agent", {}).get("agent"), "narrative_agent")
        self.assertEqual(result.get("narrative_agent", {}).get("contract_version"), "1.0")
        self.assertEqual(result["narrative_brief"]["template_code"], "executive_group_dimension")
        self.assertEqual(result["narrative_brief"]["focus"], "dimension_comparison")
        self.assertTrue(result["narrative_brief"]["headline"])
        income_block = next(item for item in result["analysis_blocks"] if item.get("code") == "income_quality")
        self.assertIn("TOTAL_INCOME", income_block["metrics_used"])
        self.assertIn("total_income_actual", income_block["evidence_fields"])
        self.assertEqual(income_block["data_status"], "available")

    @unittest.skipIf(explanation_main is None, f"explanation-service deps missing: {explanation_error}")
    def test_analysis_block_missing_status_includes_reason_and_narrative_guardrail(self):
        req = explanation_main.Req(
            question="只看客房效率",
            parsed_intent={
                "metric_code": "OWNER_PROFIT",
                "intent": "query",
                "compare_mode": "yoy",
                "analysis_focus": "metric_snapshot",
                "query_plan": {
                    "query_object_type": "single_hotel",
                    "query_object_label": "江门嘉华酒店",
                    "query_grain": "hotel",
                    "analysis_mode": "hotel_metric_snapshot",
                    "metric_bundle_code": "hotel_snapshot",
                    "report_template_code": "executive_hotel_snapshot",
                    "analysis_contract": {
                        "headline_metric": {"code": "OWNER_PROFIT", "name": "NOP业主净利润"},
                        "block_sequence": ["scope_overview", "room_efficiency"],
                    },
                },
            },
            rows=[
                {
                    "hotel_name": "江门嘉华酒店",
                    "actual_value": 100.0,
                    "compare_value": 90.0,
                    "diff_value": 10.0,
                    "diff_rate": 0.111,
                    "owner_profit_actual": 100.0,
                }
            ],
        )
        result = explanation_main.explain(req)
        room_block = next(item for item in result["analysis_blocks"] if item.get("code") == "room_efficiency")
        self.assertEqual(room_block["data_status"], "partial")
        self.assertTrue(room_block["missing_reason"])
        self.assertIn("occupancy_rate_actual", room_block["missing_fields"])
        self.assertEqual(result["narrative_agent"]["guardrail"]["status"], "passed")
        self.assertIn("no_unbacked_facts", result["narrative_agent"]["guardrail"]["checks"])

    @unittest.skipIf(explanation_main is None, f"explanation-service deps missing: {explanation_error}")
    def test_narrative_guardrail_flags_missing_data_overstatement(self):
        result = explanation_main.run_narrative_agent(
            result={"summary": "RevPAR表现完整可判断。"},
            parsed_intent={
                "query_plan": {
                    "report_template_code": "executive_hotel_snapshot",
                    "metric_bundle_code": "hotel_snapshot",
                }
            },
            template_code="executive_hotel_snapshot",
            bundle_code="hotel_snapshot",
            bundle={},
            focus_profile={},
            analysis_blocks=[
                {
                    "code": "room_efficiency",
                    "data_status": "partial",
                    "missing_fields": ["revpar_actual"],
                    "content": "当前结果未包含 RevPAR。",
                }
            ],
        )
        self.assertEqual(result["guardrail"]["status"], "warning")
        self.assertIn("missing_data_overstated", result["guardrail"]["checks"])
        self.assertEqual(result["guardrail"]["warnings"][0]["block"], "room_efficiency")

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_trace_events_includes_core_pipeline_and_agent_metadata(self):
        events = ai_query_main.build_trace_events(
            timings={
                "semantic_ms": 12,
                "sql_guardrail_ms": 3,
                "db_executor_ms": 22,
                "explanation_ms": 8,
                "total_ms": 60,
            },
            parsed={"query_plan": {"analysis_mode": "group_by_dimension_report"}},
            sql_plan={"safe": True, "warnings": []},
            explanation_payload={
                "analysis_agent": {"agent": "analysis_agent", "contract_version": "1.0"},
                "narrative_agent": {"agent": "narrative_agent", "contract_version": "1.0", "guardrail": {"status": "passed"}},
            },
            warnings=[],
        )
        stages = [item["stage"] for item in events]
        self.assertIn("parse_intent", stages)
        self.assertIn("sql_guardrail", stages)
        self.assertIn("execute_sql", stages)
        self.assertIn("build_analysis_blocks", stages)
        self.assertIn("build_narrative_brief", stages)
        narrative_event = next(item for item in events if item["stage"] == "build_narrative_brief")
        self.assertEqual(narrative_event["metadata"]["guardrail_status"], "passed")

    @unittest.skipIf(explanation_main is None, f"explanation-service deps missing: {explanation_error}")
    def test_explanation_analysis_blocks_follow_contract_block_sequence(self):
        req = explanation_main.Req(
            question="只看收入和利润",
            parsed_intent={
                "metric_code": "OWNER_PROFIT",
                "intent": "query",
                "compare_mode": "yoy",
                "analysis_focus": "dimension_comparison",
                "query_plan": {
                    "query_object_type": "hotel_group",
                    "query_object_label": "公司全部酒店",
                    "query_grain": "portfolio",
                    "analysis_mode": "group_by_dimension_report",
                    "metric_bundle_code": "group_dimension_overview",
                    "report_template_code": "executive_group_dimension",
                    "analysis_contract": {
                        "headline_metric": {"code": "OWNER_PROFIT", "name": "NOP业主净利润"},
                        "block_sequence": ["scope_overview", "income_quality", "profit_quality"],
                    },
                },
            },
            rows=[
                {
                    "hotel_name": "公司全部酒店",
                    "actual_value": 100.0,
                    "compare_value": 90.0,
                    "diff_value": 10.0,
                    "diff_rate": 0.111,
                    "portfolio_member_count": 83,
                    "total_income_actual": 1000.0,
                    "room_income_actual": 600.0,
                    "restaurant_income_actual": 200.0,
                    "banquet_income_actual": 100.0,
                    "owner_profit_actual": 100.0,
                    "operating_profit_actual": 120.0,
                    "people_cost_actual": 50.0,
                    "revpar_actual": 300.0,
                }
            ],
        )
        result = explanation_main.explain(req)
        block_codes = [item.get("code") for item in result["analysis_blocks"]]
        self.assertEqual(block_codes, ["scope_overview", "income_quality", "profit_quality"])

    @unittest.skipIf(db_executor_main is None, f"db-executor-service deps missing: {db_executor_error}")
    def test_csv_fallback_understands_current_real_table_names(self):
        sql = """
        SELECT
          COALESCE(s.hotel_name_s, o.hotel_name) AS hotel_name,
          s.area AS area,
          o.TOTAL_INCOME_MTD_A AS total_income_actual,
          o.OCCUPANCY_RATE_MTD_A AS occupancy_rate_actual,
          o.TOTAL_INCOME_MTD_A AS actual_value,
          o.TOTAL_INCOME_MTD_B AS compare_value
        FROM wddm_dim_overview_cockpit_f o LEFT JOIN dim_allhotel_slcp s ON s.hotel_name_f = o.hotel_name
        WHERE o.CALMONTH = '202601'
        LIMIT 2
        """
        rows = db_executor_main.run_real_overview_query(sql)
        if rows:
            self.assertIn("total_income_actual", rows[0])
            self.assertIn("occupancy_rate_actual", rows[0])
        else:
            self.assertEqual(rows, [])

    @unittest.skipIf(db_executor_main is None, f"db-executor-service deps missing: {db_executor_error}")
    def test_db_query_returns_empty_result_instead_of_synthetic_fallback(self):
        with patch.object(db_executor_main, "local_warehouse_available", return_value=False), patch.object(
            db_executor_main, "get_engine", side_effect=RuntimeError("db unavailable")
        ):
            result = db_executor_main.db_query(db_executor_main.Req(sql="SELECT * FROM totally_unknown_table"))
        self.assertEqual(result["source"], "empty_result")
        self.assertEqual(result["row_count"], 0)
        self.assertEqual(result["rows"], [])

    @unittest.skipIf(eval_runner is None, f"eval runner deps missing: {eval_error}")
    def test_eval_harness_semantic_sql_cases_pass(self):
        failed_count, results = eval_runner.run_eval(eval_runner.DEFAULT_CASES)
        self.assertEqual(failed_count, 0, [item for item in results if not item["passed"]])

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_quick_filters_reflects_scope_brand_compare_and_mode(self):
        result = ai_query_main.build_quick_filters(
            {
                "time_scope": "202402",
                "compare_mode": "budget",
                "analysis_focus": "income_structure",
                "requested_areas": ["华南区"],
                "requested_brand_children": ["万豪"],
                "query_plan": {
                    "query_object_label": "富力体系酒店集合",
                    "analysis_mode": "portfolio_overview",
                },
            },
            [{"hotel_name": "富力体系酒店集合"}],
            [
                {"hotel_name": "广州富力丽思卡尔顿酒店及公寓", "area": "华南区", "brand_child": "万豪"},
                {"hotel_name": "镇江富力喜来登酒店", "area": "华东区", "brand_child": "万豪"},
            ],
        )
        labels = [item["label"] for item in result]
        self.assertIn("区域", labels)
        self.assertIn("酒店", labels)
        self.assertIn("月份", labels)
        self.assertIn("品牌", labels)
        self.assertIn("口径", labels)
        self.assertIn("进一步", labels)
        self.assertIn("分析方式", labels)
        flattened = " ".join(str(option["label"]) for group in result for option in group["items"])
        self.assertIn("万豪", flattened)
        self.assertIn("同比变化", flattened)
        self.assertIn("经营摘要", flattened)
        self.assertIn("利润成本", flattened)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_quick_filters_prefers_single_hotel_template(self):
        result = ai_query_main.build_quick_filters(
            {
                "time_scope": "202402",
                "compare_mode": "budget",
                "requested_hotels": ["广州富力丽思卡尔顿酒店及公寓"],
                "requested_brand_children": ["万豪"],
                "query_plan": {
                    "query_object_type": "single_hotel",
                    "query_object_label": "广州富力丽思卡尔顿酒店及公寓",
                    "query_grain": "hotel",
                    "analysis_mode": "hotel_metric_snapshot",
                },
            },
            [{"hotel_name": "广州富力丽思卡尔顿酒店及公寓", "area": "华南区", "brand_child": "万豪"}],
            [],
        )
        labels = [item["label"] for item in result]
        self.assertEqual(labels[:4], ["月份", "口径", "进一步", "分析方式"])

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_quick_filters_prefers_area_template(self):
        result = ai_query_main.build_quick_filters(
            {
                "time_scope": "202402",
                "compare_mode": "budget",
                "requested_areas": ["华南区"],
                "requested_brand_children": ["万豪"],
                "query_plan": {
                    "query_object_type": "area_scope",
                    "query_object_label": "华南区",
                    "query_grain": "comparison",
                    "analysis_mode": "hotel_metric_snapshot",
                },
            },
            [
                {"hotel_name": "广州富力丽思卡尔顿酒店及公寓", "area": "华南区", "brand_child": "万豪"},
                {"hotel_name": "江门嘉华酒店", "area": "华南区", "brand_child": "嘉华"},
            ],
            [],
        )
        labels = [item["label"] for item in result]
        self.assertEqual(labels[:4], ["酒店", "品牌", "月份", "进一步"])

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_quick_filters_hides_repeat_driver_prompt_when_follow_up_mode_is_driver(self):
        result = ai_query_main.build_quick_filters(
            {
                "time_scope": "202402",
                "compare_mode": "yoy",
                "analysis_focus": "driver_analysis",
                "query_plan": {
                    "query_object_type": "single_hotel",
                    "query_object_label": "广州富力丽思卡尔顿酒店及公寓",
                    "query_grain": "hotel",
                    "analysis_mode": "driver_analysis",
                    "follow_up_mode": "driver",
                },
            },
            [{"hotel_name": "广州富力丽思卡尔顿酒店及公寓", "area": "华南区", "brand_child": "万豪"}],
            [],
        )
        flattened = " ".join(str(option["label"]) for group in result for option in group["items"])
        self.assertNotIn("继续原因", flattened)
        self.assertIn("经营摘要", flattened)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_query_route_classifies_portfolio_scope_and_single_hotel_paths(self):
        portfolio_route = ai_query_main._query_route(
            {
                "query_plan": {
                    "query_object_type": "hotel_group",
                    "query_grain": "portfolio",
                    "group_by_dimensions": ["manage_corp", "area"],
                }
            }
        )
        scope_route = ai_query_main._query_route(
            {
                "query_plan": {
                    "query_object_type": "area_scope",
                    "query_grain": "comparison",
                }
            }
        )
        hotel_route = ai_query_main._query_route(
            {
                "query_plan": {
                    "query_object_type": "single_hotel",
                    "query_grain": "hotel",
                }
            }
        )
        self.assertEqual(portfolio_route, "portfolio_group_breakdown")
        self.assertEqual(scope_route, "scope_detail")
        self.assertEqual(hotel_route, "single_hotel_detail")

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_incomplete_portfolio_quality_suppresses_partial_scope(self):
        parsed = {
            "query_plan": {
                "query_grain": "portfolio",
                "resolved_hotel_count": 83,
            }
        }
        quality = ai_query_main.incomplete_portfolio_quality(parsed, [{"portfolio_member_count": 50}])
        self.assertEqual(quality["status"], "mismatch")
        self.assertEqual(quality["expected_hotel_count"], 83)
        self.assertEqual(quality["actual_hotel_count"], 50)

        overcomplete_quality = ai_query_main.incomplete_portfolio_quality(parsed, [{"portfolio_member_count": 84}])
        self.assertEqual(overcomplete_quality["status"], "mismatch")

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_portfolio_sql_counts_distinct_hotels(self):
        sql = ai_query_main.build_portfolio_sql(
            {
                "source_table": "wddm_dim_overview_cockpit_f",
                "period_fields": {
                    "MTD": {
                        "actual": "OWNER_PROFIT_MTD_A",
                        "budget": "OWNER_PROFIT_MTD_B",
                        "last_year": "OWNER_PROFIT_MTD_L",
                    }
                },
            },
            {
                "period_type": "MTD",
                "compare_mode": "yoy",
                "time_scope": "202603",
                "query_plan": {
                    "query_object_type": "hotel_group",
                    "query_object_label": "公司全部酒店",
                    "query_grain": "portfolio",
                },
            },
        )
        self.assertIn("COUNT(DISTINCT TRIM(COALESCE(s.hotel_name_s, o.hotel_name))) AS portfolio_member_count", sql)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_sql_uses_analysis_focus_for_yoy_ordering(self):
        sql = ai_query_main.build_sql(
            {
                "source_table": "wddm_dim_overview_cockpit_f",
                "period_fields": {
                    "MTD": {
                        "actual": "OPERATING_PROFIT_MTD_A",
                        "budget": "OPERATING_PROFIT_MTD_B",
                        "last_year": "OPERATING_PROFIT_MTD_L",
                    }
                },
            },
            {
                "period_type": "MTD",
                "compare_mode": "yoy",
                "analysis_focus": "yoy_change",
                "time_scope": "202603",
                "query_plan": {
                    "query_object_type": "single_hotel",
                    "query_grain": "hotel",
                },
            },
            requested_hotels=["广州丽思卡尔顿酒店"],
        )
        self.assertIn(
            "ORDER BY ABS((o.OPERATING_PROFIT_MTD_A - o.OPERATING_PROFIT_MTD_L) / NULLIF(o.OPERATING_PROFIT_MTD_L, 0)) DESC",
            sql,
        )

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_quick_filters_prioritizes_management_company_for_portfolio_questions(self):
        result = ai_query_main.build_quick_filters(
            {
                "time_scope": "202402",
                "compare_mode": "budget",
                "requested_manage_corps": ["万达品牌"],
                "requested_areas": ["华南区"],
                "requested_brand_children": ["嘉华"],
                "query_plan": {
                    "query_object_type": "hotel_group",
                    "query_object_label": "公司全部酒店",
                    "query_grain": "portfolio",
                    "analysis_mode": "portfolio_overview",
                },
            },
            [{"hotel_name": "公司全部酒店", "manage_corp": "万达品牌", "area": "华南区", "brand_child": "嘉华"}],
            [{"hotel_name": "广州富力丽思卡尔顿酒店", "manage_corp": "万达品牌", "area": "华南区", "brand_child": "嘉华"}],
        )
        labels = [item["label"] for item in result]
        self.assertEqual(labels[0], "管理公司")
        flattened = " ".join(str(option["label"]) for group in result for option in group["items"])
        self.assertIn("万达品牌", flattened)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_follow_up_prompts_match_portfolio_route_and_focus(self):
        prompts = ai_query_main.build_follow_up_prompts(
            {
                "compare_mode": "yoy",
                "analysis_focus": "driver_analysis",
                "time_scope": "202603",
                "requested_manage_corps": ["万达品牌"],
                "requested_areas": ["华南区"],
                "requested_brand_children": ["嘉华"],
                "query_plan": {
                    "query_object_type": "hotel_group",
                    "query_object_label": "公司全部酒店",
                    "query_grain": "portfolio",
                    "analysis_mode": "portfolio_overview",
                    "follow_up_mode": "driver",
                },
            },
            [],
            [{"hotel_name": "广州富力丽思卡尔顿酒店", "manage_corp": "万达品牌", "area": "华南区", "brand_child": "嘉华"}],
        )
        flattened = " ".join(str(item["prompt"]) for item in prompts)
        self.assertIn("只看万达品牌", flattened)
        self.assertIn("只看华南区", flattened)
        self.assertIn("继续展开原因", flattened)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_build_monthly_hotel_count_sql_uses_overview_month(self):
        sql = ai_query_main.build_monthly_hotel_count_sql(
            {
                "metric_code": "OPERATING_HOTEL_COUNT",
                "time_scope": "202603",
                "requested_areas": [],
            },
            allowed_hotels=["ALL"],
            requested_hotels=[],
            requested_areas=[],
        )
        self.assertIn("FROM wddm_dim_overview_cockpit_f o LEFT JOIN dim_allhotel_slcp s", sql)
        self.assertIn("o.CALMONTH = '202603'", sql)
        self.assertIn("COUNT(DISTINCT COALESCE", sql)

    @unittest.skipIf(ai_query_main is None, f"ai-query-service deps missing: {ai_query_error}")
    def test_summarize_rows_for_monthly_hotel_count_mentions_period(self):
        summary = ai_query_main.summarize_rows(
            {"metric_code": "OPERATING_HOTEL_COUNT", "metric_name": "在营酒店数", "time_scope": "202603", "time_scope_explicit": True},
            [{"hotel_name": "在营酒店数", "area": "全部范围", "actual_value": 94}],
        )
        self.assertIn("202603", summary)
        self.assertIn("94 家", summary)
        self.assertIn("wddm_dim_overview_cockpit_f", summary)


if __name__ == "__main__":
    unittest.main()
