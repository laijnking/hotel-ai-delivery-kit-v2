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
  lastTimeScope: string | null;
  lastScopeLabel: string | null;
  lastCompareMode: string | null;
  lastSummary: string | null;
};

type Conversation = {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: Message[];
  context: ConversationContext;
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

type AnalysisFocus = "driver_analysis" | "management_report" | "yoy_change" | "income_structure" | "profit_cost_efficiency" | null;

const ROLE_OPTIONS: Array<{ value: Role; label: string }> = [
  { value: "GROUP_ADMIN", label: "集团管理层" },
  { value: "AREA_MANAGER", label: "区域经理" },
  { value: "HOTEL_MANAGER", label: "单店经理" }
];

const ACTION_OPTIONS: Array<{ value: ActionMode; label: string }> = [
  { value: "query", label: "问答" },
  { value: "report", label: "报告" }
];

const DEFAULT_QUESTION = "本月哪些酒店经营利润未达预算？";
const DEFAULT_ROLE: Role = "GROUP_ADMIN";
const ROLE_STORAGE_KEY = "hotel-ai-role";
const BASE_FOLLOW_UP_SUGGESTIONS = ["继续展开原因", "换成经营摘要", "看同比变化", "分析收入结构", "看利润和成本效率"];
const FALLBACK_QUICK_QUESTIONS = [
  "本月哪些酒店经营利润未达预算？",
  "广州丽思卡尔顿酒店3月的收入情况怎么样？",
  "看一下江门嘉华酒店3月的经营情况",
  "本月总收入同比如何？",
  "生成华南区本月经营摘要"
];
const LOADING_STEPS = ["已理解问题", "读取经营数据", "生成经营拆解", "准备追问建议"];
const CONVERSATION_STORAGE_KEY = "hotel-ai-conversations";
const ACTIVE_CONVERSATION_STORAGE_KEY = "hotel-ai-active-conversation";
const EMPTY_CONTEXT: ConversationContext = {
  lastQuestion: null,
  lastMetric: null,
  lastHotel: null,
  lastArea: null,
  lastTimeScope: null,
  lastScopeLabel: null,
  lastCompareMode: null,
  lastSummary: null
};
const WELCOME_MESSAGE_TEXT = "请输入一个经营问题，我会直接返回分析结论；如果你切到“报告”，我会生成可复用的经营摘要。";

function createWelcomeMessage(): Message {
  return {
    id: 1,
    sender: "assistant",
    kind: "text",
    text: WELCOME_MESSAGE_TEXT
  };
}

function getPreviousMonthScope(now = new Date()) {
  const previousMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const year = previousMonth.getFullYear();
  const month = String(previousMonth.getMonth() + 1).padStart(2, "0");
  return `${year}${month}`;
}

function isRole(value: string | null): value is Role {
  return value === "GROUP_ADMIN" || value === "AREA_MANAGER" || value === "HOTEL_MANAGER";
}

function getInitialRole(): Role {
  if (typeof window === "undefined") return DEFAULT_ROLE;
  const roleFromUrl = new URLSearchParams(window.location.search).get("role");
  if (isRole(roleFromUrl)) {
    window.localStorage.setItem(ROLE_STORAGE_KEY, roleFromUrl);
    return roleFromUrl;
  }
  const storedRole = window.localStorage.getItem(ROLE_STORAGE_KEY);
  return isRole(storedRole) ? storedRole : DEFAULT_ROLE;
}

function createConversation(seed?: Partial<Conversation>): Conversation {
  const now = Date.now();
  return {
    id: seed?.id || `conversation-${now}-${Math.random().toString(16).slice(2)}`,
    title: seed?.title || "新会话",
    createdAt: seed?.createdAt || now,
    updatedAt: seed?.updatedAt || now,
    messages: seed?.messages?.length ? seed.messages : [createWelcomeMessage()],
    context: { ...EMPTY_CONTEXT, ...(seed?.context || {}) }
  };
}

function getConversationTitleFromQuestion(value: string) {
  const title = value.replace(/\s+/g, " ").trim();
  if (!title) return "新会话";
  return title.length > 22 ? `${title.slice(0, 22)}...` : title;
}

function getConversationMeta(conversation: Conversation) {
  const context = conversation.context;
  const pieces = [
    context.lastScopeLabel || context.lastHotel || context.lastArea,
    context.lastTimeScope ? formatTimeScopeLabel(context.lastTimeScope) : null,
    context.lastMetric
  ].filter(Boolean);
  return pieces.length ? pieces.join(" · ") : "等待经营问题";
}

function getContextSnapshotItems(context: ConversationContext) {
  return [
    context.lastScopeLabel || context.lastHotel || context.lastArea ? `范围：${context.lastScopeLabel || context.lastHotel || context.lastArea}` : null,
    context.lastTimeScope ? `时间：${formatTimeScopeLabel(context.lastTimeScope)}` : null,
    context.lastMetric ? `指标：${context.lastMetric}` : null,
    context.lastCompareMode ? `口径：${getAnalysisModeLabel(context.lastCompareMode)}` : null
  ].filter(Boolean) as string[];
}

function restoreConversations(): Conversation[] {
  if (typeof window === "undefined") return [createConversation()];
  try {
    const raw = window.localStorage.getItem(CONVERSATION_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    if (!Array.isArray(parsed) || !parsed.length) return [createConversation()];
    return parsed
      .filter((item) => item && typeof item === "object")
      .map((item) =>
        createConversation({
          id: String(item.id || ""),
          title: String(item.title || "新会话"),
          createdAt: Number(item.createdAt) || Date.now(),
          updatedAt: Number(item.updatedAt) || Date.now(),
          messages: Array.isArray(item.messages) && item.messages.length ? item.messages : [createWelcomeMessage()],
          context: item.context || EMPTY_CONTEXT
        })
      )
      .slice(0, 20);
  } catch {
    return [createConversation()];
  }
}

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

function hasDetailedSections(result: any) {
  return getPrimarySections(result).length > 0;
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
  const parsed = result?.parsed_intent || result?.source_query?.parsed_intent || {};
  const queryPlan = parsed?.query_plan || result?.query_plan || {};
  const firstPoint = Array.isArray(result?.data_points) && result.data_points.length ? result.data_points[0] : null;
  const firstSection = Array.isArray(result?.report_sections) && result.report_sections.length ? result.report_sections[0] : null;
  const metric =
    result?.metric_definition?.name_cn ||
    parsed?.metric_code ||
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
    lastTimeScope: parsed?.time_scope || null,
    lastScopeLabel: queryPlan?.query_object_label || hotel || area || null,
    lastCompareMode: queryPlan?.analysis_mode || parsed?.compare_mode || null,
    lastSummary: String(firstSection?.content || summary || "")
  };
}

function getFollowUpSuggestions(_context: ConversationContext) {
  return BASE_FOLLOW_UP_SUGGESTIONS;
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
    { label: "模式", value: getAnalysisModeLabel(queryPlan.analysis_mode || parsed.compare_mode || "系统默认") },
  ];
}

