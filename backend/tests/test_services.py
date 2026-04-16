import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


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
        self.assertEqual(result["metric_code"], "OPERATING_PROFIT")
        self.assertEqual(result["compare_mode"], "budget")
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
        self.assertEqual(result["compare_mode"], "budget")
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
        self.assertEqual(income_result["compare_mode"], "budget")
        self.assertEqual(income_result["requested_hotels"], ["广州柏悦"])
        self.assertEqual(profit_result["skill_id"], "hotel_profit_overview")
        self.assertEqual(profit_result["metric_code"], "OPERATING_PROFIT")
        self.assertEqual(profit_result["compare_mode"], "budget")
        self.assertEqual(profit_result["requested_hotels"], ["江门嘉华"])
        self.assertEqual(operation_result["skill_id"], "hotel_operation_overview")
        self.assertEqual(operation_result["metric_code"], "OPERATING_PROFIT")
        self.assertEqual(operation_result["requested_hotels"], ["北京富力万丽酒店"])

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
    def test_semantic_recognizes_pnl_department_and_account(self):
        with patch.object(semantic_main, "call_llm_parse", return_value=None):
            result = semantic_main.parse(
                semantic_main.Req(question="解释江门嘉华3月餐饮部酒水成本为什么偏高", time_scope="202601")
            )
        self.assertIn("餐饮部", result["requested_departments"])
        self.assertIn("酒水成本", result["requested_accounts"])
        self.assertEqual(result["intent"], "explain")

    @unittest.skipIf(metric_main is None, f"metric-service deps missing: {metric_error}")
    def test_metric_alias_lookup(self):
        result = metric_main.get_metric("revenue")
        self.assertEqual(result["metric_code"], "TOTAL_INCOME")

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
        self.assertEqual([item["title"] for item in result["report_sections"]], ["分析范围", "收入质量", "客房效率", "利润质量", "成本效率", "横向对标"])
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
        self.assertEqual(titles, ["分析范围", "收入质量", "客房效率", "利润质量", "成本效率", "横向对标"])
        self.assertIn("当前结果尚未包含", result["report_sections"][1]["content"])
        self.assertIn("入住率", result["report_sections"][2]["content"])
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

        with tempfile.TemporaryDirectory() as temp_dir:
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
        self.assertIn("总收入", result["report_sections"][1]["content"])
        self.assertIn("ADR", result["report_sections"][2]["content"])
        self.assertIn("经营利润率", result["report_sections"][3]["content"])
        self.assertIn("人工成本", result["report_sections"][4]["content"])

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
        self.assertGreaterEqual(len(rows), 1)
        self.assertIn("total_income_actual", rows[0])
        self.assertIn("occupancy_rate_actual", rows[0])

    @unittest.skipIf(eval_runner is None, f"eval runner deps missing: {eval_error}")
    def test_eval_harness_semantic_sql_cases_pass(self):
        failed_count, results = eval_runner.run_eval(eval_runner.DEFAULT_CASES)
        self.assertEqual(failed_count, 0, [item for item in results if not item["passed"]])


if __name__ == "__main__":
    unittest.main()
