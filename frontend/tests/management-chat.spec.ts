import { expect, test, type Page } from "@playwright/test";

async function waitForAssistantResult(page: Page, expectedCount?: number) {
  if (typeof expectedCount === "number") {
    await expect(page.getByTestId("result-card")).toHaveCount(expectedCount);
  } else {
    await expect(page.getByTestId("result-card").last()).toBeVisible();
  }
  await expect(page.getByTestId("result-summary").last()).not.toContainText("暂无数据");
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/system/settings", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        quick_questions: [
          "本月哪些酒店经营利润未达预算？",
          "广州丽思卡尔顿酒店3月的收入情况怎么样？",
          "看一下江门嘉华酒店3月的经营情况",
          "本月总收入同比如何？",
          "生成华南区本月经营摘要"
        ],
        model_config: {
          runtime: { fast_model: "qwen3.5-flash", deep_model: "qwen3.6-plus" }
        },
        answer_templates: {
          metric_query: { title: "指标查询", structure: ["结论", "核心数据", "建议"] }
        },
        tuning_stages: [
          { name: "语义解析", observable: "parsed_intent", success_criteria: "参数正确" },
          { name: "SQL生成", observable: "SQL 计划", success_criteria: "字段正确" }
        ]
      })
    });
  });

  await page.route("**/api/v1/ai/**", async (route) => {
    const isReport = route.request().url().includes("/ai/report");
    const payload = route.request().postDataJSON?.() || {};
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        trace_id: "trace_frontend_mock",
        summary: isReport ? "已生成 mock酒店 经营摘要。" : "已完成 mock酒店 的经营对比分析，返回 1 家酒店。",
        parsed_intent: {
          intent: isReport ? "report" : "query",
          metric_code: "TOTAL_INCOME",
          compare_mode: "budget",
          question: payload.question,
          requested_hotels: ["mock酒店"],
          requested_areas: [],
          time_scope: "202603",
          query_plan: { query_object_label: "mock酒店", analysis_mode: "hotel_metric_snapshot" }
        },
        metric_definition: { name_cn: "总收入" },
        data_points: [{ hotel_name: "mock酒店", area: "华南区", actual_value: 1200000, compare_value: 1000000, diff_value: 200000, diff_rate: 0.2 }],
        portfolio_breakdown: payload.question?.includes("富力")
          ? [
              { hotel_name: "广州富力丽思卡尔顿酒店及公寓", actual_value: 500000, compare_value: 420000, diff_value: 80000, diff_rate: 0.19 },
              { hotel_name: "镇江富力喜来登酒店", actual_value: 280000, compare_value: 360000, diff_value: -80000, diff_rate: -0.22 }
            ]
          : [],
        portfolio_outliers: payload.question?.includes("富力")
          ? {
              income: {
                best: { hotel_name: "广州富力丽思卡尔顿酒店及公寓", diff_value: 80000 },
                worst: { hotel_name: "镇江富力喜来登酒店", diff_value: -80000 }
              },
              profit: {
                best: { hotel_name: "广州富力丽思卡尔顿酒店及公寓", operating_profit_actual: 260000 },
                worst: { hotel_name: "镇江富力喜来登酒店", operating_profit_actual: -120000 }
              },
              cost: {
                worst: { hotel_name: "镇江富力喜来登酒店", people_cost_actual: 180000 }
              }
            }
          : null,
        internal_benchmark: {
          peer_count: 8,
          scope_used: "同区域同品牌",
          scope: { area: "华南区", brand: "国际品牌", brand_child: "mock品牌", brand_level: "奢华级", city_level: "一线城市" },
          current: { total_income: 1200000, revpar: 680, operating_profit: 260000, profit_margin: 0.2167, cost_rate: 0.28 },
          peer_avg: { total_income: 1080000, revpar: 620, operating_profit: 220000, profit_margin: 0.2031, cost_rate: 0.31 }
        },
        external_benchmark: {
          requested: true,
          provider: "manual_review",
          status: "awaiting_provider",
          dimensions: ["区域：华南区", "子品牌：mock品牌"],
          message: "你已开启外部行业对标。当前系统会先返回内部经营对标，外部行业数据需按所选 Provider 联网补充后再展示。",
          disclaimers: ["外部行业样本仅供参考。"]
        },
        sql_plan: { safe: true, rewritten_sql: "SELECT 1" },
        auth_scope: { allowed_areas: ["ALL"], allowed_hotels: ["ALL"] },
        explanation: {
          risks: ["mock酒店 收入高于预算，正数代表实际高于对比值。"],
          suggestions: ["继续下钻收入结构和客户来源。"],
          report_sections: [
            { title: "结论", content: "已完成 mock酒店 分析。" },
            { title: "风险", content: "mock酒店 暂无重大负向风险。" },
            { title: "建议", content: "继续下钻收入结构。" }
          ]
        },
        report_sections: isReport ? [
          { title: "结论", content: "已生成 mock酒店 经营摘要。" },
          { title: "风险", content: "暂无重大负向风险。" },
          { title: "建议", content: "继续下钻收入结构。" }
        ] : undefined,
        report_markdown: isReport ? "## 结论\n已生成 mock酒店 经营摘要。\n\n## 风险\n暂无重大负向风险。" : undefined,
        data_source: { source: "local_warehouse", warehouse_manifest: { latest_month: "202603" } },
        performance: { total_ms: 188, semantic_ms: 12, db_executor_ms: 60 },
        warnings: []
      })
    });
  });

  await page.goto("/");
  await expect(page.getByText("酒店经营 AI 助手")).toBeVisible();
});

