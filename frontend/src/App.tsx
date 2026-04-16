import React, { useEffect, useMemo, useRef, useState } from "react";
import { fetchSystemSettings, submitQuery, submitReport } from "./lib/api";
import { QuickQuestions } from "./components/QuickQuestions";

type QueryStatus = "idle" | "loading" | "success" | "error";
type Role = "GROUP_ADMIN" | "AREA_MANAGER" | "HOTEL_MANAGER";
type ActionMode = "query" | "report";

type Message = {
  id: number;
  sender: "user" | "assistant";
  kind: "text" | "result";
  text: string;
  payload?: any;
  originalQuestion?: string;
};

type ConversationContext = {
  lastQuestion: string | null;
  lastMetric: string | null;
  lastHotel: string | null;
  lastArea: string | null;
  lastSummary: string | null;
};

type SystemSettings = {
  quick_questions?: string[];
  model_config?: any;
  answer_templates?: Record<string, any>;
  tuning_stages?: Array<Record<string, any>>;
};

type QuestionFrame = {
  scope: string;
  period: string;
  metric: string;
  mode: string;
  usedContext: boolean;
};

const ROLE_OPTIONS: Array<{ value: Role; label: string }> = [
  { value: "GROUP_ADMIN", label: "集团管理员" },
  { value: "AREA_MANAGER", label: "区域经理" },
  { value: "HOTEL_MANAGER", label: "单店经理" }
];

const ACTION_OPTIONS: Array<{ value: ActionMode; label: string }> = [
  { value: "query", label: "问答" },
  { value: "report", label: "报告" }
];

const DEFAULT_QUESTION = "本月哪些酒店经营利润未达预算？";
const DEFAULT_TIME_SCOPE = "202601";
const DEFAULT_ROLE: Role = "AREA_MANAGER";
const BASE_FOLLOW_UP_SUGGESTIONS = ["继续展开原因", "只看华南区", "换成经营摘要", "给我行动建议", "看同比变化"];
const FALLBACK_QUICK_QUESTIONS = [
  "本月哪些酒店经营利润未达预算？",
  "广州丽思卡尔顿酒店3月的收入情况怎么样？",
  "看一下江门嘉华酒店3月的经营情况",
  "本月总收入同比如何？",
  "生成华南区本月经营摘要"
];
const LOADING_STEPS = ["已理解问题", "读取经营数据", "生成经营拆解", "准备追问建议"];

function formatJson(value: unknown) {
  if (value == null) return "暂无数据";
  return JSON.stringify(value, null, 2);
}

function formatNumber(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value)) return "N/A";
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function formatPercent(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value)) return "N/A";
  return `${(value * 100).toFixed(1)}%`;
}

function formatTimeScopeLabel(value: unknown) {
  const text = String(value || "");
  if (!/^\d{6}$/.test(text)) return "当前时间范围";
  return `${text.slice(0, 4)}年${Number(text.slice(4, 6))}月`;
}

function cleanScopeName(value: string) {
  return value
    .replace(/^(请|麻烦|帮我|帮忙|给我|看一下|看下|看一看|看看|看|分析一下|分析|查一下|查询|了解一下)+/, "")
    .replace(/(本月|当月|这个月|上月|去年同期|同比|预算|经营情况|经营状况|收入情况|利润情况|表现|情况|怎么样|如何|咋样|\d{1,2}月|20\d{2}年.*)$/g, "")
    .trim();
}

function inferQuestionFrame(input: string, fallbackTimeScope: string, mode: ActionMode, usedContext: boolean): QuestionFrame {
  const monthMatch = input.match(/(20\d{2})\s*年\s*(1[0-2]|0?[1-9])\s*月|(?:^|[^\d])(1[0-2]|0?[1-9])\s*月/);
  const year = fallbackTimeScope.slice(0, 4);
  const month = monthMatch ? Number(monthMatch[2] || monthMatch[3]) : Number(fallbackTimeScope.slice(4, 6));
  const hotelMatch = input.match(/([\u4e00-\u9fa5A-Za-z0-9]{2,30}?(?:酒店|公寓|嘉华|丽思卡尔顿|柏悦|万丽|希尔顿|君悦))/);
  const areaMatch = input.match(/华南区|华东区|华北区|西南区|华中区|中南区|东北区|西北区|海南区/);
  const metric = input.includes("收入") || input.includes("营收")
    ? "收入情况"
    : input.includes("利润")
      ? "利润情况"
      : input.includes("RevPAR") || input.includes("每房收益")
        ? "客房效率"
        : "经营情况";
  return {
    scope: hotelMatch?.[1] ? cleanScopeName(hotelMatch[1]) : areaMatch?.[0] || "当前管理范围",
    period: `${monthMatch?.[1] || year}年${month || Number(fallbackTimeScope.slice(4, 6))}月`,
    metric,
    mode: mode === "report" ? "经营摘要" : "经营问答",
    usedContext,
  };
}