function getAnalysisModeLabel(value: unknown) {
  const text = String(value || "");
  if (text === "portfolio_overview") return "组合总览";
  if (text === "hotel_metric_snapshot") return "单点快照";
  if (text === "management_report") return "管理摘要";
  if (text === "driver_analysis") return "归因分析";
  if (text === "ranking_overview") return "排名概览";
  return text || "系统默认";
}

function getDisplayRows(result: any) {
  if (Array.isArray(result?.portfolio_breakdown) && result.portfolio_breakdown.length) {
    return result.portfolio_breakdown;
  }
  return Array.isArray(result?.data_points) ? result.data_points : [];
}

function getPortfolioMemberCount(result: any) {
  const directCount = result?.portfolio_member_count;
  if (typeof directCount === "number" && !Number.isNaN(directCount)) return directCount;
  const firstPoint = Array.isArray(result?.data_points) && result.data_points.length ? result.data_points[0] : null;
  if (typeof firstPoint?.portfolio_member_count === "number" && !Number.isNaN(firstPoint.portfolio_member_count)) {
    return firstPoint.portfolio_member_count;
  }
  const plannedCount = result?.parsed_intent?.query_plan?.resolved_hotel_count;
  if (typeof plannedCount === "number" && !Number.isNaN(plannedCount)) return plannedCount;
  return null;
}