test("发送按钮会返回三段式经营结果", async ({ page }) => {
  await page.getByTestId("composer-input").fill("本月哪些酒店经营利润未达预算？");
  await page.getByTestId("composer-send").click();

  await waitForAssistantResult(page, 1);
  await expect(page.getByTestId("result-summary").last()).toContainText(/返回|完成|酒店/);
  await expect(page.getByTestId("recognized-scope").last()).toContainText("mock酒店");
  await expect(page.getByTestId("recognized-scope").last()).toContainText("2026年3月");
  await expect(page.getByTestId("recognized-scope").last()).toContainText("单点快照");
  await expect(page.getByTestId("executive-overview").last()).toContainText("管理层速览");
  await expect(page.getByTestId("internal-benchmark-card").last()).toContainText("同区域同品牌");
  await expect(page.getByTestId("details-analysis-sections").last()).toBeVisible();
  await page.locator("[data-testid='details-analysis-sections'] summary").last().click();
  await expect(page.getByTestId("section-结论").last()).toContainText("已完成");
  await expect(page.getByTestId("section-风险").last()).toContainText(/酒店|风险|异常|正负/);
  await expect(page.getByTestId("section-建议").last()).toContainText("下钻");
});

test("发送后会先展示识别口径和阶段进度", async ({ page }) => {
  await page.route("**/api/v1/ai/query", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 900));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        trace_id: "trace_delayed_mock",
        summary: "已完成江门嘉华酒店经营情况分析。",
        parsed_intent: { intent: "query", metric_code: "OPERATING_PROFIT", compare_mode: "budget", requested_hotels: ["江门嘉华"], requested_areas: [], time_scope: "202603" },
        metric_definition: { name_cn: "经营利润" },
        data_source: { source: "local_warehouse", warehouse_manifest: { latest_month: "202603" } },
        data_points: [{ hotel_name: "江门嘉华", area: "华南区", actual_value: 100, compare_value: 90, diff_value: 10, diff_rate: 0.111 }],
        explanation: { report_sections: [{ title: "结论", content: "已完成分析。" }] },
        performance: { total_ms: 180 },
        warnings: []
      })
    });
  });

  await page.getByTestId("composer-input").fill("看一下江门嘉华酒店3月的经营情况");
  await page.getByTestId("composer-send").click();

  await expect(page.getByTestId("loading-card")).toBeVisible();
  await expect(page.getByTestId("loading-intent-strip")).toContainText("江门嘉华");
  await expect(page.getByTestId("loading-intent-strip")).toContainText("2026年3月");
  await expect(page.getByText("读取经营数据", { exact: true })).toBeVisible();

  await waitForAssistantResult(page, 1);
});

test("快捷提问按钮逐个点击都能返回结果", async ({ page }) => {
  for (const index of [0, 1, 2, 3, 4]) {
    await page.getByTestId(`quick-question-${index}`).click();
    await waitForAssistantResult(page, index + 1);
    await expect(page.getByTestId("result-summary").last()).toContainText(/已完成|返回|未查询到|生成/);
  }

  await expect(page.getByTestId("details-report-markdown").last()).toBeVisible();
});

test("继续追问按钮会带着上下文返回新结果", async ({ page }) => {
  await page.getByTestId("composer-input").fill("本月哪些酒店经营利润未达预算？");
  await page.getByTestId("composer-send").click();
  await waitForAssistantResult(page, 1);

  await page.locator("[data-testid='follow-up-actions'] summary").last().click();
  await page.getByTestId("follow-up-0").last().click();

  await expect(page.getByText("已按上下文理解为：").last()).toBeVisible();
  await waitForAssistantResult(page, 2);
  await expect(page.getByTestId("result-summary").last()).toContainText(/已完成|返回|分析/);
});