function getIntentLabel(result: any) {
  return result?.parsed_intent?.intent || result?.source_query?.parsed_intent?.intent || "待解析";
}

function getResultSummary(result: any) {
  return result?.summary || "已完成处理，但暂无摘要。";
}

function getHighlights(result: any) {
  if (Array.isArray(result?.risks) && result.risks.length) {
    return result.risks;
  }
  if (Array.isArray(result?.explanation?.risks) && result.explanation.risks.length) {
    return result.explanation.risks;
  }
  if (Array.isArray(result?.report_sections) && result.report_sections.length) {
    return result.report_sections.map((item: any) => `${item.title}：${item.content}`);
  }
  const explanation = result?.explanation;
  if (Array.isArray(explanation?.drivers) && explanation.drivers.length) {
    return explanation.drivers.map((item: any) => item.evidence || item.name);
  }
  if (Array.isArray(explanation?.suggestions) && explanation.suggestions.length) {
    return explanation.suggestions;
  }
  return [];
}

function getPrimarySections(result: any) {
  if (Array.isArray(result?.report_sections) && result.report_sections.length) {
    return result.report_sections;
  }
  if (Array.isArray(result?.explanation?.report_sections) && result.explanation.report_sections.length) {
    return result.explanation.report_sections;
  }
  if (result?.interaction_mode === "clarification" && result?.clarification?.question) {
    return [{ title: "请先确认", content: String(result.clarification.question) }];
  }
  return [];
}

function getExecutiveSummaryLine(result: any) {
  const sections = getPrimarySections(result);
  const conclusion = sections.find((item: any) => item.title === "结论");
  const risk = sections.find((item: any) => item.title === "风险");
  if (!conclusion && !risk) return null;
  return [conclusion?.content, risk?.content].filter(Boolean).join(" ");
}

function extractContext(result: any, question: string): ConversationContext {
  const summary = String(result?.summary || "");
  const firstPoint = Array.isArray(result?.data_points) && result.data_points.length ? result.data_points[0] : null;
  const firstSection = Array.isArray(result?.report_sections) && result.report_sections.length ? result.report_sections[0] : null;
  const metric =
    result?.metric_definition?.name_cn ||
    result?.parsed_intent?.metric_code ||
    result?.source_query?.parsed_intent?.metric_code ||
    null;
  const hotel =
    firstPoint?.hotel_name ||
    result?.auth_scope?.allowed_hotels?.find((item: string) => item !== "ALL") ||
    (summary.match(/示例酒店[A-Z]/)?.[0] ?? null);
  const area =
    firstPoint?.area ||
    result?.auth_scope?.allowed_areas?.find((item: string) => item !== "ALL") ||
    (question.match(/华南区|华东区|华北区|西南区|华中区|东北区|西北区/)?.[0] ?? null);

  return {
    lastQuestion: question,
    lastMetric: metric,
    lastHotel: hotel,
    lastArea: area,
    lastSummary: String(firstSection?.content || summary || "")
  };
}

function getFollowUpSuggestions(context: ConversationContext) {
  const dynamic: string[] = [];
  if (context.lastHotel) {
    dynamic.push(`只看${context.lastHotel}`);
    dynamic.push(`继续分析${context.lastHotel}原因`);
  }
  if (context.lastArea) {
    dynamic.push(`只看${context.lastArea}`);
    dynamic.push(`生成${context.lastArea}经营摘要`);
  }
  if (context.lastMetric) {
    dynamic.push(`看${context.lastMetric}同比变化`);
    dynamic.push(`给出${context.lastMetric}管理建议`);
  }
  return [...dynamic, ...BASE_FOLLOW_UP_SUGGESTIONS].filter((item, index, arr) => arr.indexOf(item) === index).slice(0, 6);
}

function getClarificationSuggestions(result: any) {
  if (Array.isArray(result?.clarification?.options) && result.clarification.options.length) {
    return result.clarification.options.map((item: any) => String(item));
  }
  return BASE_FOLLOW_UP_SUGGESTIONS.slice(0, 4);
}

