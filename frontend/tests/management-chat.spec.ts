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
        parsed_intent: { intent: isReport ? "report" : "query", metric_code: "TOTAL_INCOME", compare_mode: "budget", question: payload.question, requested_hotels: ["mock酒店"], requested_areas: [], time_scope: "202603" },
        metric_definition: { name_cn: "总收入" },
        data_points: [{ hotel_name: "mock酒店", area: "华南区", actual_value: 1200000, compare_value: 1000000, diff_value: 200000, diff_rate: 0.2 }],
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
  await expect(page.getByTestId("executive-overview").last()).toContainText("管理层速览");
  await expect(page.getByTestId("internal-benchmark-card").last()).toContainText("同区域同品牌");
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

  await page.getByTestId("follow-up-0").last().click();

  await expect(page.getByText("已按上下文理解为：").last()).toBeVisible();
  await waitForAssistantResult(page, 2);
  await expect(page.getByTestId("result-summary").last()).toContainText(/已完成|返回|分析/);
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