test("快速筛选会根据问题联想区域酒店月份品牌口径，并能直接触发下一轮追问", async ({ page }) => {
  await page.route("**/api/v1/ai/query", async (route) => {
    const payload = route.request().postDataJSON?.() || {};
    const question = String(payload.question || "");
    if (question.includes("基于“") && question.includes("范围只看广州富力丽思卡尔顿酒店及公寓")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          trace_id: "trace_filter_followup",
          summary: "已切换到广州富力丽思卡尔顿酒店及公寓的单酒店视角。",
          parsed_intent: {
            intent: "query",
            metric_code: "OPERATING_PROFIT",
            compare_mode: "budget",
            time_scope: "202402",
            requested_hotels: ["广州富力丽思卡尔顿酒店及公寓"],
            query_plan: { query_object_label: "广州富力丽思卡尔顿酒店及公寓", query_grain: "hotel", analysis_mode: "hotel_metric_snapshot" }
          },
          metric_definition: { name_cn: "经营利润" },
          data_points: [{ hotel_name: "广州富力丽思卡尔顿酒店及公寓", area: "华南区", actual_value: 500000, compare_value: 420000, diff_value: 80000, diff_rate: 0.19 }],
          data_source: { source: "local_warehouse", warehouse_manifest: { latest_month: "202603" } },
          performance: { total_ms: 180 },
          warnings: []
        })
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        trace_id: "trace_filter_portfolio",
        summary: "已按富力体系酒店集合完成组合经营拆解。",
        parsed_intent: {
          intent: "query",
          metric_code: "OPERATING_PROFIT",
          compare_mode: "budget",
          time_scope: "202402",
          requested_brand_children: ["万豪"],
          query_plan: { query_object_label: "富力体系酒店集合", query_grain: "portfolio", analysis_mode: "portfolio_overview" }
        },
        metric_definition: { name_cn: "经营利润" },
        data_points: [{ hotel_name: "富力体系酒店集合", actual_value: -147636.58, compare_value: 0, diff_value: -147636.58, diff_rate: null }],
        portfolio_member_count: 7,
        portfolio_breakdown: [
          { hotel_name: "广州富力丽思卡尔顿酒店及公寓", area: "华南区", brand_child: "万豪", actual_value: 500000, compare_value: 420000, diff_value: 80000, diff_rate: 0.19 },
          { hotel_name: "镇江富力喜来登酒店", area: "华东区", actual_value: 280000, compare_value: 360000, diff_value: -80000, diff_rate: -0.22 }
        ],
        data_source: { source: "local_warehouse", warehouse_manifest: { latest_month: "202603" } },
        performance: { total_ms: 220 },
        warnings: []
      })
    });
  });

  await page.getByTestId("composer-input").fill("查一下2024年2月富力所有酒店的总体经营情况");
  await page.getByTestId("composer-send").click();

  await waitForAssistantResult(page, 1);
  await page.locator("[data-testid='follow-up-actions'] summary").last().click();
  await expect(page.getByTestId("quick-filters").last()).toContainText("区域");
  await expect(page.getByTestId("quick-filters").last()).toContainText("酒店");
  await expect(page.getByTestId("quick-filters").last()).toContainText("月份");
  await expect(page.getByTestId("quick-filters").last()).toContainText("品牌");
  await expect(page.getByTestId("quick-filters").last()).toContainText("口径");
  await expect(page.getByTestId("quick-filters").last()).toContainText("分析方式");
  await expect(page.getByTestId("quick-filters").last()).toContainText("万豪");
  await expect(page.getByTestId("quick-filters").last()).toContainText("同比变化");
  await page.getByRole("button", { name: "广州富力丽思卡尔顿酒店及公寓" }).last().click();

  await expect(page.getByText("已按上下文理解为：").last()).toBeVisible();
  await waitForAssistantResult(page, 2);
  await expect(page.getByTestId("result-summary").last()).toContainText("单酒店视角");
});