function getRuntimeModelLine(settings: SystemSettings | null) {
  const runtime = settings?.model_config?.runtime;
  if (!runtime) return "模型配置读取中";
  return `快模型：${runtime.fast_model || "未配置"}；深度模型：${runtime.deep_model || "未配置"}；解析策略：${runtime.parse_policy || "auto"}；解释增强：${runtime.explanation_policy || "off"}`;
}

function getDataSourceLabel(result: any) {
  const source = result?.data_source?.source;
  if (source === "local_warehouse") return "本地分析缓存";
  if (source === "database") return "实时数据库";
  if (source === "real_csv") return "本地真实 CSV";
  if (source === "fallback") return "示例兜底数据";
  return "数据已返回";
}

function getMetricLabel(result: any) {
  return result?.metric_definition?.name_cn || result?.parsed_intent?.metric_code || "经营指标";
}

function getPerformanceLabel(result: any) {
  const totalMs = result?.performance?.total_ms;
  if (typeof totalMs !== "number") return null;
  if (totalMs < 1000) return `${totalMs}ms`;
  return `${(totalMs / 1000).toFixed(1)}s`;
}

function getRecognizedScopeItems(result: any) {
  const parsed = result?.parsed_intent || result?.source_query?.parsed_intent || {};
  const hotels = Array.isArray(parsed.requested_hotels) ? parsed.requested_hotels.filter(Boolean) : [];
  const areas = Array.isArray(parsed.requested_areas) ? parsed.requested_areas.filter(Boolean) : [];
  const queryPlan = parsed?.query_plan || result?.query_plan || {};
  return [
    { label: "范围", value: queryPlan.query_object_label || hotels[0] || areas[0] || "当前管理范围" },
    { label: "时间", value: formatTimeScopeLabel(parsed.time_scope) },
    { label: "指标", value: getMetricLabel(result) },
    { label: "模式", value: queryPlan.analysis_mode || parsed.compare_mode || "系统默认" },
  ];
}

function formatBenchmarkScope(scope: any) {
  if (!scope || typeof scope !== "object") return "当前范围";
  return ["area", "brand", "brand_child", "brand_level", "city_level"]
    .map((key) => String(scope[key] || "").trim())
    .filter(Boolean)
    .join(" / ") || "当前范围";
}

function InternalBenchmarkCard({ benchmark }: { benchmark: any }) {
  if (!benchmark || typeof benchmark !== "object") return null;
  const peerCount = Number(benchmark.peer_count || 0);
  const peerAvg = benchmark.peer_avg || {};
  const current = benchmark.current || {};
  if (!peerCount) return null;
  return (
    <div className="result-block benchmark-card" data-testid="internal-benchmark-card">
      <div className="result-block-title">内部经营对标</div>
      <div className="benchmark-head">
        <div className="benchmark-summary">
          当前采用 <strong>{benchmark.scope_used || "当前同口径样本"}</strong>，样本 <strong>{peerCount}</strong> 家，不含本店。
        </div>
        <span className="meta-pill">{formatBenchmarkScope(benchmark.scope)}</span>
      </div>
      <div className="benchmark-grid">
        <div className="benchmark-metric">
          <span>总收入</span>
          <strong>{formatNumber(current.total_income)}</strong>
          <em>同口径均值 {formatNumber(peerAvg.total_income)}</em>
        </div>
        <div className="benchmark-metric">
          <span>RevPAR</span>
          <strong>{formatNumber(current.revpar)}</strong>
          <em>同口径均值 {formatNumber(peerAvg.revpar)}</em>
        </div>
        <div className="benchmark-metric">
          <span>经营利润</span>
          <strong>{formatNumber(current.operating_profit)}</strong>
          <em>同口径均值 {formatNumber(peerAvg.operating_profit)}</em>
        </div>
        <div className="benchmark-metric">
          <span>利润率 / 成本率</span>
          <strong>{formatPercent(current.profit_margin)} / {formatPercent(current.cost_rate)}</strong>
          <em>同口径均值 {formatPercent(peerAvg.profit_margin)} / {formatPercent(peerAvg.cost_rate)}</em>
        </div>
      </div>
    </div>
  );
}

