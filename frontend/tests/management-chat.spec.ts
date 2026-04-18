import { expect, test, type Page } from "@playwright/test";

async function waitForAssistantResult(page: Page, expectedCount?: number) {
  if (typeof expectedCount === "number") {
    await expect(page.getByTestId("result-card")).toHaveCount(expectedCount);
  } else {
    await expect(page.getByTestId("result-card").last()).toBeVisible();
  }
  await expect(page.getByTestId("result-summary").last()).not.toContainText("暂无数据");
}

function previousMonthScope() {
  const now = new Date();
  const previous = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${previous.getFullYear()}${String(previous.getMonth() + 1).padStart(2, "0")}`;
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.clear();
  });

  await page.route("**/api/v1/system/settings", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        quick_questions: [
          "汇总一下本月所以酒店的经营情况",
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
    const focus = payload.context?.analysis_focus;
    const focusedSummary =
      focus === "driver_analysis" ? "已切换到原因展开：mock酒店 当前波动主要来自收入端和成本端。" :
      focus === "management_report" ? "已生成经营摘要：mock酒店 已整理收入质量、客房效率、利润质量和成本效率。" :
      focus === "yoy_change" ? "已切换到同比变化观察：mock酒店 同比口径已返回。" :
      focus === "income_structure" ? "已切换到收入结构拆解：mock酒店 总收入、客房收入、餐饮/宴会收入结构已返回。" :
      focus === "profit_cost_efficiency" ? "已切换到利润与成本效率拆解：mock酒店 利润质量和成本效率已返回。" :
      null;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        trace_id: "trace_frontend_mock",
        summary: focusedSummary || (isReport ? "已生成 mock酒店 经营摘要。" : "已完成 mock酒店 的经营对比分析，返回 1 家酒店。"),
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
          risks: focus === "income_structure"
            ? ["收入结构：总收入、客房收入、餐饮/宴会收入结构已进入本轮观察。"]
            : focus === "profit_cost_efficiency"
              ? ["利润与成本：经营利润、人工、能耗、餐饮成本和费用率已进入本轮观察。"]
              : ["mock酒店 收入高于预算，正数代表实际高于对比值。"],
          suggestions: focus ? [`当前追问焦点：${focus}`] : ["继续下钻收入结构和客户来源。"],
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
        trace_events: [
          { stage: "parse_intent", status: "completed", duration_ms: 12, metadata: { intent: "query", metric_code: "TOTAL_INCOME" } },
          { stage: "sql_guardrail", status: "completed", duration_ms: 3, metadata: { safe: true } },
          { stage: "execute_sql", status: "completed", duration_ms: 60, metadata: { row_count: 1 } },
          { stage: "build_analysis_blocks", status: "completed", duration_ms: 30, metadata: { agent: "analysis_agent", block_count: 3 } },
          { stage: "build_narrative_brief", status: "completed", duration_ms: 20, metadata: { agent: "narrative_agent", guardrail_status: "passed" } }
        ],
        warnings: []
      })
    });
  });

  await page.goto("/");
  await expect(page.getByText("酒店经营 AI 助手")).toBeVisible();
});

test("发送按钮会返回三段式经营结果", async ({ page }) => {
  const submittedPayloads: any[] = [];
  page.on("request", (request) => {
    if (!request.url().includes("/api/v1/ai/query")) return;
    submittedPayloads.push(request.postDataJSON?.());
  });

  await page.getByTestId("composer-input").fill("本月哪些酒店经营利润未达预算？");
  await page.getByTestId("composer-send").click();

  await waitForAssistantResult(page, 1);
  expect(submittedPayloads.at(-1)?.auth?.role).toBe("GROUP_ADMIN");
  expect(submittedPayloads.at(-1)?.context?.time_scope).toBe(previousMonthScope());
  await expect(page.getByTestId("result-summary").last()).toContainText(/返回|完成|酒店/);
  await expect(page.getByTestId("recognized-scope").last()).toContainText("mock酒店");
  await expect(page.getByTestId("recognized-scope").last()).toContainText("2026年3月");
  await expect(page.getByTestId("recognized-scope").last()).toContainText("单点快照");
  await expect(page.getByTestId("management-overview").last()).toContainText("已完成 mock酒店");
  await expect(page.getByTestId("internal-benchmark-card").last()).toContainText("同区域同品牌");
  await expect(page.getByTestId("advanced-panel")).toBeVisible();
  await expect(page.getByTestId("details-analysis-sections")).toHaveCount(0);
  await expect(page.getByTestId("details-diagnostics")).toHaveCount(0);
  await expect(page.getByTestId("details-sql-plan")).toHaveCount(0);
});

test("集团默认管理层视图，可切换调试视图查看技术细节", async ({ page }) => {
  await expect(page.getByTestId("composer-input")).toHaveValue("汇总一下本月所以酒店的经营情况");
  await page.getByTestId("composer-input").fill("本月哪些酒店经营利润未达预算？");
  await page.getByTestId("composer-send").click();
  await waitForAssistantResult(page, 1);

  await expect(page.getByTestId("details-diagnostics")).toHaveCount(0);
  await page.locator("[data-testid='advanced-panel'] > summary").click();
  await expect(page.getByTestId("view-mode-toggle")).toHaveText("管理层视图");
  await page.getByTestId("view-mode-toggle").click();
  await expect(page.getByTestId("view-mode-toggle")).toHaveText("调试视图");
  await expect(page.getByTestId("details-diagnostics").last()).toBeVisible();
  await expect(page.getByTestId("details-sql-plan").last()).toBeVisible();
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
  const starterButtons = page.getByTestId("starter-prompts").getByRole("button");
  await expect(starterButtons).toHaveCount(8);
  for (const index of [0, 1, 2, 3, 4]) {
    await starterButtons.nth(index).click();
    await waitForAssistantResult(page, index + 1);
    await expect(page.getByTestId("result-summary").last()).toContainText(/已完成|返回|未查询到|生成/);
  }

  await expect(page.getByTestId("details-report-markdown")).toHaveCount(0);
});

test("继续追问按钮会带着上下文返回新结果", async ({ page }) => {
  await page.getByTestId("composer-input").fill("本月哪些酒店经营利润未达预算？");
  await page.getByTestId("composer-send").click();
  await waitForAssistantResult(page, 1);

  await page.getByTestId("follow-up-actions").last().getByRole("button").first().click();

  await waitForAssistantResult(page, 2);
  await expect(page.getByTestId("result-summary").last()).toContainText(/完成|返回|分析|原因展开/);
});

test("不同连续追问会带不同分析焦点并返回差异化结果", async ({ page }) => {
  const submittedPayloads: any[] = [];
  page.on("request", (request) => {
    if (!request.url().includes("/api/v1/ai/")) return;
    submittedPayloads.push(request.postDataJSON?.());
  });

  await page.getByTestId("composer-input").fill("广州丽思卡尔顿酒店3月的经营情况怎么样？");
  await page.getByTestId("composer-send").click();
  await waitForAssistantResult(page, 1);

  const cases = [
    { label: "继续展开原因", focus: "driver_analysis", summary: "原因展开" },
    { label: "换成经营摘要", focus: "management_report", summary: "经营摘要" },
    { label: "看去年同期", focus: "yoy_change", summary: "同比变化" },
    { label: "看收入结构", focus: "income_structure", summary: "收入结构" },
    { label: "看利润和成本效率", focus: "profit_cost_efficiency", summary: "利润与成本效率" },
  ];

  for (const item of cases) {
    await page.getByTestId("follow-up-actions").last().getByRole("button", { name: item.label }).first().click();
    await waitForAssistantResult(page);
    expect(submittedPayloads.at(-1)?.context?.analysis_focus).toBe(item.focus);
    await expect(page.getByTestId("result-summary").last()).toContainText(item.summary);
  }
});

test("会话历史支持新建切换，并恢复各自消息和上下文", async ({ page }) => {
  await expect(page.getByTestId("conversation-panel")).toBeVisible();
  await expect(page.getByTestId("conversation-item")).toHaveCount(1);

  await page.getByTestId("composer-input").fill("广州丽思卡尔顿酒店3月的收入情况怎么样？");
  await page.getByTestId("composer-send").click();
  await waitForAssistantResult(page, 1);
  await expect(page.getByTestId("context-snapshot")).toContainText("mock酒店");
  await expect(page.getByTestId("context-snapshot")).toContainText("2026年3月");

  await page.getByTestId("new-conversation").click();
  await expect(page.getByTestId("conversation-item")).toHaveCount(2);
  await expect(page.getByTestId("result-card")).toHaveCount(0);
  await expect(page.getByText("请输入一个经营问题")).toBeVisible();

  await page.getByTestId("composer-input").fill("本月总收入同比如何？");
  await page.getByTestId("composer-send").click();
  await waitForAssistantResult(page, 1);

  await page.getByTestId("conversation-list").getByRole("button", { name: /广州丽思卡尔顿酒店3月的收入情况怎么样/ }).click();
  await expect(page.getByTestId("result-summary")).toContainText(/已完成|返回/);
  await expect(page.getByTestId("context-snapshot")).toContainText("mock酒店");
});

test("新会话不会继承旧会话的连续追问上下文", async ({ page }) => {
  const submittedQuestions: string[] = [];
  page.on("request", (request) => {
    if (!request.url().includes("/api/v1/ai/query")) return;
    const payload = request.postDataJSON?.();
    submittedQuestions.push(String(payload?.question || ""));
  });

  await page.getByTestId("composer-input").fill("本月哪些酒店经营利润未达预算？");
  await page.getByTestId("composer-send").click();
  await waitForAssistantResult(page, 1);

  await page.getByTestId("new-conversation").click();
  await page.getByTestId("composer-input").fill("继续展开原因");
  await page.getByTestId("composer-send").click();
  await waitForAssistantResult(page, 1);

  expect(submittedQuestions.at(-1)).toBe("继续展开原因");
  await expect(page.getByText("已按上下文理解为：")).toHaveCount(0);
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
          query_plan: { query_object_label: "富力体系酒店集合", query_grain: "portfolio", analysis_mode: "portfolio_overview", report_template_code: "executive_portfolio" }
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
  await expect(page.getByTestId("quick-filters")).toHaveCount(0);
  await expect(page.getByTestId("follow-up-actions").last()).toContainText("继续展开原因");
  await expect(page.getByTestId("follow-up-actions").last()).toContainText("换成经营摘要");
  await page.getByTestId("follow-up-actions").last().getByRole("button", { name: "看去年同期" }).first().click();

  await waitForAssistantResult(page, 2);
  await expect(page.getByTestId("result-summary").last()).toContainText(/完成|返回|分析/);
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
  await expect(page.getByTestId("quick-filters")).toHaveCount(0);
  await expect(page.getByTestId("follow-up-actions").last()).toContainText("继续展开原因");
  await expect(page.getByTestId("follow-up-actions").last()).toContainText("看利润和成本效率");
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
  await expect(page.getByTestId("quick-filters")).toHaveCount(0);
  await expect(page.getByTestId("follow-up-actions").last()).toContainText("继续展开原因");
  await expect(page.getByTestId("follow-up-actions").last()).toContainText("看收入结构");
});

test("集团管理层保留业务设置，非集团角色仍可通过角色视角看到调优配置", async ({ page }) => {
  await expect(page.getByTestId("advanced-panel")).toBeVisible();
  await page.locator("[data-testid='advanced-panel'] > summary").click();
  await expect(page.getByTestId("action-mode-select")).toBeVisible();
  await expect(page.getByTestId("time-scope-input")).toBeVisible();
  await expect(page.getByTestId("view-mode-toggle")).toHaveText("管理层视图");
  await expect(page.getByTestId("external-benchmark-toggle")).toBeVisible();
  await expect(page.getByTestId("role-select")).toHaveCount(0);
  await expect(page.getByTestId("system-config-panel")).toHaveCount(0);

  await page.goto("/?role=AREA_MANAGER");
  await expect(page.getByText("酒店经营 AI 助手")).toBeVisible();
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
  await page.getByTestId("composer-input").fill("生成华南区本月经营摘要");
  await page.getByTestId("composer-send").click();

  await waitForAssistantResult(page, 1);
  await expect(page.getByTestId("result-summary").last()).toContainText(/生成|摘要/);
  await expect(page.getByTestId("details-analysis-sections")).toHaveCount(0);
  await expect(page.getByTestId("details-report-markdown")).toHaveCount(0);
});

test("非集团角色仍可展开查看结构化和技术详情", async ({ page }) => {
  await page.goto("/?role=AREA_MANAGER");
  await expect(page.getByText("酒店经营 AI 助手")).toBeVisible();
  await page.getByTestId("composer-input").fill("本月哪些酒店经营利润未达预算？");
  await page.getByTestId("composer-send").click();

  await waitForAssistantResult(page, 1);

  for (const testId of ["details-data-points", "details-sql-plan", "details-auth-scope"]) {
    await page.locator(`[data-testid='${testId}'] summary`).click();
    await expect(page.locator(`[data-testid='${testId}'][open]`)).toBeVisible();
    await expect(page.locator(`[data-testid='${testId}'] pre`)).not.toBeEmpty();
  }

  await page.locator("[data-testid='details-diagnostics'] summary").click();
  await expect(page.getByTestId("trace-events-summary")).toContainText("语义理解");
  await expect(page.getByTestId("trace-events-summary")).toContainText("叙事生成");
  await expect(page.getByTestId("trace-events-summary")).toContainText("Guardrail：passed");
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
          { hotel_name: "广州富力丽思卡尔顿酒店及公寓", actual_value: 500000, total_income_actual: 500000, owner_profit_actual: 90000, operating_profit_actual: 260000, revpar_actual: 680, compare_value: 420000, diff_value: 80000, diff_rate: 0.19 },
          { hotel_name: "镇江富力喜来登酒店", actual_value: 280000, total_income_actual: 280000, owner_profit_actual: -120000, operating_profit_actual: -80000, revpar_actual: 320, compare_value: 360000, diff_value: -80000, diff_rate: -0.22 }
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
        report_sections: [
          { title: "分析范围", content: "组合总览" },
          { title: "重点酒店与梯队", content: "1. 广州富力丽思卡尔顿酒店及公寓 总收入 500,000；2. 镇江富力喜来登酒店 总收入 280,000。1. 广州富力丽思卡尔顿酒店及公寓 NOP业主净利润 90,000；2. 镇江富力喜来登酒店 NOP业主净利润 -120,000。0-200万 1 家，合计 NOP业主净利润 90,000；亏损 1 家，合计 NOP业主净利润 -120,000。" }
        ],
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
  await expect(page.getByTestId("portfolio-watchlist-table").last()).toContainText("NOP业主净利润");
  await expect(page.getByTestId("portfolio-watchlist-table").last()).toContainText("NOP业主净利润梯队");
  await expect(page.getByTestId("portfolio-outliers").last()).toContainText("收入拉动");
  await expect(page.getByTestId("portfolio-outliers").last()).toContainText("镇江富力喜来登酒店");
});

test("explanation 章节中的指标和排行会结构化展示", async ({ page }) => {
  await page.route("**/api/v1/ai/query", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        trace_id: "trace_structured_sections",
        summary: "已按万达品牌完成分维度经营拆解。",
        parsed_intent: {
          intent: "query",
          metric_code: "OWNER_PROFIT",
          compare_mode: "yoy",
          time_scope: "202603",
          query_plan: {
            query_object_label: "万达品牌",
            query_grain: "portfolio",
            analysis_mode: "group_by_dimension_report",
            report_template_code: "executive_group_dimension"
          }
        },
        metric_definition: { name_cn: "NOP业主净利润" },
        data_points: [{ hotel_name: "万达品牌", actual_value: -100000, compare_value: 0, diff_value: -100000, diff_rate: -0.1 }],
        portfolio_member_count: 5,
        portfolio_breakdown: [
          { hotel_name: "内江嘉华", total_income_actual: 2762981.25, owner_profit_actual: 33061.46, operating_profit_actual: 155301.59, revpar_actual: 171.86, diff_value: 31480.73 },
          { hotel_name: "太原文华", total_income_actual: 2254909.25, owner_profit_actual: -397444.53, operating_profit_actual: -338219.09, revpar_actual: 90.07, diff_value: -398952.29 }
        ],
        explanation: {
          report_sections: [
            { title: "成本效率", content: "人工成本 119,616,730.44（占收入 34.2%）；能源费用 33,888,512.83（占收入 9.7%）；餐饮成本 88,415,077.66（占收入 25.3%）；客房成本 56,109,977.62（占收入 16.1%）；行政费用 80,909,875.62（占收入 23.2%）。" },
            { title: "重点酒店与梯队", content: "1. 内江嘉华 总收入 2,762,981.25；2. 太原文华 总收入 2,254,909.25。1. 内江嘉华 NOP业主净利润 33,061.46；2. 太原文华 NOP业主净利润 -397,444.53。0-200万 1 家，合计 NOP业主净利润 33,061.46；亏损 1 家，合计 NOP业主净利润 -397,444.53。" }
          ]
        },
        data_source: { source: "local_warehouse", warehouse_manifest: { latest_month: "202603" } },
        performance: { total_ms: 260 },
        warnings: []
      })
    });
  });

  await page.getByTestId("composer-input").fill("请分析一下万达所有酒店3月份经营情况，按区域维度输出");
  await page.getByTestId("composer-send").click();

  await waitForAssistantResult(page, 1);
  await expect(page.getByTestId("section-成本效率").last().getByTestId("structured-section-table")).toContainText("指标明细");
  await expect(page.getByTestId("section-成本效率").last().getByTestId("structured-section-table")).toContainText("人工成本");
  await expect(page.getByTestId("portfolio-watchlist-table").last()).toContainText("总收入");
  await expect(page.getByTestId("portfolio-watchlist-table").last()).toContainText("NOP业主净利润梯队");
});

test("analysis blocks 中的指标串会结构化展示", async ({ page }) => {
  await page.route("**/api/v1/ai/query", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        trace_id: "trace_structured_blocks",
        summary: "已按万达品牌完成分维度经营拆解。",
        parsed_intent: {
          intent: "query",
          metric_code: "OWNER_PROFIT",
          compare_mode: "yoy",
          time_scope: "202603",
          query_plan: {
            query_object_label: "万达品牌",
            query_grain: "portfolio",
            analysis_mode: "group_by_dimension_report",
            report_template_code: "executive_group_dimension"
          }
        },
        metric_definition: { name_cn: "NOP业主净利润" },
        data_points: [{ hotel_name: "万达品牌", actual_value: -100000, compare_value: 0, diff_value: -100000, diff_rate: -0.1 }],
        analysis_blocks: [
          {
            title: "成本效率",
            narrative: "人工成本 119,616,730.44（占收入 34.2%）；能源费用 33,888,512.83（占收入 9.7%）；餐饮成本 88,415,077.66（占收入 25.3%）；客房成本 56,109,977.62（占收入 16.1%）；行政费用 80,909,875.62（占收入 23.2%）。"
          }
        ],
        data_source: { source: "local_warehouse", warehouse_manifest: { latest_month: "202603" } },
        performance: { total_ms: 260 },
        warnings: []
      })
    });
  });

  await page.getByTestId("composer-input").fill("请分析一下万达所有酒店3月份经营情况，按区域维度输出");
  await page.getByTestId("composer-send").click();

  await waitForAssistantResult(page, 1);
  await expect(page.getByTestId("analysis-blocks").last().getByTestId("structured-section-table")).toContainText("指标明细");
  await expect(page.getByTestId("analysis-blocks").last().getByTestId("structured-section-table")).toContainText("人工成本");
});