test("单酒店问题会优先展示月份口径归因和摘要类筛选", async ({ page }) => {
  await page.route("**/api/v1/ai/query", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        trace_id: "trace_single_hotel_filters",
        summary: "已完成广州富力丽思卡尔顿酒店及公寓的经营分析。",
        parsed_intent: {
          intent: "query",
          metric_code: "OPERATING_PROFIT",
          compare_mode: "budget",
          time_scope: "202402",
          requested_hotels: ["广州富力丽思卡尔顿酒店及公寓"],
          query_plan: { query_object_label: "广州富力丽思卡尔顿酒店及公寓", query_object_type: "single_hotel", query_grain: "hotel", analysis_mode: "hotel_metric_snapshot" }
        },
        metric_definition: { name_cn: "经营利润" },
        data_points: [{ hotel_name: "广州富力丽思卡尔顿酒店及公寓", area: "华南区", brand_child: "万豪", actual_value: 500000, compare_value: 420000, diff_value: 80000, diff_rate: 0.19 }],
        quick_filters: [
          { label: "月份", items: [{ label: "2024年1月", prompt: "切到2024年1月" }] },
          { label: "口径", items: [{ label: "同比变化", prompt: "切换成同比变化" }] },
          { label: "分析方式", items: [{ label: "归因分析", prompt: "继续展开原因" }, { label: "经营摘要", prompt: "换成经营摘要" }] },
          { label: "品牌", items: [{ label: "万豪", prompt: "只看万豪品牌" }] }
        ],
        data_source: { source: "local_warehouse", warehouse_manifest: { latest_month: "202603" } },
        performance: { total_ms: 160 },
        warnings: []
      })
    });
  });

  await page.getByTestId("composer-input").fill("看一下广州富力丽思卡尔顿酒店及公寓2月的经营情况");
  await page.getByTestId("composer-send").click();

  await waitForAssistantResult(page, 1);
  await page.locator("[data-testid='follow-up-actions'] summary").last().click();
  const labels = await page.locator("[data-testid='quick-filters'] .quick-filter-label").allTextContents();
  expect(labels.slice(0, 4)).toEqual(["月份", "口径", "分析方式", "品牌"]);
});

test("区域问题会优先展示下钻酒店切品牌切月份和摘要类筛选", async ({ page }) => {
  await page.route("**/api/v1/ai/query", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        trace_id: "trace_area_filters",
        summary: "已完成华南区经营概览。",
        parsed_intent: {
          intent: "query",
          metric_code: "OPERATING_PROFIT",
          compare_mode: "budget",
          time_scope: "202402",
          requested_areas: ["华南区"],
          query_plan: { query_object_label: "华南区", query_object_type: "area_scope", query_grain: "comparison", analysis_mode: "hotel_metric_snapshot" }
        },
        metric_definition: { name_cn: "经营利润" },
        data_points: [
          { hotel_name: "广州富力丽思卡尔顿酒店及公寓", area: "华南区", brand_child: "万豪", actual_value: 500000, compare_value: 420000, diff_value: 80000, diff_rate: 0.19 },
          { hotel_name: "江门嘉华酒店", area: "华南区", brand_child: "嘉华", actual_value: 280000, compare_value: 300000, diff_value: -20000, diff_rate: -0.07 }
        ],
        quick_filters: [
          { label: "酒店", items: [{ label: "广州富力丽思卡尔顿酒店及公寓", prompt: "只看广州富力丽思卡尔顿酒店及公寓" }] },
          { label: "品牌", items: [{ label: "万豪", prompt: "只看万豪品牌" }] },
          { label: "月份", items: [{ label: "2024年1月", prompt: "切到2024年1月" }] },
          { label: "分析方式", items: [{ label: "经营摘要", prompt: "换成经营摘要" }] }
        ],
        data_source: { source: "local_warehouse", warehouse_manifest: { latest_month: "202603" } },
        performance: { total_ms: 170 },
        warnings: []
      })
    });
  });

  await page.getByTestId("composer-input").fill("看一下华南区2月的经营情况");
  await page.getByTestId("composer-send").click();

  await waitForAssistantResult(page, 1);
  await page.locator("[data-testid='follow-up-actions'] summary").last().click();
  const labels = await page.locator("[data-testid='quick-filters'] .quick-filter-label").allTextContents();
  expect(labels.slice(0, 4)).toEqual(["酒店", "品牌", "月份", "分析方式"]);
});

test("高级设置展示模型配置和调优阶段", async ({ page }) => {
  await page.locator("[data-testid='advanced-panel'] > summary").click();
  await expect(page.getByTestId("system-config-panel")).toContainText("模型配置");
  await expect(page.getByTestId("system-config-panel")).toContainText("分阶段调优");
  await expect(page.getByTestId("answer-template-settings")).toBeVisible();
  await expect(page.getByTestId("external-benchmark-toggle")).toHaveText(/未开启|已开启/);
  await page.getByTestId("external-benchmark-toggle").click();
  await expect(page.getByTestId("external-benchmark-toggle")).toHaveText("已开启");
  await expect(page.getByText(/外部行业对标默认关闭；开启后表示你接受系统后续联网补充外部样本/)).toBeVisible();
});