function ExternalBenchmarkCard({ benchmark }: { benchmark: any }) {
  if (!benchmark || typeof benchmark !== "object") return null;
  const status = String(benchmark.status || "").trim();
  if (!status) return null;
  return (
    <div className="result-block benchmark-card external-benchmark-card" data-testid="external-benchmark-card">
      <div className="result-block-title">外部行业对标</div>
      <div className="benchmark-head">
        <div className="benchmark-summary">
          {benchmark.message || "当前未拉取外部行业样本。"}
        </div>
        {benchmark.provider ? <span className="meta-pill">Provider：{benchmark.provider}</span> : null}
      </div>
      {Array.isArray(benchmark.dimensions) && benchmark.dimensions.length ? (
        <div className="chip-list compact-chip-list">
          {benchmark.dimensions.map((item: string) => (
            <span className="info-chip" key={item}>{item}</span>
          ))}
        </div>
      ) : null}
      {Array.isArray(benchmark.disclaimers) && benchmark.disclaimers.length ? (
        <div className="mobile-section-list">
          {benchmark.disclaimers.map((item: string, index: number) => (
            <div className="mobile-section-card subtle-card" key={`${item}-${index}`}>
              <div className="mobile-section-content">{item}</div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function LoadingCard({ frame, step }: { frame: QuestionFrame | null; step: number }) {
  const items = frame
    ? [
        { label: "范围", value: frame.scope },
        { label: "时间", value: frame.period },
        { label: "指标", value: frame.metric },
        { label: "模式", value: frame.mode },
      ]
    : [];
  return (
    <div className="loading-card" data-testid="loading-card">
      <div className="loading-head">
        <div>
          <div className="result-kicker">正在处理</div>
          <div className="loading-title">先帮你确认口径，再读取经营数据。</div>
        </div>
        {frame?.usedContext ? <span className="source-pill">已承接上文</span> : null}
      </div>
      {items.length ? (
        <div className="intent-strip" data-testid="loading-intent-strip">
          {items.map((item) => (
            <div className="intent-chip" key={item.label}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>
      ) : null}
      <div className="progress-steps">
        {LOADING_STEPS.map((item, index) => (
          <div className={`progress-step ${index < step ? "done" : ""} ${index === step ? "active" : ""}`} key={item}>
            <span className="progress-dot" />
            <span>{item}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function isFollowUpQuestion(input: string) {
  return /^(继续|展开|深挖|只看|改成|换成|聚焦|那华南区|那单店|原因呢|细一点|给我|看|生成)/.test(input.trim());
}

function resolveActionMode(input: string, selectedMode: ActionMode) {
  const trimmed = input.trim();
  if (/生成.*(摘要|报告)|输出.*(摘要|报告)|换成.*摘要|改成.*摘要/.test(trimmed)) {
    return "report";
  }
  return selectedMode;
}

function rewriteFollowUpQuestion(input: string, context: ConversationContext) {
  const trimmed = input.trim();
  const lastQuestion = context.lastQuestion;
  if (!trimmed || !lastQuestion || !isFollowUpQuestion(trimmed)) {
    return { rewritten: trimmed, usedContext: false };
  }

  if (
    trimmed.includes("继续展开原因") ||
    trimmed.includes("展开原因") ||
    trimmed.includes("原因呢") ||
    trimmed.includes("深挖") ||
    trimmed.includes("继续分析")
  ) {
    const focus = context.lastHotel || context.lastArea || context.lastMetric || "上一个问题";
    return {
      rewritten: `基于“${lastQuestion}”，继续展开${focus}的原因，并给出更具体的驱动因素和管理建议。`,
      usedContext: true
    };
  }

  const regionMatch = trimmed.match(/华南区|华东区|华北区|西南区|华中区|东北区|西北区/);
  if (trimmed.includes("只看") && regionMatch) {
    return {
      rewritten: `基于“${lastQuestion}”，范围只看${regionMatch[0]}。`,
      usedContext: true
    };
  }

  if (trimmed.includes("只看") && context.lastHotel) {
    return {
      rewritten: `基于“${lastQuestion}”，范围只看${context.lastHotel}。`,
      usedContext: true
    };
  }

  if (trimmed.includes("只看单店")) {
    return {
      rewritten: `基于“${lastQuestion}”，范围只看单店，并突出单店经营结论。`,
      usedContext: true
    };
  }

  if (trimmed.includes("换成经营摘要") || trimmed.includes("改成经营摘要") || trimmed.includes("换成摘要")) {
    return {
      rewritten: `基于“${lastQuestion}”，改为输出经营摘要。`,
      usedContext: true
    };
  }

  if (trimmed.includes("生成") && trimmed.includes("摘要")) {
    const scope = regionMatch?.[0] || context.lastArea || context.lastHotel || "当前范围";
    return {
      rewritten: `基于“${lastQuestion}”，生成${scope}经营摘要。`,
      usedContext: true
    };
  }

  if (trimmed.includes("给我") && trimmed.includes("建议")) {
    const focus = context.lastMetric || context.lastHotel || "当前经营问题";
    return {
      rewritten: `基于“${lastQuestion}”，请给出${focus}的管理建议和优先动作。`,
      usedContext: true
    };
  }

  if (trimmed.includes("同比")) {
    const focus = context.lastMetric || "当前指标";
    const scope = context.lastArea || context.lastHotel || "当前范围";
    return {
      rewritten: `基于“${lastQuestion}”，看${scope}${focus}的同比变化。`,
      usedContext: true
    };
  }

  return {
    rewritten: `基于“${lastQuestion}”，${trimmed}`,
    usedContext: true
  };
}

function ResultCard({
  result,
  onFollowUp,
  disabled = false,
  suggestions = BASE_FOLLOW_UP_SUGGESTIONS
}: {
  result: any;
  onFollowUp: (value: string) => void;
  disabled?: boolean;
  suggestions?: string[];
}) {
  const highlights = getHighlights(result);
  const sections = getPrimarySections(result);
  const executiveLine = getExecutiveSummaryLine(result);
  const finalSuggestions = result?.interaction_mode === "clarification" ? getClarificationSuggestions(result) : suggestions;
  const firstPoint = Array.isArray(result?.data_points) && result.data_points.length ? result.data_points[0] : null;
  const performanceLabel = getPerformanceLabel(result);
  const recognizedScopeItems = getRecognizedScopeItems(result);
  return (
    <div className="result-card" data-testid="result-card">
      <div className="assistant-card-head">
        <div>
          <div className="result-kicker">经营分析</div>
          <div className="result-summary" data-testid="result-summary">{getResultSummary(result)}</div>
        </div>
        <span className="source-pill">{getDataSourceLabel(result)}</span>
      </div>

      {firstPoint ? (
        <div className="metric-strip" data-testid="primary-metric-strip">
          <div className="metric-tile">
            <span>酒店</span>
            <strong>{firstPoint.hotel_name || "当前范围"}</strong>
          </div>
          <div className="metric-tile">
            <span>实际</span>
            <strong>{formatNumber(firstPoint.actual_value)}</strong>
          </div>
          <div className="metric-tile">
            <span>差额</span>
            <strong>{formatNumber(firstPoint.diff_value)}</strong>
          </div>
          <div className="metric-tile">
            <span>差异率</span>
            <strong>{formatPercent(firstPoint.diff_rate)}</strong>
          </div>
        </div>
      ) : null}

      {executiveLine ? (
        <div className="result-block" data-testid="executive-overview">
          <div className="result-block-title">管理层速览</div>
          <div className="executive-line">{executiveLine}</div>
        </div>
      ) : null}

      <div className="result-meta">
        <span className="meta-pill">指标：{getMetricLabel(result)}</span>
        {result?.data_points ? <span className="meta-pill">样本：{result.data_points.length} 条</span> : null}
        {result?.data_source?.warehouse_manifest?.latest_month ? <span className="meta-pill">最新账期：{result.data_source.warehouse_manifest.latest_month}</span> : null}
        {result?.parsed_intent?.compare_mode ? <span className="meta-pill">口径：{result.parsed_intent.compare_mode}</span> : null}
      </div>

      <div className="intent-strip" data-testid="recognized-scope">
        {recognizedScopeItems.map((item) => (
          <div className="intent-chip" key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>

      <InternalBenchmarkCard benchmark={result?.internal_benchmark} />
      <ExternalBenchmarkCard benchmark={result?.external_benchmark} />

      {Array.isArray(result?.data_points) && result.data_points.length ? (
        <div className="result-block" data-testid="top-data-points">
          <div className="result-block-title">关键数据</div>
          <div className="mobile-section-list">
            {result.data_points.slice(0, 5).map((item: any, index: number) => (
              <div className="mobile-section-card" key={`${item.hotel_name}-${index}`}>
                <div className="mobile-section-title">{index + 1}. {item.hotel_name || "未知酒店"}</div>
                <div className="mobile-section-content">
                  实际 {formatNumber(item.actual_value)}，对比 {formatNumber(item.compare_value)}，差额 {formatNumber(item.diff_value)}，差异率 {formatPercent(item.diff_rate)}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {highlights.length ? (
        <div className="result-block" data-testid="risk-highlights">
          <div className="result-block-title">经营观察</div>
          <div className="chip-list">
            {highlights.map((item: string, index: number) => (
              <span className="info-chip" key={`${item}-${index}`}>
                {item}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {sections.length ? (
        <div className="mobile-section-list" data-testid="executive-sections">
          {sections.map((section: any, index: number) => (
            <div className="mobile-section-card" key={`${section.title}-${index}`} data-testid={`section-${section.title}`}>
              <div className="mobile-section-title">{section.title}</div>
              <div className="mobile-section-content">{section.content}</div>
            </div>
          ))}
        </div>
      ) : null}

      {result?.trace_id || result?.parsed_intent ? (
        <details className="details-card diagnostic-card" data-testid="details-diagnostics">
          <summary>技术诊断信息</summary>
          <div className="result-meta diagnostic-meta">
            {result?.trace_id ? <span className="meta-pill">Trace：{result.trace_id}</span> : null}
            <span className="meta-pill">意图：{getIntentLabel(result)}</span>
            <span className="meta-pill">来源：{getDataSourceLabel(result)}</span>
            {performanceLabel ? <span className="meta-pill">耗时：{performanceLabel}</span> : null}
          </div>
          {result?.performance ? <pre className="pre diagnostic-pre">{formatJson(result.performance)}</pre> : null}
        </details>
      ) : null}

      {result?.report_markdown ? (
        <details className="details-card" data-testid="details-report-markdown">
          <summary>查看报告 Markdown</summary>
          <pre className="pre">{String(result.report_markdown)}</pre>
        </details>
      ) : null}

      {result?.data_points ? (
        <details className="details-card" data-testid="details-data-points">
          <summary>查看结构化数据</summary>
          <pre className="pre">{formatJson(result.data_points)}</pre>
        </details>
      ) : null}

      {result?.sql_plan ? (
        <details className="details-card" data-testid="details-sql-plan">
          <summary>查看 SQL 计划</summary>
          <pre className="pre">{formatJson(result.sql_plan)}</pre>
        </details>
      ) : null}

      {result?.auth_scope ? (
        <details className="details-card" data-testid="details-auth-scope">
          <summary>查看权限范围</summary>
          <pre className="pre">{formatJson(result.auth_scope)}</pre>
        </details>
      ) : null}

      {Array.isArray(result?.warnings) && result.warnings.length ? (
        <details className="details-card" data-testid="details-warnings">
          <summary>查看系统提示</summary>
          <pre className="pre">{formatJson(result.warnings)}</pre>
        </details>
      ) : null}

      <div className="result-block" data-testid="follow-up-actions">
        <div className="result-block-title">你可以继续问</div>
        <div className="chip-list">
          {finalSuggestions.map((item, index) => (
            <button
              type="button"
              className="chip"
              key={item}
              disabled={disabled}
              onClick={() => onFollowUp(item)}
              data-testid={`follow-up-${index}`}
            >
              {item}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [timeScope, setTimeScope] = useState(DEFAULT_TIME_SCOPE);
  const [role, setRole] = useState<Role>(DEFAULT_ROLE);
  const [actionMode, setActionMode] = useState<ActionMode>("query");
  const [externalBenchmark, setExternalBenchmark] = useState(false);
  const [status, setStatus] = useState<QueryStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [conversationContext, setConversationContext] = useState<ConversationContext>({
    lastQuestion: null,
    lastMetric: null,
    lastHotel: null,
    lastArea: null,
    lastSummary: null
  });
  const [contextHint, setContextHint] = useState<string | null>(null);
  const [activeFrame, setActiveFrame] = useState<QuestionFrame | null>(null);
  const [loadingStep, setLoadingStep] = useState(0);
  const [systemSettings, setSystemSettings] = useState<SystemSettings | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 1,
      sender: "assistant",
      kind: "text",
      text: "请输入一个经营问题，我会直接返回分析结论；如果你切到“报告”，我会生成可复用的经营摘要。"
    }
  ]);
  const requestIdRef = useRef(1);

  const isLoading = status === "loading";
  const quickQuestions = systemSettings?.quick_questions?.length ? systemSettings.quick_questions : FALLBACK_QUICK_QUESTIONS;

  useEffect(() => {
    let active = true;
    fetchSystemSettings()
      .then((settings) => {
        if (!active) return;
        setSystemSettings(settings as SystemSettings);
        setSettingsError(null);
      })
      .catch((err) => {
        if (!active) return;
        setSettingsError(err instanceof Error ? err.message : "系统设置读取失败");
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!isLoading) {
      setLoadingStep(0);
      return;
    }
    const timer = window.setInterval(() => {
      setLoadingStep((current) => Math.min(current + 1, LOADING_STEPS.length - 1));
    }, 700);
    return () => window.clearInterval(timer);
  }, [isLoading]);

  const placeholder = useMemo(() => {
    if (contextHint) return contextHint;
    return actionMode === "report" ? "例如：生成华南区本月经营摘要" : "例如：为什么某酒店经营利润低于预算？";
  }, [actionMode, contextHint]);

  async function run(nextQuestion?: string, options?: { useContextRewrite?: boolean }) {
    const rawQuestion = (nextQuestion ?? question).trim();
    if (!rawQuestion) return;

    const rewritten = options?.useContextRewrite === false ? { rewritten: rawQuestion, usedContext: false } : rewriteFollowUpQuestion(rawQuestion, conversationContext);
    const finalQuestion = rewritten.rewritten;
    const effectiveMode = resolveActionMode(finalQuestion, actionMode);

    const currentRequestId = ++requestIdRef.current;
    const userMessage: Message = {
      id: currentRequestId * 2,
      sender: "user",
      kind: "text",
      text: rawQuestion,
      originalQuestion: finalQuestion
    };

    setMessages((current) => [...current, userMessage]);
    setStatus("loading");
    setLoadingStep(0);
    setActiveFrame(inferQuestionFrame(finalQuestion, timeScope, effectiveMode, rewritten.usedContext));
    setError(null);
    if (nextQuestion) setQuestion(nextQuestion);
    setContextHint(null);

    try {
      const payload = {
        question: finalQuestion,
        context: { time_scope: timeScope, language: "zh-CN", external_benchmark: externalBenchmark },
        auth: { user_id: "u001", role }
      };
      const result = effectiveMode === "report" ? await submitReport(payload) : await submitQuery(payload);

      if (currentRequestId !== requestIdRef.current) return;

      setMessages((current) => [
        ...current,
        {
          id: currentRequestId * 2 + 1,
          sender: "assistant",
          kind: "result",
          text: getResultSummary(result),
          payload: result,
          originalQuestion: finalQuestion
        }
      ]);
      setStatus("success");
      setQuestion("");
      setActiveFrame(null);
      setConversationContext(extractContext(result, finalQuestion));
    } catch (err) {
      if (currentRequestId !== requestIdRef.current) return;

      const message = err instanceof Error ? err.message : "请求失败，请稍后重试。";
      setError(message);
      setActiveFrame(null);
      setMessages((current) => [
        ...current,
        {
          id: currentRequestId * 2 + 1,
          sender: "assistant",
          kind: "text",
          text: `这次没有成功返回结果：${message}`,
          originalQuestion: finalQuestion
        }
      ]);
      setStatus("error");
    }
  }

  function handleFollowUp(value: string) {
    setQuestion(value);
    const rewritten = rewriteFollowUpQuestion(value, conversationContext);
    if (rewritten.usedContext) {
      setContextHint(`将自动理解为：${rewritten.rewritten}`);
    } else {
      setContextHint(null);
    }
    void run(value);
  }

  return (
    <div className="chat-page">
      <div className="chat-shell">
        <header className="chat-header">
          <div>
            <div className="eyebrow">MANAGEMENT COPILOT</div>
            <h1>酒店经营 AI 助手</h1>
            <p>像和经营分析师对话一样提问。默认只展示管理层需要看的经营拆解，技术细节已收进诊断区。</p>
          </div>
          <div className={`status-badge status-${status}`}>{status === "idle" ? "待输入" : status === "loading" ? "处理中" : status === "success" ? "已返回" : "有异常"}</div>
        </header>

        <div className="quick-strip">
          <QuickQuestions onSelect={(q) => void run(q, { useContextRewrite: false })} activeQuestion={question} disabled={isLoading} questions={quickQuestions} />
        </div>

        <main className="chat-thread">
          {messages.map((message) => (
            <div className={`message-row ${message.sender}`} key={message.id}>
              <div className={`message-bubble ${message.sender}`}>
                {message.kind === "result" ? (
                  <ResultCard
                    result={message.payload}
                    onFollowUp={handleFollowUp}
                    disabled={isLoading}
                    suggestions={getFollowUpSuggestions(conversationContext)}
                  />
                ) : (
                  <div className="message-text">
                    {message.text}
                    {message.originalQuestion && message.originalQuestion !== message.text ? (
                      <div className="context-note">已按上下文理解为：{message.originalQuestion}</div>
                    ) : null}
                  </div>
                )}
              </div>
            </div>
          ))}

          {isLoading ? (
            <div className="message-row assistant">
              <div className="message-bubble assistant" data-testid="typing-bubble">
                <LoadingCard frame={activeFrame} step={loadingStep} />
              </div>
            </div>
          ) : null}
        </main>

        <footer className="composer-shell">
          <details className="advanced-panel" data-testid="advanced-panel">
            <summary>高级设置与调优观察</summary>
            <div className="advanced-grid">
              <label className="field">
                <span className="field-label">输出模式</span>
                <select className="input" value={actionMode} onChange={(e) => setActionMode(e.target.value as ActionMode)} data-testid="action-mode-select">
                  {ACTION_OPTIONS.map((option) => (
                    <option value={option.value} key={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span className="field-label">时间范围</span>
                <input className="input" value={timeScope} onChange={(e) => setTimeScope(e.target.value)} data-testid="time-scope-input" />
              </label>

              <label className="field">
                <span className="field-label">访问角色</span>
                <select className="input" value={role} onChange={(e) => setRole(e.target.value as Role)} data-testid="role-select">
                  {ROLE_OPTIONS.map((option) => (
                    <option value={option.value} key={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span className="field-label">外部行业对标</span>
                <button
                  type="button"
                  className={`toggle-btn ${externalBenchmark ? "active" : ""}`}
                  onClick={() => setExternalBenchmark((current) => !current)}
                  data-testid="external-benchmark-toggle"
                >
                  {externalBenchmark ? "已开启" : "未开启"}
                </button>
              </label>
            </div>

            <div className="system-config-panel" data-testid="system-config-panel">
              <div className="system-config-card">
                <div className="result-block-title">模型配置</div>
                <div className="mobile-section-content">{getRuntimeModelLine(systemSettings)}</div>
                <div className="context-note">快模型负责语义解析和参数补全；深度模型负责经营解释和管理层表达。</div>
                <div className="context-note">外部行业对标默认关闭；开启后表示你接受系统后续联网补充外部样本，但其准确性和时效性仍需人工评估。</div>
              </div>

              {Array.isArray(systemSettings?.tuning_stages) && systemSettings.tuning_stages.length ? (
                <div className="system-config-card">
                  <div className="result-block-title">分阶段调优</div>
                  <div className="tuning-stage-list">
                    {systemSettings.tuning_stages.map((stage, index) => (
                      <div className="tuning-stage" key={`${stage.name}-${index}`}>
                        <div className="tuning-stage-title">{index + 1}. {stage.name}</div>
                        <div className="context-note">观察：{stage.observable}</div>
                        <div className="context-note">达标：{stage.success_criteria}</div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              {systemSettings?.answer_templates ? (
                <details className="details-card compact-details" data-testid="answer-template-settings">
                  <summary>查看回答模板配置</summary>
                  <pre className="pre">{formatJson(systemSettings.answer_templates)}</pre>
                </details>
              ) : null}

              {settingsError ? <div className="composer-error">系统设置读取失败：{settingsError}</div> : null}
            </div>
          </details>

          <div className="composer">
            <textarea
              className="composer-input"
              rows={1}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={placeholder}
              data-testid="composer-input"
            />
            <button className="composer-btn" onClick={() => void run()} disabled={isLoading || !question.trim()} data-testid="composer-send">
              {actionMode === "report" ? "生成报告" : "发送"}
            </button>
          </div>

          <div className="mobile-hint">建议直接输入“本月经营情况怎样”“生成本月经营摘要”这类自然语言问题。</div>
          {contextHint ? <div className="context-note composer-note" data-testid="context-hint">{contextHint}</div> : null}

          {error ? <div className="composer-error" data-testid="composer-error">{error}</div> : null}
        </footer>
      </div>
    </div>
  );
}