function getPortfolioOutlierItems(result: any) {
  const outliers = result?.portfolio_outliers;
  if (!outliers || typeof outliers !== "object") return [];
  const buckets = [
    {
      key: "income",
      title: "收入拉动",
      leadLabel: "拉动较强",
      lagLabel: "拖累较明显",
      format: (item: any) => `差额 ${formatNumber(item?.diff_value)}`
    },
    {
      key: "profit",
      title: "利润表现",
      leadLabel: "表现较强",
      lagLabel: "承压较明显",
      format: (item: any) => `经营利润 ${formatNumber(item?.operating_profit_actual)}`
    },
    {
      key: "cost",
      title: "成本效率",
      leadLabel: "成本较低",
      lagLabel: "人工成本偏高",
      format: (item: any) => `人工成本 ${formatNumber(item?.people_cost_actual)}`
    }
  ];
  return buckets
    .map((bucket) => {
      const source = outliers?.[bucket.key];
      if (!source || typeof source !== "object") return null;
      const best = source.best && typeof source.best === "object" ? source.best : null;
      const worst = source.worst && typeof source.worst === "object" ? source.worst : null;
      if (!best && !worst) return null;
      return {
        title: bucket.title,
        best: best?.hotel_name ? `${bucket.leadLabel}：${best.hotel_name}，${bucket.format(best)}` : null,
        worst: worst?.hotel_name ? `${bucket.lagLabel}：${worst.hotel_name}，${bucket.format(worst)}` : null,
      };
    })
    .filter(Boolean);
}

function shiftMonth(timeScope: string, offset: number) {
  if (!/^\d{6}$/.test(timeScope)) return null;
  const year = Number(timeScope.slice(0, 4));
  const month = Number(timeScope.slice(4, 6));
  const date = new Date(year, month - 1 + offset, 1);
  return `${date.getFullYear()}年${date.getMonth() + 1}月`;
}