test("报告模式和详情展开都能正常反馈内容", async ({ page }) => {
  await page.locator("[data-testid='advanced-panel'] > summary").click();
  await page.getByTestId("action-mode-select").selectOption("report");
  await page.getByTestId("time-scope-input").fill("202601");
  await page.getByTestId("role-select").selectOption("AREA_MANAGER");
  await expect(page.getByTestId("composer-send")).toHaveText("生成报告");

  await page.getByTestId("composer-input").fill("生成华南区本月经营摘要");
  await page.getByTestId("composer-send").click();

  await waitForAssistantResult(page, 1);
  await expect(page.getByTestId("details-analysis-sections")).toBeVisible();
  await expect(page.getByTestId("details-report-markdown")).toBeVisible();
  await page.locator("[data-testid='details-report-markdown'] summary").click();
  await expect(page.locator("[data-testid='details-report-markdown'][open]")).toBeVisible();
  await expect(page.locator("[data-testid='details-report-markdown'] pre")).toContainText("## 结论");
});

test("查询结果的详情按钮可以展开查看结构化内容", async ({ page }) => {
  await page.getByTestId("composer-input").fill("本月哪些酒店经营利润未达预算？");
  await page.getByTestId("composer-send").click();

  await waitForAssistantResult(page, 1);

  for (const testId of ["details-data-points", "details-sql-plan", "details-auth-scope"]) {
    await page.locator(`[data-testid='${testId}'] summary`).click();
    await expect(page.locator(`[data-testid='${testId}'][open]`)).toBeVisible();
    await expect(page.locator(`[data-testid='${testId}'] pre`)).not.toBeEmpty();
  }
});

test("组合总览问题会优先展示组合口径和组合内重点酒店", async ({ page }) => {
  await page.route("**/api/v1/ai/query", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        trace_id: "trace_portfolio_mock",
        summary: "已按富力体系酒店集合完成组合经营拆解。",
        parsed_intent: {
          intent: "query",
          metric_code: "OPERATING_PROFIT",
          compare_mode: "budget",
          time_scope: "202402",
          query_plan: { query_object_label: "富力体系酒店集合", query_grain: "portfolio", analysis_mode: "portfolio_overview" }
        },
        metric_definition: { name_cn: "经营利润" },
        data_points: [{ hotel_name: "富力体系酒店集合", actual_value: -147636.58, compare_value: 0, diff_value: -147636.58, diff_rate: null }],
        portfolio_member_count: 7,
        portfolio_breakdown: [
          { hotel_name: "广州富力丽思卡尔顿酒店及公寓", actual_value: 500000, compare_value: 420000, diff_value: 80000, diff_rate: 0.19 },
          { hotel_name: "镇江富力喜来登酒店", actual_value: 280000, compare_value: 360000, diff_value: -80000, diff_rate: -0.22 }
        ],
        portfolio_outliers: {
          income: {
            best: { hotel_name: "广州富力丽思卡尔顿酒店及公寓", diff_value: 80000 },
            worst: { hotel_name: "镇江富力喜来登酒店", diff_value: -80000 }
          },
          profit: {
            best: { hotel_name: "广州富力丽思卡尔顿酒店及公寓", operating_profit_actual: 260000 },
            worst: { hotel_name: "镇江富力喜来登酒店", operating_profit_actual: -120000 }
          },
          cost: {
            worst: { hotel_name: "镇江富力喜来登酒店", people_cost_actual: 180000 }
          }
        },
        explanation: { report_sections: [{ title: "分析范围", content: "组合总览" }] },
        data_source: { source: "local_warehouse", warehouse_manifest: { latest_month: "202603" } },
        performance: { total_ms: 260 },
        warnings: []
      })
    });
  });

  await page.getByTestId("composer-input").fill("查一下2024年2月富力所有酒店的总体经营情况");
  await page.getByTestId("composer-send").click();

  await waitForAssistantResult(page, 1);
  await expect(page.getByTestId("recognized-scope").last()).toContainText("富力体系酒店集合");
  await expect(page.getByTestId("recognized-scope").last()).toContainText("组合总览");
  await expect(page.getByTestId("primary-metric-strip").last()).toContainText("7");
  await expect(page.getByTestId("top-data-points").last()).toContainText("广州富力丽思卡尔顿酒店及公寓");
  await expect(page.getByTestId("portfolio-outliers").last()).toContainText("收入拉动");
  await expect(page.getByTestId("portfolio-outliers").last()).toContainText("镇江富力喜来登酒店");
});