function getQuickFilters(result: any) {
  if (Array.isArray(result?.quick_filters) && result.quick_filters.length) {
    return result.quick_filters;
  }
  const parsed = result?.parsed_intent || {};
  const rows = getDisplayRows(result);
  const currentTimeScope = String(parsed?.time_scope || "");
  const queryPlan = parsed?.query_plan || {};
  const areas = Array.from(
    new Set(
      [
        ...(Array.isArray(parsed?.requested_areas) ? parsed.requested_areas : []),
        ...rows.map((item: any) => String(item?.area || "").trim()).filter(Boolean),
      ],
    ),
  ).slice(0, 3);
  const hotels = Array.from(
    new Set(
      rows
        .map((item: any) => String(item?.hotel_name || "").trim())
        .filter((item: string) => item && item !== String(result?.parsed_intent?.query_plan?.query_object_label || "").trim()),
    ),
  ).slice(0, 3);
  const brands = Array.from(
    new Set(
      [
        ...(Array.isArray(parsed?.requested_brand_children) ? parsed.requested_brand_children : []),
        ...rows.map((item: any) => String(item?.brand_child || "").trim()).filter(Boolean),
      ],
    ),
  ).slice(0, 3);
  const months = [shiftMonth(currentTimeScope, -1), formatTimeScopeLabel(currentTimeScope), shiftMonth(currentTimeScope, 1)].filter(Boolean) as string[];
  const compareOptions = [
    { label: "预算对比", prompt: "切换成预算对比", active: parsed?.compare_mode === "budget" },
    { label: "同比变化", prompt: "切换成同比变化", active: parsed?.compare_mode === "yoy" },
    { label: "实际表现", prompt: "切换成实际表现", active: parsed?.compare_mode === "actual" },
  ].filter((item) => !item.active).slice(0, 2);
  const modeOptions = [
    { label: "组合总览", prompt: "改看组合总览", active: queryPlan?.analysis_mode === "portfolio_overview" },
    { label: "归因分析", prompt: "继续展开原因", active: queryPlan?.analysis_mode === "driver_analysis" },
    { label: "经营摘要", prompt: "换成经营摘要", active: queryPlan?.analysis_mode === "management_report" },
  ].filter((item) => !item.active).slice(0, 2);
  return [
    {
      label: "区域",
      items: areas.map((item) => ({ label: item, prompt: `只看${item}` })),
    },
    {
      label: "酒店",
      items: hotels.map((item) => ({ label: item, prompt: `只看${item}` })),
    },
    {
      label: "月份",
      items: months.map((item) => ({ label: item, prompt: `切到${item}` })),
    },
    {
      label: "品牌",
      items: brands.map((item) => ({ label: item, prompt: `只看${item}品牌` })),
    },
    {
      label: "口径",
      items: compareOptions.map(({ label, prompt }) => ({ label, prompt })),
    },
    {
      label: "分析方式",
      items: modeOptions.map(({ label, prompt }) => ({ label, prompt })),
    },
  ].filter((group) => group.items.length);
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

function inferAnalysisFocus(input: string, mode: ActionMode): AnalysisFocus {
  const text = input.trim();
  if (mode === "report" || /生成.*(摘要|报告)|输出.*(摘要|报告)|换成.*摘要|改成.*摘要/.test(text)) {
    return "management_report";
  }
  if (/原因|为什么|归因|继续展开/.test(text)) {
    return "driver_analysis";
  }
  if (/同比/.test(text)) {
    return "yoy_change";
  }
  if (/收入结构|收入质量|客房收入|餐饮|宴会/.test(text)) {
    return "income_structure";
  }
  if (/利润.*成本|成本.*利润|成本效率|利润质量|人工|能耗|能源|费用率/.test(text)) {
    return "profit_cost_efficiency";
  }
  return null;
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
  const monthMatch = trimmed.match(/(20\d{2})年\s*(1[0-2]|0?[1-9])月/);
  const scopedTarget = trimmed.startsWith("只看") ? trimmed.replace(/^只看/, "").trim() : "";
  if (trimmed.includes("只看") && regionMatch) {
    return {
      rewritten: `基于“${lastQuestion}”，范围只看${regionMatch[0]}。`,
      usedContext: true
    };
  }

  if (trimmed.includes("只看") && scopedTarget) {
    return {
      rewritten: `基于“${lastQuestion}”，范围只看${scopedTarget}。`,
      usedContext: true
    };
  }

  if ((trimmed.includes("切到") || trimmed.includes("改看") || trimmed.includes("看")) && monthMatch) {
    return {
      rewritten: `基于“${lastQuestion}”，时间切到${monthMatch[1]}年${Number(monthMatch[2])}月。`,
      usedContext: true
    };
  }

  if (trimmed.includes("品牌")) {
    const brandTarget = trimmed.replace(/^只看/, "").replace(/品牌/g, "").trim();
    if (brandTarget) {
      return {
        rewritten: `基于“${lastQuestion}”，范围只看${brandTarget}品牌。`,
        usedContext: true
      };
    }
  }

  if (trimmed.includes("预算对比")) {
    return {
      rewritten: `基于“${lastQuestion}”，切换成预算对比口径。`,
      usedContext: true
    };
  }

  if (trimmed.includes("同比变化")) {
    return {
      rewritten: `基于“${lastQuestion}”，切换成同比变化口径。`,
      usedContext: true
    };
  }

  if (trimmed.includes("实际表现")) {
    return {
      rewritten: `基于“${lastQuestion}”，切换成实际表现口径。`,
      usedContext: true
    };
  }

  if (trimmed.includes("组合总览")) {
    return {
      rewritten: `基于“${lastQuestion}”，改看组合总览。`,
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
  suggestions = BASE_FOLLOW_UP_SUGGESTIONS,
  showTechnicalDetails = false
}: {
  result: any;
  onFollowUp: (value: string) => void;
  disabled?: boolean;
  suggestions?: string[];
  showTechnicalDetails?: boolean;
}) {
  const highlights = getHighlights(result);
  const sections = getPrimarySections(result);
  const executiveLine = getExecutiveSummaryLine(result);
  const finalSuggestions = result?.interaction_mode === "clarification" ? getClarificationSuggestions(result) : suggestions;
  const displayRows = getDisplayRows(result);
  const firstPoint = displayRows.length ? displayRows[0] : null;
  const performanceLabel = getPerformanceLabel(result);
  const recognizedScopeItems = getRecognizedScopeItems(result);
  const portfolioSummaryPoint = Array.isArray(result?.data_points) && result.data_points.length ? result.data_points[0] : null;
  const isPortfolio = String(result?.parsed_intent?.query_plan?.query_grain || "") === "portfolio";
  const portfolioMemberCount = getPortfolioMemberCount(result);
  const portfolioOutlierItems = getPortfolioOutlierItems(result);
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
            <span>{isPortfolio ? "组合" : "酒店"}</span>
            <strong>{(isPortfolio ? portfolioSummaryPoint?.hotel_name : firstPoint.hotel_name) || "当前范围"}</strong>
          </div>
          <div className="metric-tile">
            <span>实际</span>
            <strong>{formatNumber((isPortfolio ? portfolioSummaryPoint?.actual_value : firstPoint.actual_value))}</strong>
          </div>
          <div className="metric-tile">
            <span>差额</span>
            <strong>{formatNumber((isPortfolio ? portfolioSummaryPoint?.diff_value : firstPoint.diff_value))}</strong>
          </div>
          <div className="metric-tile">
            <span>{isPortfolio ? "样本数" : "差异率"}</span>
            <strong>{isPortfolio ? formatNumber(portfolioMemberCount) : formatPercent(firstPoint.diff_rate)}</strong>
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

      {displayRows.length ? (
        <div className="result-block" data-testid="top-data-points">
          <div className="result-block-title">{isPortfolio ? "组合内重点酒店" : "关键数据"}</div>
          <div className="mobile-section-list">
            {displayRows.slice(0, 5).map((item: any, index: number) => (
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

      {portfolioOutlierItems.length ? (
        <div className="result-block" data-testid="portfolio-outliers">
          <div className="result-block-title">组合异常拆解</div>
          <div className="outlier-grid">
            {portfolioOutlierItems.map((item: any) => (
              <div className="outlier-card" key={item.title}>
                <div className="outlier-title">{item.title}</div>
                {item.best ? <div className="outlier-line positive">{item.best}</div> : null}
                {item.worst ? <div className="outlier-line negative">{item.worst}</div> : null}
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

      {showTechnicalDetails && hasDetailedSections(result) ? (
        <details className="details-card analysis-details-card" data-testid="details-analysis-sections">
          <summary>查看分析明细</summary>
          <div className="mobile-section-list">
            {sections.map((section: any, index: number) => (
              <div className="mobile-section-card" key={`${section.title}-${index}`} data-testid={`section-${section.title}`}>
                <div className="mobile-section-title">{section.title}</div>
                <div className="mobile-section-content">{section.content}</div>
              </div>
            ))}
          </div>
        </details>
      ) : null}

      {showTechnicalDetails && (result?.trace_id || result?.parsed_intent) ? (
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

      {showTechnicalDetails && result?.report_markdown ? (
        <details className="details-card" data-testid="details-report-markdown">
          <summary>查看报告 Markdown</summary>
          <pre className="pre">{String(result.report_markdown)}</pre>
        </details>
      ) : null}

      {showTechnicalDetails && result?.data_points ? (
        <details className="details-card" data-testid="details-data-points">
          <summary>查看结构化数据</summary>
          <pre className="pre">{formatJson(result.data_points)}</pre>
        </details>
      ) : null}

      {showTechnicalDetails && result?.sql_plan ? (
        <details className="details-card" data-testid="details-sql-plan">
          <summary>查看 SQL 计划</summary>
          <pre className="pre">{formatJson(result.sql_plan)}</pre>
        </details>
      ) : null}

      {showTechnicalDetails && result?.auth_scope ? (
        <details className="details-card" data-testid="details-auth-scope">
          <summary>查看权限范围</summary>
          <pre className="pre">{formatJson(result.auth_scope)}</pre>
        </details>
      ) : null}

      {showTechnicalDetails && Array.isArray(result?.warnings) && result.warnings.length ? (
        <details className="details-card" data-testid="details-warnings">
          <summary>查看系统提示</summary>
          <pre className="pre">{formatJson(result.warnings)}</pre>
        </details>
      ) : null}

      <details className="details-card follow-up-details-card" data-testid="follow-up-actions">
        <summary>你可以继续问</summary>
        <div className="result-block">
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
      </details>
    </div>
  );
}

export default function App() {
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [timeScope, setTimeScope] = useState(() => getPreviousMonthScope());
  const [role, setRole] = useState<Role>(() => getInitialRole());
  const [actionMode, setActionMode] = useState<ActionMode>("query");
  const [externalBenchmark, setExternalBenchmark] = useState(false);
  const [status, setStatus] = useState<QueryStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [contextHint, setContextHint] = useState<string | null>(null);
  const [activeFrame, setActiveFrame] = useState<QuestionFrame | null>(null);
  const [loadingStep, setLoadingStep] = useState(0);
  const [systemSettings, setSystemSettings] = useState<SystemSettings | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>(() => restoreConversations());
  const [activeConversationId, setActiveConversationId] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    return window.localStorage.getItem(ACTIVE_CONVERSATION_STORAGE_KEY) || "";
  });
  const requestIdRef = useRef(1);

  const isLoading = status === "loading";
  const showTechnicalDetails = role !== "GROUP_ADMIN";
  const quickQuestions = systemSettings?.quick_questions?.length ? systemSettings.quick_questions : FALLBACK_QUICK_QUESTIONS;
  const sortedConversations = useMemo(
    () => [...conversations].sort((a, b) => b.updatedAt - a.updatedAt),
    [conversations]
  );
  const activeConversation = useMemo(() => {
    return conversations.find((item) => item.id === activeConversationId) || sortedConversations[0] || createConversation();
  }, [activeConversationId, conversations, sortedConversations]);
  const messages = activeConversation.messages;
  const conversationContext = activeConversation.context || EMPTY_CONTEXT;
  const contextSnapshotItems = getContextSnapshotItems(conversationContext);

  useEffect(() => {
    if (conversations.some((item) => item.id === activeConversationId)) return;
    const fallbackId = sortedConversations[0]?.id;
    if (fallbackId) setActiveConversationId(fallbackId);
  }, [activeConversationId, conversations, sortedConversations]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(CONVERSATION_STORAGE_KEY, JSON.stringify(conversations.slice(0, 20)));
  }, [conversations]);

  useEffect(() => {
    if (typeof window === "undefined" || !activeConversationId) return;
    window.localStorage.setItem(ACTIVE_CONVERSATION_STORAGE_KEY, activeConversationId);
  }, [activeConversationId]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(ROLE_STORAGE_KEY, role);
  }, [role]);

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

  function updateConversationById(conversationId: string, updater: (conversation: Conversation) => Conversation) {
    setConversations((current) =>
      current.map((conversation) => (conversation.id === conversationId ? updater(conversation) : conversation))
    );
  }

  function createFreshConversation() {
    const conversation = createConversation();
    setConversations((current) => [conversation, ...current].slice(0, 20));
    setActiveConversationId(conversation.id);
    setQuestion("");
    setContextHint(null);
    setError(null);
    setActiveFrame(null);
    setStatus("idle");
  }

  function selectConversation(conversationId: string) {
    setActiveConversationId(conversationId);
    setQuestion("");
    setContextHint(null);
    setError(null);
    setActiveFrame(null);
    if (!isLoading) setStatus("idle");
  }

  async function run(nextQuestion?: string, options?: { useContextRewrite?: boolean }) {
    const rawQuestion = (nextQuestion ?? question).trim();
    if (!rawQuestion) return;

    const currentConversationId = activeConversation.id;
    const currentContext = conversationContext;
    const rewritten = options?.useContextRewrite === false ? { rewritten: rawQuestion, usedContext: false } : rewriteFollowUpQuestion(rawQuestion, currentContext);
    const finalQuestion = rewritten.rewritten;
    const effectiveMode = resolveActionMode(rawQuestion, actionMode);

    const currentRequestId = ++requestIdRef.current;
    const userMessage: Message = {
      id: currentRequestId * 2,
      sender: "user",
      kind: "text",
      text: rawQuestion,
      originalQuestion: finalQuestion
    };

    updateConversationById(currentConversationId, (conversation) => ({
      ...conversation,
      title: conversation.title === "新会话" ? getConversationTitleFromQuestion(rawQuestion) : conversation.title,
      updatedAt: Date.now(),
      messages: [...conversation.messages, userMessage]
    }));
    setStatus("loading");
    setLoadingStep(0);
    setActiveFrame(inferQuestionFrame(finalQuestion, timeScope, effectiveMode, rewritten.usedContext));
    setError(null);
    if (nextQuestion) setQuestion(nextQuestion);
    setContextHint(null);

    try {
      const payload = {
        question: finalQuestion,
        context: { time_scope: timeScope, language: "zh-CN", external_benchmark: externalBenchmark, analysis_focus: inferAnalysisFocus(rawQuestion, effectiveMode) },
        auth: { user_id: "u001", role }
      };
      const result = effectiveMode === "report" ? await submitReport(payload) : await submitQuery(payload);

      if (currentRequestId !== requestIdRef.current) return;

      updateConversationById(currentConversationId, (conversation) => ({
        ...conversation,
        updatedAt: Date.now(),
        context: extractContext(result, finalQuestion),
        messages: [
          ...conversation.messages,
          {
          id: currentRequestId * 2 + 1,
          sender: "assistant",
          kind: "result",
          text: getResultSummary(result),
          payload: result,
          originalQuestion: finalQuestion
          }
        ]
      }));
      setStatus("success");
      setQuestion("");
      setActiveFrame(null);
    } catch (err) {
      if (currentRequestId !== requestIdRef.current) return;

      const message = err instanceof Error ? err.message : "请求失败，请稍后重试。";
      setError(message);
      setActiveFrame(null);
      updateConversationById(currentConversationId, (conversation) => ({
        ...conversation,
        updatedAt: Date.now(),
        messages: [
          ...conversation.messages,
          {
            id: currentRequestId * 2 + 1,
            sender: "assistant",
            kind: "text",
            text: `这次没有成功返回结果：${message}`,
            originalQuestion: finalQuestion
          }
        ]
      }));
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

        <section className="conversation-panel panel" data-testid="conversation-panel">
          <div className="conversation-head">
            <div>
              <div className="panel-title">会话历史</div>
              <div className="section-desc">不同主题彼此隔离，追问只承接当前会话。</div>
            </div>
            <button type="button" className="new-conversation-btn" onClick={createFreshConversation} data-testid="new-conversation">
              新会话
            </button>
          </div>
          <div className="conversation-list" data-testid="conversation-list" aria-label="会话历史">
            {sortedConversations.map((conversation) => (
              <button
                type="button"
                key={conversation.id}
                className={`conversation-item ${conversation.id === activeConversation.id ? "active" : ""}`}
                onClick={() => selectConversation(conversation.id)}
                data-testid="conversation-item"
              >
                <span className="conversation-title">{conversation.title}</span>
                <span className="conversation-meta">{getConversationMeta(conversation)}</span>
              </button>
            ))}
          </div>
          {contextSnapshotItems.length ? (
            <div className="context-snapshot" data-testid="context-snapshot">
              <span className="context-snapshot-label">当前承接</span>
              {contextSnapshotItems.map((item) => (
                <span className="context-snapshot-item" key={item}>{item}</span>
              ))}
            </div>
          ) : null}
        </section>

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
                    showTechnicalDetails={showTechnicalDetails}
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
            <summary>高级设置</summary>
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

              {showTechnicalDetails ? (
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
              ) : null}

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

            {showTechnicalDetails ? (
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
            ) : null}
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
