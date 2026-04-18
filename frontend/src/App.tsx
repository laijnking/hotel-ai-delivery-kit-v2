import React, { useEffect, useMemo, useRef, useState } from "react";
import { fetchSystemSettings, submitQuery, submitReport } from "./lib/api";

type QueryStatus = "idle" | "loading" | "success" | "error";
type Role = "GROUP_ADMIN" | "AREA_MANAGER" | "HOTEL_MANAGER";
type ActionMode = "query" | "report";
type ViewMode = "management" | "debug";

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
  lastAnalysisMode?: string | null;
  lastAnalysisFocus?: string | null;
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

type PromptGroup = {
  title: string;
  description: string;
  items: string[];
};

type TraceEvent = {
  stage?: string;
  status?: string;
  duration_ms?: number;
  metadata?: Record<string, any>;
};

type SectionMetricRow = {
  rank: number | null;
  dimension: string;
  metric: string;
  value: string;
};

type SectionMetricGroup = {
  metric: string;
  rows: SectionMetricRow[];
};

type SectionTierRow = {
  tier: string;
  count: string;
  metric: string;
  value: string;
};

type SectionValueRow = {
  metric: string;
  value: string;
  note: string | null;
};

const ROLE_OPTIONS: Array<{ value: Role; label: string }> = [
  { value: "GROUP_ADMIN", label: "集团管理层" },
  { value: "AREA_MANAGER", label: "区域经理" },
  { value: "HOTEL_MANAGER", label: "单店经理" }
];

const ACTION_OPTIONS: Array<{ value: ActionMode; label: string }> = [
  { value: "query", label: "问答" },
  { value: "report", label: "报告" }
];

const VIEW_MODE_OPTIONS: Array<{ value: ViewMode; label: string; helper: string }> = [
  { value: "management", label: "管理层视图", helper: "只保留结论、分维度汇总、重点酒店和追问入口。" },
  { value: "debug", label: "调试视图", helper: "显示 Trace、SQL、权限范围、结构化数据和系统配置。" }
];

const DEFAULT_QUESTION = "汇总一下本月所有酒店的经营情况";
const DEFAULT_ROLE: Role = "GROUP_ADMIN";
const ROLE_STORAGE_KEY = "hotel-ai-role";
const BASE_FOLLOW_UP_SUGGESTIONS = ["继续展开原因", "换成经营摘要", "看去年同期", "看收入结构", "看利润和成本效率"];
const FALLBACK_QUICK_QUESTIONS = [
  "汇总一下本月所有酒店的经营情况",
  "广州丽思卡尔顿酒店3月的收入情况怎么样？",
  "看一下江门嘉华酒店3月的经营情况",
  "本月总收入同比如何？",
  "生成华南区本月经营摘要"
];
const LOADING_STEPS = ["已理解问题", "读取经营数据", "生成经营拆解", "准备追问建议"];
const CONVERSATION_STORAGE_KEY = "hotel-ai-conversations";
const ACTIVE_CONVERSATION_STORAGE_KEY = "hotel-ai-active-conversation";
const SECTION_TITLE_OBSERVATION = "\u7ecf\u8425\u89c2\u5bdf";
const SECTION_TITLE_MANAGEMENT = "\u7ba1\u7406\u5c42\u901f\u89c8";
const SECTION_TITLE_ANALYSIS = "\u5206\u5c42\u5206\u6790";
const SECTION_TITLES_MANAGEMENT_ORDER = [
  "\u5206\u6790\u8303\u56f4",
  "\u7ecf\u8425\u603b\u89c8",
  "\u7ba1\u7406\u516c\u53f8/\u533a\u57df\u6c47\u603b",
  "\u6536\u5165\u8d28\u91cf",
  "\u5ba2\u623f\u6548\u7387",
  "\u5229\u6da6\u8d28\u91cf",
  "\u6210\u672c\u6548\u7387",
  "\u91cd\u70b9\u9152\u5e97\u4e0e\u68af\u961f",
  "\u6a2a\u5411\u5bf9\u6807",
  "\u6a2a\u5411\u5bf9\u6807\u4e0e\u7ee7\u7eed\u8ffd\u95ee",
  "\u7ed3\u8bba",
  "\u98ce\u9669",
  "\u5efa\u8bae",
];
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

function dedupePromptItems(items: Array<string | null | undefined>) {
  return Array.from(new Set(items.map((item) => String(item || "").trim()).filter(Boolean)));
}

function getStarterPromptGroups(context: ConversationContext, quickQuestions: string[]): PromptGroup[] {
  const starterQuestions = dedupePromptItems((quickQuestions?.length ? quickQuestions : FALLBACK_QUICK_QUESTIONS).slice(0, 4));
  const quickFilters = dedupePromptItems([
    context.lastArea ? `只看${context.lastArea}` : "只看华南区",
    context.lastHotel ? `只看${context.lastHotel}` : null,
    "看去年同期",
    context.lastCompareMode === "yoy" ? "换成预算对比" : "切到去年同期",
    "换成经营摘要"
  ]);
  return [
    {
      title: "常用切入",
      description: "直接点一下，就能开始经营对话。",
      items: starterQuestions,
    },
    {
      title: "快速筛选",
      description: "缩小范围后再看重点变化。",
      items: quickFilters,
    },
  ];
}

function getFollowUpPromptGroups(context: ConversationContext, suggestions: string[]): PromptGroup[] {
  const followUpFocus = dedupePromptItems([
    ...suggestions.slice(0, 4),
    context.lastAnalysisFocus !== "income_structure" ? "看收入结构" : null,
    context.lastAnalysisFocus !== "profit_cost_efficiency" ? "看利润和成本效率" : null,
  ]);
  const followUpFilters = dedupePromptItems([
    context.lastArea ? `只看${context.lastArea}` : "只看华南区",
    context.lastHotel ? `只看${context.lastHotel}` : null,
    context.lastCompareMode !== "yoy" ? "看去年同期" : "换成预算对比",
    context.lastAnalysisMode !== "management_report" ? "换成经营摘要" : null,
  ]);
  return [
    {
      title: "继续聊",
      description: "顺着当前结论继续展开。",
      items: followUpFocus,
    },
    {
      title: "换个切法",
      description: "换区域、换口径、换时间再看一遍。",
      items: followUpFilters,
    },
  ];
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

function getTraceStageLabel(stage: unknown) {
  const value = String(stage || "");
  const labels: Record<string, string> = {
    parse_intent: "语义理解",
    sql_guardrail: "口径安全检查",
    execute_sql: "数据读取",
    build_analysis_blocks: "分析拆解",
    build_narrative_brief: "叙事生成",
    pipeline_warnings: "系统提示"
  };
  return labels[value] || value || "未知阶段";
}

function getTraceStatusLabel(status: unknown) {
  const value = String(status || "");
  const labels: Record<string, string> = {
    completed: "完成",
    passed: "通过",
    warning: "提醒",
    blocked: "阻断",
    fallback: "降级",
    failed: "失败"
  };
  return labels[value] || value || "待确认";
}

function getTraceEventNote(event: TraceEvent) {
  const metadata = event.metadata || {};
  const guardrailStatus = metadata.guardrail_status;
  const pieces = [
    typeof event.duration_ms === "number" ? `${event.duration_ms}ms` : null,
    guardrailStatus ? `Guardrail：${guardrailStatus}` : null,
    metadata.agent ? `Agent：${metadata.agent}` : null,
    typeof metadata.row_count === "number" ? `数据：${metadata.row_count} 条` : null,
    metadata.metric_code ? `指标：${metadata.metric_code}` : null
  ].filter(Boolean);
  return pieces.join(" · ");
}

function formatNumber(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value)) return "N/A";
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function formatPercent(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value)) return "N/A";
  return `${(value * 100).toFixed(1)}%`;
}

function parseDisplayNumber(value: string) {
  const numeric = Number(value.replace(/,/g, "").replace(/%$/, ""));
  return Number.isFinite(numeric) ? numeric : null;
}

const SECTION_METRIC_LABELS = [
  "NOP业主净利润",
  "餐饮/宴会收入",
  "能源费用",
  "经营利润",
  "餐饮成本",
  "人工成本",
  "客房成本",
  "行政费用",
  "客房收入",
  "总收入",
  "RevPAR",
  "GOP",
  "差额",
  "利润率",
  "成本率",
  "入住率",
].sort((left, right) => right.length - left.length);

const SECTION_METRIC_PATTERN = new RegExp(
  `^(?:(\\d+)[\\.、]\\s*)?(.+?)\\s+(${SECTION_METRIC_LABELS.map((item) => item.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})\\s+(-?[\\d,]+(?:\\.\\d+)?%?)$`,
);

const SECTION_RANKING_PATTERN = new RegExp(
  `(?:^|[；。\\n]\\s*)(?:(\\d+)[\\.、]\\s*)?([^；。\\n]+?)\\s+(${SECTION_METRIC_LABELS.map((item) => item.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})\\s+(-?[\\d,]+(?:\\.\\d+)?%?)`,
  "g",
);

const SECTION_VALUE_PATTERN = new RegExp(
  `^(${SECTION_METRIC_LABELS.map((item) => item.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})\\s+(-?[\\d,]+(?:\\.\\d+)?%?)(?:（([^）]+)）)?$`,
);

function parseSectionMetricGroups(content: unknown): SectionMetricGroup[] {
  const text = String(content || "").trim();
  if (!text) return [];
  const groups = new Map<string, SectionMetricRow[]>();
  for (const match of text.matchAll(SECTION_RANKING_PATTERN)) {
    const [, rank, dimension, metric, value] = match;
    const rows = groups.get(metric) || [];
    const cleanDimension = dimension.trim();
    if (!cleanDimension || SECTION_METRIC_LABELS.includes(cleanDimension)) continue;
    rows.push({
      rank: rank ? Number(rank) : rows.length + 1,
      dimension: cleanDimension,
      metric,
      value,
    });
    groups.set(metric, rows);
  }
  if (!groups.size) {
    text
      .split(/[；。\n]+/)
      .map((item) => item.trim())
      .filter(Boolean)
      .forEach((segment) => {
        const match = segment.match(SECTION_METRIC_PATTERN);
        if (!match) return;
        const [, rank, dimension, metric, value] = match;
        const rows = groups.get(metric) || [];
        rows.push({
          rank: rank ? Number(rank) : rows.length + 1,
          dimension: dimension.trim(),
          metric,
          value,
        });
        groups.set(metric, rows);
      });
  }
  return Array.from(groups.entries())
    .map(([metric, rows]) => ({ metric, rows }))
    .filter((group) => group.rows.length >= 2);
}

function parseSectionValueRows(content: unknown): SectionValueRow[] {
  const text = String(content || "").trim();
  if (!text) return [];
  const rows = text
    .split(/[；。\n]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((segment) => {
      const match = segment.match(SECTION_VALUE_PATTERN);
      if (!match) return null;
      const [, metric, value, note] = match;
      return { metric, value, note: note || null };
    })
    .filter(Boolean) as SectionValueRow[];
  return rows.length >= 2 ? rows : [];
}

function parseSectionTierRows(content: unknown): SectionTierRow[] {
  const text = String(content || "").trim();
  if (!text) return [];
  return text
    .split(/[；。\n]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((segment) => {
      const match = segment.match(/^(.+?)\s+(\d+)\s+家，?合计\s+(.+?)\s+(-?[\d,]+(?:\.\d+)?%?)$/);
      if (!match) return null;
      const [, tier, count, metric, value] = match;
      return { tier, count, metric, value };
    })
    .filter(Boolean) as SectionTierRow[];
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

function getAnalysisBlocks(result: any) {
  const sources = [
    result?.analysis_blocks,
    result?.explanation?.analysis_blocks,
    result?.report?.analysis_blocks,
  ];
  for (const source of sources) {
    if (Array.isArray(source) && source.length) {
      return source.filter((item) => item && typeof item === "object");
    }
    if (source && typeof source === "object") {
      const nested = source.blocks || source.items || source.list;
      if (Array.isArray(nested) && nested.length) {
        return nested.filter((item) => item && typeof item === "object");
      }
    }
  }
  return [];
}

function getNarrativeBrief(result: any) {
  const value =
    result?.narrative_brief ||
    result?.explanation?.narrative_brief ||
    result?.report?.narrative_brief ||
    result?.briefing ||
    null;
  if (typeof value === "string") {
    const text = value.trim();
    return text || null;
  }
  return typeof value === "number" ? String(value) : null;
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
  const conclusion = sections.find((item: any) => item.title === "\u7ed3\u8bba");
  const risk = sections.find((item: any) => item.title === "\u98ce\u9669");
  if (!conclusion && !risk) return null;
  return [conclusion?.content, risk?.content].filter(Boolean).join(" ");
}

function normalizeAnalysisText(value: unknown) {
  return String(value || "").replace(/\s+/g, "").toLowerCase();
}

function getAnalysisBlockTitle(block: any, index: number) {
  const title = block?.title || block?.name || block?.label || block?.heading;
  if (typeof title === "string" && title.trim()) return title.trim();
  return `分析块 ${index + 1}`;
}

function getAnalysisBlockNarrative(block: any) {
  const candidates = [
    block?.narrative,
    block?.brief,
    block?.summary,
    block?.content,
    block?.description,
    block?.lead,
  ];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  return "";
}

function getAnalysisBlockTags(block: any) {
  const raw = block?.tags || block?.metrics || block?.metrics_used || block?.highlights || block?.points || block?.items;
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item: any) => {
      if (typeof item === "string") return item.trim();
      if (item && typeof item === "object") {
        const label = item.label || item.name || item.title || item.key;
        const value = item.value ?? item.amount ?? item.text;
        if (label && value != null && String(value).trim()) {
          return `${String(label).trim()}：${String(value).trim()}`;
        }
        if (label) return String(label).trim();
        if (value != null) return String(value).trim();
      }
      return "";
    })
    .filter(Boolean)
    .slice(0, 6);
}

function getAnalysisBlockStatus(block: any) {
  const status = String(block?.data_status || block?.status || "").trim();
  if (status === "available") return { label: "数据完整", tone: "ok" };
  if (status === "partial") return { label: "部分数据", tone: "warn" };
  if (status === "missing") return { label: "缺少数据", tone: "danger" };
  return null;
}

function getAnalysisBlockEvidence(block: any) {
  const fields = Array.isArray(block?.evidence_fields)
    ? block.evidence_fields.map((item: any) => String(item || "").trim()).filter(Boolean)
    : [];
  const metrics = Array.isArray(block?.metrics_used)
    ? block.metrics_used.map((item: any) => String(item || "").trim()).filter(Boolean)
    : [];
  return {
    fields: fields.slice(0, 8),
    metrics: metrics.slice(0, 8),
  };
}

function getAnalysisBlockSignatures(blocks: any[]) {
  const signatures = new Set<string>();
  blocks.forEach((block, index) => {
    const title = getAnalysisBlockTitle(block, index);
    signatures.add(normalizeAnalysisText(title));
    const narrative = getAnalysisBlockNarrative(block);
    if (narrative) signatures.add(normalizeAnalysisText(narrative));
  });
  return signatures;
}

function isDuplicateSectionAgainstAnalysisBlocks(section: any, blockSignatures: Set<string>) {
  const title = normalizeAnalysisText(section?.title);
  const content = normalizeAnalysisText(section?.content);
  if (!title && !content) return false;
  if (blockSignatures.has(title) || blockSignatures.has(content)) return true;
  for (const signature of blockSignatures) {
    if (!signature) continue;
    if ((title && (title.includes(signature) || signature.includes(title))) || (content && (content.includes(signature) || signature.includes(content)))) {
      return true;
    }
  }
  return false;
}

function getTemplateSectionOrder(templateCode: string) {
  if (templateCode === "executive_group_dimension") {
    return [
      "经营总览",
      "管理公司/区域汇总",
      "收入质量",
      "客房效率",
      "利润质量",
      "成本效率",
      "重点酒店与梯队",
      "横向对标",
      "横向对标与继续追问",
      "结论",
      "风险",
      "建议",
    ];
  }
  if (templateCode === "executive_hotel_snapshot") {
    return [
      "分析范围",
      "经营总览",
      "收入质量",
      "客房效率",
      "利润质量",
      "成本效率",
      "横向对标",
      "结论",
      "风险",
      "建议",
    ];
  }
  if (templateCode === "executive_portfolio") {
    return [
      "分析范围",
      "经营总览",
      "管理公司/区域汇总",
      "收入质量",
      "客房效率",
      "利润质量",
      "成本效率",
      "重点酒店与梯队",
      "横向对标",
      "横向对标与继续追问",
      "结论",
      "风险",
      "建议",
    ];
  }
  return SECTION_TITLES_MANAGEMENT_ORDER;
}

function getTemplateSectionTitle(templateCode: string) {
  if (templateCode === "executive_group_dimension") return "管理层速读";
  if (templateCode === "executive_hotel_snapshot") return "经营摘要";
  if (templateCode === "executive_portfolio") return "组合总览";
  return "分层分析";
}

function getVisibleManagementSections(result: any) {
  const sections = getPrimarySections(result);
  if (!sections.length) return [];
  const templateCode = getReportTemplateCode(result);
  const order = getTemplateSectionOrder(templateCode);
  const limit = templateCode === "executive_group_dimension" ? 4 : templateCode === "executive_hotel_snapshot" ? 3 : 5;
  const analysisBlocks = getAnalysisBlocks(result);
  const blockSignatures = analysisBlocks.length ? getAnalysisBlockSignatures(analysisBlocks) : null;

  return sections
    .map((section: any, index: number) => ({
      section,
      score: order.indexOf(String(section?.title || "")),
      index,
    }))
    .filter(({ section }) => !blockSignatures || !isDuplicateSectionAgainstAnalysisBlocks(section, blockSignatures))
    .sort((left, right) => {
      const leftScore = left.score === -1 ? 999 + left.index : left.score;
      const rightScore = right.score === -1 ? 999 + right.index : right.score;
      return leftScore - rightScore;
    })
    .map((item) => item.section)
    .filter((section) => Boolean(section?.content))
    .slice(0, limit);
}

function getTemplateLeadLine(result: any) {
  const sections = getVisibleManagementSections(result);
  const firstSection = sections[0];
  return getExecutiveSummaryLine(result) || firstSection?.content || getResultSummary(result);
}

function getManagementSections(result: any) {
  const sections = getPrimarySections(result);
  if (!sections.length) return [];

  const preferredTitles = [
    "ç»è¥æ€»è§ˆ",
    "æ”¶å…¥è´¨é‡",
    "å®¢æˆ¿æ•ˆçŽ‡",
    "åˆ©æ¶¦è´¨é‡",
    "æˆæœ¬æ•ˆçŽ‡",
    "é‡ç‚¹é…’åº—ä¸Žæ¢¯é˜Ÿ",
    "æ¨ªå‘å¯¹æ ‡ä¸Žç»§ç»­è¿½é—®",
    "ç»“è®º",
    "é£Žé™©",
    "å»ºè®®",
  ];

  return sections
    .map((section: any, index: number) => ({
      section,
      score: SECTION_TITLES_MANAGEMENT_ORDER.indexOf(String(section?.title || "")),
      index,
    }))
    .sort((left, right) => {
      const leftScore = left.score === -1 ? 999 + left.index : left.score;
      const rightScore = right.score === -1 ? 999 + right.index : right.score;
      return leftScore - rightScore;
    })
    .map((item) => item.section)
    .slice(0, 5);
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
    lastCompareMode: parsed?.compare_mode || null,
    lastAnalysisMode: queryPlan?.analysis_mode || null,
    lastAnalysisFocus: parsed?.analysis_focus || queryPlan?.analysis_focus || null,
    lastSummary: String(firstSection?.content || summary || "")
  };
}

function buildSemanticConversationContext(context: ConversationContext) {
  return {
    metric_code: context.lastMetric,
    compare_mode: context.lastCompareMode,
    time_scope: context.lastTimeScope,
    requested_hotels: context.lastHotel ? [context.lastHotel] : [],
    requested_areas: context.lastArea ? [context.lastArea] : [],
    query_plan: {
      query_object_label: context.lastScopeLabel,
      analysis_mode: context.lastAnalysisMode,
      analysis_focus: context.lastAnalysisFocus,
    },
    summary: context.lastSummary,
    last_question: context.lastQuestion,
  };
}

function getFollowUpSuggestions(context: ConversationContext) {
  const suggestions: string[] = [];
  if (context.lastAnalysisFocus !== "driver_analysis") suggestions.push("继续展开原因");
  if (context.lastCompareMode !== "yoy") suggestions.push("看去年同期");
  if (context.lastAnalysisFocus !== "income_structure") suggestions.push("看收入结构");
  if (context.lastAnalysisFocus !== "profit_cost_efficiency") suggestions.push("看利润和成本效率");
  if (context.lastAnalysisMode !== "management_report") suggestions.push("换成经营摘要");
  return suggestions.slice(0, 5);
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
  const metricCode = String(result?.parsed_intent?.metric_code || result?.metric_definition?.metric_code || "");
  if (metricCode === "OPERATING_PROFIT") return "\u7ecf\u8425\u5229\u6da6\uff08GOP\uff09";
  if (metricCode === "OWNER_PROFIT") return "NOP业主净利润";
  return result?.metric_definition?.name_cn || result?.parsed_intent?.metric_code || "经营指标";
}

function getReportTemplateCode(result: any) {
  return String(result?.parsed_intent?.query_plan?.report_template_code || "");
}

function getResultKicker(result: any) {
  const templateCode = getReportTemplateCode(result);
  if (templateCode === "executive_group_dimension") return "组合经营简报";
  if (templateCode === "executive_hotel_snapshot") return "单店经营快照";
  if (templateCode === "executive_portfolio") return "管理层经营简报";
  return "经营分析";
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
  if (text === "group_by_dimension_report") return "分维度汇总";
  if (text === "driver_analysis") return "归因分析";
  if (text === "ranking_overview") return "排名概览";
  if (text === "budget") return "预算对比";
  if (text === "yoy") return "去年同期";
  if (text === "actual") return "实际表现";
  return text || "系统默认";
}

function getDisplayRows(result: any) {
  if (Array.isArray(result?.portfolio_breakdown) && result.portfolio_breakdown.length) {
    return result.portfolio_breakdown;
  }
  return Array.isArray(result?.data_points) ? result.data_points : [];
}

function getPortfolioMemberCount(result: any) {
  if (["incomplete", "mismatch"].includes(String(result?.data_quality?.status || ""))) return null;
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

function getDimensionLabel(dimension: string) {
  if (dimension === "manage_corp") return "管理公司";
  if (dimension === "area") return "区域";
  if (dimension === "manage_corp_area") return "管理公司 x 区域";
  if (dimension === "brand_child") return "品牌";
  return dimension;
}

function getDimensionRowLabel(dimension: string, row: any) {
  if (dimension === "manage_corp_area") {
    return `${row?.manage_corp || "未标注"} - ${row?.area || "未标注"}`;
  }
  if (dimension === "manage_corp") return row?.manage_corp || "未标注";
  if (dimension === "area") return row?.area || "未标注";
  if (dimension === "brand_child") return row?.brand_child || "未标注";
  return row?.name || "未标注";
}

function getDimensionBreakdownGroups(result: any) {
  const breakdowns = result?.dimension_breakdowns;
  if (!breakdowns || typeof breakdowns !== "object") return [];
  return ["manage_corp", "area", "manage_corp_area", "brand_child"]
    .map((dimension) => {
      const rows = Array.isArray(breakdowns?.[dimension]) ? breakdowns[dimension] : [];
      return {
        dimension,
        title: getDimensionLabel(dimension),
        rows: rows.slice(0, 6),
      };
    })
    .filter((group) => group.rows.length > 0);
}

function getDimensionInsight(row: any) {
  const diffRate = row?.diff_rate;
  const diffValue = row?.diff_value;
  if (typeof diffRate === "number" && !Number.isNaN(diffRate)) {
    const direction = diffRate >= 0 ? "高于" : "低于";
    return `${direction}对比口径 ${formatPercent(Math.abs(diffRate))}，差额 ${formatNumber(diffValue)}`;
  }
  if (typeof diffValue === "number" && !Number.isNaN(diffValue)) {
    return `差额 ${formatNumber(diffValue)}`;
  }
  return "暂无差额口径";
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

function getPortfolioMetricValue(row: any, fields: string[]) {
  for (const field of fields) {
    const value = row?.[field];
    if (typeof value === "number" && !Number.isNaN(value)) return value;
  }
  return null;
}

function getPortfolioRankingGroups(rows: any[]) {
  const configs = [
    { label: "总收入", fields: ["total_income_actual"], direction: "desc" },
    { label: "NOP业主净利润", fields: ["owner_profit_actual"], direction: "desc" },
    { label: "GOP", fields: ["operating_profit_actual"], direction: "desc" },
    { label: "RevPAR", fields: ["revpar_actual"], direction: "desc" },
    { label: "差额", fields: ["diff_value"], direction: "asc" },
  ];
  return configs
    .map((config) => {
      const rankedRows = rows
        .map((row) => ({ row, value: getPortfolioMetricValue(row, config.fields) }))
        .filter((item) => item.value !== null)
        .sort((left, right) => {
          const diff = Number(right.value) - Number(left.value);
          return config.direction === "asc" ? -diff : diff;
        })
        .slice(0, 5);
      return { label: config.label, rows: rankedRows };
    })
    .filter((group) => group.rows.length >= 2);
}

function getOwnerProfitTierRows(rows: any[]) {
  const buckets = [
    { label: "2000万以上", min: 20000000, max: Infinity },
    { label: "1000万-2000万", min: 10000000, max: 20000000 },
    { label: "500万-1000万", min: 5000000, max: 10000000 },
    { label: "200万-500万", min: 2000000, max: 5000000 },
    { label: "0-200万", min: 0, max: 2000000 },
    { label: "亏损", min: -Infinity, max: 0 },
  ];
  return buckets
    .map((bucket) => {
      const bucketRows = rows.filter((row) => {
        const value = getPortfolioMetricValue(row, ["owner_profit_actual"]);
        return value !== null && value >= bucket.min && value < bucket.max;
      });
      if (!bucketRows.length) return null;
      const total = bucketRows.reduce((sum, row) => sum + Number(getPortfolioMetricValue(row, ["owner_profit_actual"]) || 0), 0);
      return {
        tier: bucket.label,
        count: bucketRows.length,
        value: total,
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

function SectionMetricTables({
  groups,
  tierRows,
  valueRows = [],
}: {
  groups: SectionMetricGroup[];
  tierRows: SectionTierRow[];
  valueRows?: SectionValueRow[];
}) {
  if (!groups.length && !tierRows.length && !valueRows.length) return null;
  return (
    <div className="structured-section" data-testid="structured-section-table">
      {valueRows.length ? (
        <div className="structured-table-card structured-table-card--wide">
          <div className="structured-table-title">指标明细</div>
          <table className="structured-table">
            <thead>
              <tr>
                <th>指标</th>
                <th>数据</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              {valueRows.map((row) => (
                <tr key={`${row.metric}-${row.value}`}>
                  <td>{row.metric}</td>
                  <td className={parseDisplayNumber(row.value) !== null && Number(parseDisplayNumber(row.value)) < 0 ? "negative-number" : ""}>{row.value}</td>
                  <td>{row.note || "当前口径"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {groups.length ? (
        <div className="structured-table-grid">
          {groups.map((group) => (
            <div className="structured-table-card" key={group.metric}>
              <div className="structured-table-title">{group.metric}</div>
              <table className="structured-table">
                <thead>
                  <tr>
                    <th>排名</th>
                    <th>维度</th>
                    <th>数据</th>
                  </tr>
                </thead>
                <tbody>
                  {group.rows.map((row, index) => (
                    <tr key={`${group.metric}-${row.dimension}-${index}`}>
                      <td>{row.rank || index + 1}</td>
                      <td>{row.dimension}</td>
                      <td className={parseDisplayNumber(row.value) !== null && Number(parseDisplayNumber(row.value)) < 0 ? "negative-number" : ""}>{row.value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      ) : null}
      {tierRows.length ? (
        <div className="structured-table-card structured-table-card--wide">
          <div className="structured-table-title">梯队汇总</div>
          <table className="structured-table">
            <thead>
              <tr>
                <th>梯队</th>
                <th>数量</th>
                <th>指标</th>
                <th>合计</th>
              </tr>
            </thead>
            <tbody>
              {tierRows.map((row) => (
                <tr key={`${row.tier}-${row.metric}`}>
                  <td>{row.tier}</td>
                  <td>{row.count} 家</td>
                  <td>{row.metric}</td>
                  <td className={parseDisplayNumber(row.value) !== null && Number(parseDisplayNumber(row.value)) < 0 ? "negative-number" : ""}>{row.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function PortfolioWatchlistSection({
  rows,
  outlierItems,
  fallbackContent,
}: {
  rows: any[];
  outlierItems: any[];
  fallbackContent: string;
}) {
  const rankingGroups = getPortfolioRankingGroups(rows);
  const tierRows = getOwnerProfitTierRows(rows);
  if (!rankingGroups.length) {
    const parsedGroups = parseSectionMetricGroups(fallbackContent);
    const parsedTiers = parseSectionTierRows(fallbackContent);
    return (
      <>
        <SectionMetricTables groups={parsedGroups} tierRows={parsedTiers} />
        {!parsedGroups.length && !parsedTiers.length ? <div className="leadership-section-content">{fallbackContent}</div> : null}
      </>
    );
  }
  return (
    <div className="portfolio-watchlist" data-testid="portfolio-watchlist-table">
      <div className="structured-table-grid">
        {rankingGroups.map((group) => (
          <div className="structured-table-card" key={group.label}>
            <div className="structured-table-title">{group.label}</div>
            <table className="structured-table">
              <thead>
                <tr>
                  <th>排名</th>
                  <th>酒店</th>
                  <th>数据</th>
                </tr>
              </thead>
              <tbody>
                {group.rows.map((item, index) => (
                  <tr key={`${group.label}-${item.row?.hotel_name || index}`}>
                    <td>{index + 1}</td>
                    <td>{item.row?.hotel_name || "未知酒店"}</td>
                    <td className={Number(item.value) < 0 ? "negative-number" : ""}>{formatNumber(item.value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
      {tierRows.length ? (
        <div className="structured-table-card structured-table-card--wide">
          <div className="structured-table-title">NOP业主净利润梯队</div>
          <table className="structured-table">
            <thead>
              <tr>
                <th>梯队</th>
                <th>酒店数</th>
                <th>合计 NOP</th>
              </tr>
            </thead>
            <tbody>
              {tierRows.map((row: any) => (
                <tr key={row.tier}>
                  <td>{row.tier}</td>
                  <td>{row.count} 家</td>
                  <td className={row.value < 0 ? "negative-number" : ""}>{formatNumber(row.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {outlierItems.length ? (
        <div className="watchlist-outlier-strip">
          {outlierItems.map((item: any) => (
            <div className="watchlist-outlier-item" key={item.title}>
              <strong>{item.title}</strong>
              {item.best ? <span>{item.best}</span> : null}
              {item.worst ? <span>{item.worst}</span> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function StructuredSectionContent({
  section,
  rows,
  outlierItems,
}: {
  section: any;
  rows: any[];
  outlierItems: any[];
}) {
  const title = String(section?.title || "");
  const content = String(section?.content || "");
  if (title === "重点酒店与梯队") {
    return <PortfolioWatchlistSection rows={rows} outlierItems={outlierItems} fallbackContent={content} />;
  }
  const metricGroups = parseSectionMetricGroups(content);
  const tierRows = parseSectionTierRows(content);
  const valueRows = parseSectionValueRows(content);
  if (metricGroups.length || tierRows.length || valueRows.length) {
    return (
      <>
        <SectionMetricTables groups={metricGroups} tierRows={tierRows} valueRows={valueRows} />
        <details className="structured-section-source">
          <summary>查看原始表述</summary>
          <div className="leadership-section-content">{content}</div>
        </details>
      </>
    );
  }
  return <div className="leadership-section-content">{content}</div>;
}

function LoadingCard({ frame, step, promptLabel }: { frame: QuestionFrame | null; step: number; promptLabel?: string | null }) {
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
        <div className="loading-badges">
          {promptLabel ? <span className="source-pill loading-pill">当前已选：{promptLabel}</span> : null}
          {frame?.usedContext ? <span className="source-pill">已承接上文</span> : null}
        </div>
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

function PromptBank({
  title,
  description,
  groups,
  onSelect,
  disabled = false,
  selectedPrompt,
  className = "",
  feedbackLabel,
  dataTestId,
}: {
  title: string;
  description: string;
  groups: PromptGroup[];
  onSelect: (value: string) => void;
  disabled?: boolean;
  selectedPrompt?: string | null;
  className?: string;
  feedbackLabel?: string | null;
  dataTestId?: string;
}) {
  if (!groups.length) return null;
  return (
    <section className={`prompt-bank panel ${className}`.trim()} data-testid={dataTestId}>
      <div className="section-head prompt-bank-head">
        <div>
          <div className="panel-title">{title}</div>
          <div className="section-desc">{description}</div>
        </div>
        {feedbackLabel ? <span className="prompt-feedback-pill">{feedbackLabel}</span> : null}
      </div>
      <div className="prompt-group-list">
        {groups.map((group) => (
          <div className="prompt-group" key={group.title}>
            <div className="prompt-group-head">
              <div className="prompt-group-title">{group.title}</div>
              <div className="prompt-group-desc">{group.description}</div>
            </div>
            <div className="prompt-chip-list">
              {group.items.map((item, index) => (
                <button
                  type="button"
                  className={`prompt-chip ${selectedPrompt === item ? "active" : ""}`}
                  key={`${group.title}-${item}-${index}`}
                  disabled={disabled}
                  onClick={() => onSelect(item)}
                  data-testid={`${dataTestId || "prompt-bank"}-${group.title}-${index}`}
                  aria-pressed={selectedPrompt === item}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function AnalysisBlocksPanel({
  blocks,
  rows,
  outlierItems,
}: {
  blocks: any[];
  rows: any[];
  outlierItems: any[];
}) {
  if (!blocks.length) return null;
  return (
    <div className="result-block analysis-block-section" data-testid="analysis-blocks">
      <div className="result-block-title">结构化分析</div>
      <div className="analysis-block-grid">
        {blocks.map((block, index) => {
          const title = getAnalysisBlockTitle(block, index);
          const narrative = getAnalysisBlockNarrative(block);
          const tags = getAnalysisBlockTags(block);
          const status = getAnalysisBlockStatus(block);
          const evidence = getAnalysisBlockEvidence(block);
          const hasEvidence = evidence.metrics.length > 0 || evidence.fields.length > 0;
          return (
            <section className="analysis-block-card" key={`${title}-${index}`}>
              <div className="analysis-block-head">
                <div className="analysis-block-title">{title}</div>
                <div className="analysis-block-pill-row">
                  {status ? <span className={`analysis-block-status analysis-block-status--${status.tone}`}>{status.label}</span> : null}
                  {block?.tag ? <span className="analysis-block-pill">{String(block.tag)}</span> : null}
                </div>
              </div>
              {narrative ? (
                <div className="analysis-block-summary">
                  <StructuredSectionContent section={{ title, content: narrative }} rows={rows} outlierItems={outlierItems} />
                </div>
              ) : null}
              {tags.length ? (
                <div className="analysis-block-tags">
                  {tags.map((item: string) => (
                    <span className="analysis-block-tag" key={item}>{item}</span>
                  ))}
                </div>
              ) : null}
              {hasEvidence ? (
                <details className="analysis-block-evidence">
                  <summary>查看证据字段</summary>
                  {evidence.metrics.length ? (
                    <div className="analysis-block-evidence-row">
                      <span>指标</span>
                      <strong>{evidence.metrics.join(" / ")}</strong>
                    </div>
                  ) : null}
                  {evidence.fields.length ? (
                    <div className="analysis-block-evidence-row">
                      <span>字段</span>
                      <strong>{evidence.fields.join(" / ")}</strong>
                    </div>
                  ) : null}
                </details>
              ) : null}
            </section>
          );
        })}
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
  if (/同比|去年同期/.test(text)) {
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

  if (trimmed.includes("同比变化") || trimmed.includes("去年同期")) {
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
  showTechnicalDetails = false,
  selectedPromptLabel = null,
}: {
  result: any;
  onFollowUp: (value: string) => void;
  disabled?: boolean;
  suggestions?: string[];
  showTechnicalDetails?: boolean;
  selectedPromptLabel?: string | null;
}) {
  const highlights = getHighlights(result);
  const sections = getPrimarySections(result);
  const finalSuggestions = result?.interaction_mode === "clarification" ? getClarificationSuggestions(result) : suggestions;
  const displayRows = getDisplayRows(result);
  const firstPoint = displayRows.length ? displayRows[0] : null;
  const performanceLabel = getPerformanceLabel(result);
  const recognizedScopeItems = getRecognizedScopeItems(result);
  const narrativeBrief = getNarrativeBrief(result);
  const portfolioSummaryPoint = Array.isArray(result?.data_points) && result.data_points.length ? result.data_points[0] : null;
  const isPortfolio = String(result?.parsed_intent?.query_plan?.query_grain || "") === "portfolio";
  const portfolioMemberCount = getPortfolioMemberCount(result);
  const portfolioOutlierItems = getPortfolioOutlierItems(result);
  const analysisBlocks = getAnalysisBlocks(result);
  const hasAnalysisBlocks = analysisBlocks.length > 0;
  const dimensionBreakdownGroups = getDimensionBreakdownGroups(result);
  const templateCode = getReportTemplateCode(result);
  const isGroupDimensionTemplate = templateCode === "executive_group_dimension";
  const isHotelSnapshotTemplate = templateCode === "executive_hotel_snapshot";
  const visibleManagementSections = getVisibleManagementSections(result);
  const showInlineManagementSections = !showTechnicalDetails && visibleManagementSections.length > 0;
  const resultTitle = getTemplateSectionTitle(templateCode);
  const templateLeadLine = getTemplateLeadLine(result);
  const showObservationBlock = !showTechnicalDetails && !hasAnalysisBlocks && !visibleManagementSections.length && highlights.length > 0;
  const showTopDataPoints = !isGroupDimensionTemplate && displayRows.length > 0;
  const compareModeLabel = getAnalysisModeLabel(result?.parsed_intent?.compare_mode || "system_default");
  const sampleCountLabel = isPortfolio ? formatNumber(portfolioMemberCount) : formatNumber(result?.data_points?.length);
  const traceEvents = Array.isArray(result?.trace_events) ? result.trace_events as TraceEvent[] : [];
  const followUpGroups = getFollowUpPromptGroups(
    {
      lastQuestion: String(result?.original_question || result?.parsed_intent?.question || result?.question || ""),
      lastMetric: String(result?.parsed_intent?.metric_code || result?.metric_definition?.metric_code || ""),
      lastHotel: String(result?.parsed_intent?.requested_hotel || result?.parsed_intent?.query_plan?.query_object_label || ""),
      lastArea: String(result?.parsed_intent?.requested_area || ""),
      lastTimeScope: String(result?.parsed_intent?.time_scope || result?.parsed_intent?.query_plan?.time_scope || ""),
      lastScopeLabel: String(result?.parsed_intent?.query_plan?.query_object_label || ""),
      lastCompareMode: String(result?.parsed_intent?.compare_mode || ""),
      lastAnalysisMode: String(result?.parsed_intent?.query_plan?.analysis_mode || ""),
      lastAnalysisFocus: String(result?.parsed_intent?.analysis_focus || ""),
      lastSummary: String(result?.summary || ""),
    },
    finalSuggestions
  );
  return (
    <div className={`result-card ${templateCode ? `result-card--${templateCode.replace(/_/g, "-")}` : "result-card--default"}`} data-testid="result-card">
      <div className="assistant-card-head">
        <div>
          <div className="result-kicker">{getResultKicker(result)}</div>
          <div className="result-summary" data-testid="result-summary">{narrativeBrief || getResultSummary(result)}</div>
        </div>
        <span className="source-pill">{getDataSourceLabel(result)}</span>
      </div>

      <div className="result-block result-briefing" data-testid="management-overview">
        <div className="result-block-title">{resultTitle}</div>
        <div className="result-briefing-text">{templateLeadLine}</div>
      </div>

      {hasAnalysisBlocks ? <AnalysisBlocksPanel blocks={analysisBlocks} rows={displayRows} outlierItems={portfolioOutlierItems} /> : null}

      {false ? <div className="result-block" data-testid="management-observation">
        <div className="result-block-title">ç»è¥è§‚å¯Ÿ</div>
        <div className="executive-line">{observationText}</div>
      </div> : null}

      {firstPoint ? (
        <div className="metric-strip metric-strip--template" data-testid="primary-metric-strip">
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

      {false && compareBasisLine ? (
        <div className="result-block" data-testid="executive-overview">
        <div className="result-block-title">{SECTION_TITLE_MANAGEMENT}</div>
          <div className="executive-line">{compareBasisLine}</div>
        </div>
      ) : null}

      <div className="result-meta">
        <span className="meta-pill">指标：{getMetricLabel(result)}</span>
        {sampleCountLabel !== "N/A" ? <span className="meta-pill">样本：{sampleCountLabel} 条</span> : null}
        {result?.data_source?.warehouse_manifest?.latest_month ? <span className="meta-pill">最新账期：{result.data_source.warehouse_manifest.latest_month}</span> : null}
        {result?.parsed_intent?.compare_mode ? <span className="meta-pill">口径：{compareModeLabel}</span> : null}
      </div>

      <div className="result-block insight-block" data-testid="recognized-scope">
        <div className="result-block-title">当前理解</div>
        <div className="section-desc">系统已经识别出的范围、时间、指标和口径。</div>
        <div className="intent-strip">
          {recognizedScopeItems.map((item) => (
            <div className="intent-chip" key={item.label}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>
      </div>

      {isGroupDimensionTemplate && dimensionBreakdownGroups.length ? (
        <div className="result-block" data-testid="dimension-breakdowns">
          <div className="result-block-title">分维度汇总</div>
          <div className="dimension-breakdown-grid">
            {dimensionBreakdownGroups.map((group) => (
              <section className="dimension-breakdown-card" key={group.dimension}>
                <div className="dimension-breakdown-head">
                  <div className="dimension-breakdown-title">{group.title}</div>
                  <div className="dimension-breakdown-subtitle">按当前问题自动提炼的重点分组</div>
                </div>
                <div className="dimension-breakdown-list">
                  {group.rows.map((row: any, index: number) => (
                    <div className="dimension-breakdown-row" key={`${group.dimension}-${getDimensionRowLabel(group.dimension, row)}-${index}`}>
                      <div className="dimension-breakdown-rank">{index + 1}</div>
                      <div className="dimension-breakdown-main">
                        <div className="dimension-breakdown-name">{getDimensionRowLabel(group.dimension, row)}</div>
                        <div className="dimension-breakdown-insight">{getDimensionInsight(row)}</div>
                      </div>
                      <div className="dimension-breakdown-metrics">
                        <span>{formatNumber(row?.hotel_count)} 家</span>
                        <span>收入 {formatNumber(row?.total_income_actual)}</span>
                        <span>NOP {formatNumber(row?.owner_profit_actual)}</span>
                        <span>RevPAR {formatNumber(row?.revpar_actual)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </div>
      ) : null}

      {showInlineManagementSections ? (
        <div className="result-block" data-testid="management-sections">
          <div className="result-block-title">åˆ†å±‚åˆ†æž</div>
          <div className={`leadership-section-grid leadership-section-grid--${templateCode ? templateCode.replace(/_/g, "-") : "default"}`}>
            {visibleManagementSections.map((section: any, index: number) => (
              <section className={`leadership-section-card ${index === 0 ? "leadership-section-card--feature" : ""}`} key={`${section.title}-${index}`} data-testid={`section-${section.title}`}>
                <div className="leadership-section-title">{section.title}</div>
                <StructuredSectionContent section={section} rows={displayRows} outlierItems={portfolioOutlierItems} />
              </section>
            ))}
          </div>
        </div>
      ) : null}

      {!isGroupDimensionTemplate && dimensionBreakdownGroups.length ? (
        <div className="result-block" data-testid="dimension-breakdowns">
          <div className="result-block-title">分维度汇总</div>
          <div className="dimension-breakdown-grid">
            {dimensionBreakdownGroups.map((group) => (
              <section className="dimension-breakdown-card" key={group.dimension}>
                <div className="dimension-breakdown-head">
                  <div className="dimension-breakdown-title">{group.title}</div>
                  <div className="dimension-breakdown-subtitle">按当前问题自动提炼的重点分组</div>
                </div>
                <div className="dimension-breakdown-list">
                  {group.rows.map((row: any, index: number) => (
                    <div className="dimension-breakdown-row" key={`${group.dimension}-${getDimensionRowLabel(group.dimension, row)}-${index}`}>
                      <div className="dimension-breakdown-rank">{index + 1}</div>
                      <div className="dimension-breakdown-main">
                        <div className="dimension-breakdown-name">{getDimensionRowLabel(group.dimension, row)}</div>
                        <div className="dimension-breakdown-insight">{getDimensionInsight(row)}</div>
                      </div>
                      <div className="dimension-breakdown-metrics">
                        <span>{formatNumber(row?.hotel_count)} 家</span>
                        <span>收入 {formatNumber(row?.total_income_actual)}</span>
                        <span>NOP {formatNumber(row?.owner_profit_actual)}</span>
                        <span>RevPAR {formatNumber(row?.revpar_actual)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </div>
      ) : null}

      <InternalBenchmarkCard benchmark={result?.internal_benchmark} />
      <ExternalBenchmarkCard benchmark={result?.external_benchmark} />

      {showTopDataPoints && !isHotelSnapshotTemplate ? (
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

      {showObservationBlock && !isGroupDimensionTemplate ? (
        <div className="result-block" data-testid="risk-highlights">
        <div className="result-block-title">{SECTION_TITLE_OBSERVATION}</div>
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
                <StructuredSectionContent section={section} rows={displayRows} outlierItems={portfolioOutlierItems} />
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
          {traceEvents.length ? (
            <div className="trace-events-summary" data-testid="trace-events-summary">
              {traceEvents.map((event, index) => (
                <div className="trace-event-row" key={`${event.stage || "stage"}-${index}`}>
                  <div>
                    <strong>{getTraceStageLabel(event.stage)}</strong>
                    <span>{getTraceStatusLabel(event.status)}</span>
                  </div>
                  {getTraceEventNote(event) ? <em>{getTraceEventNote(event)}</em> : null}
                </div>
              ))}
            </div>
          ) : null}
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

      <PromptBank
        title="你可以继续问"
        description="顺着当前结果继续展开，或者把范围再缩一层。"
        groups={followUpGroups}
        selectedPrompt={selectedPromptLabel}
        onSelect={onFollowUp}
        disabled={disabled}
        className="follow-up-prompt-bank"
        feedbackLabel={selectedPromptLabel ? (disabled ? "正在继续追问" : "最近一次操作") : null}
        dataTestId="follow-up-actions"
      />
    </div>
  );
}

export default function App() {
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [timeScope, setTimeScope] = useState(() => getPreviousMonthScope());
  const [role, setRole] = useState<Role>(() => getInitialRole());
  const [actionMode, setActionMode] = useState<ActionMode>("query");
  const [viewMode, setViewMode] = useState<ViewMode>(() => (getInitialRole() === "GROUP_ADMIN" ? "management" : "debug"));
  const [externalBenchmark, setExternalBenchmark] = useState(false);
  const [status, setStatus] = useState<QueryStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [contextHint, setContextHint] = useState<string | null>(null);
  const [selectedPromptLabel, setSelectedPromptLabel] = useState<string | null>(null);
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
  const showTechnicalDetails = viewMode === "debug" || role !== "GROUP_ADMIN";
  const collapseConversationHistory = false && role === "GROUP_ADMIN";
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
  const starterPromptGroups = getStarterPromptGroups(conversationContext, quickQuestions);
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
    if (role !== "GROUP_ADMIN") setViewMode("debug");
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
    setSelectedPromptLabel(null);
    setError(null);
    setActiveFrame(null);
    setStatus("idle");
  }

  function selectConversation(conversationId: string) {
    setActiveConversationId(conversationId);
    setQuestion("");
    setContextHint(null);
    setSelectedPromptLabel(null);
    setError(null);
    setActiveFrame(null);
    if (!isLoading) setStatus("idle");
  }

  async function run(nextQuestion?: string, options?: { useContextRewrite?: boolean; promptLabel?: string | null }) {
    const rawQuestion = (nextQuestion ?? question).trim();
    if (!rawQuestion) return;

    const currentConversationId = activeConversation.id;
    const currentContext = conversationContext;
    const rewritten = options?.useContextRewrite === false ? { rewritten: rawQuestion, usedContext: false } : rewriteFollowUpQuestion(rawQuestion, currentContext);
    const finalQuestion = rewritten.rewritten;
    const effectiveMode = resolveActionMode(rawQuestion, actionMode);
    const promptLabel = options?.promptLabel ?? null;

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
    setSelectedPromptLabel(promptLabel);
    setError(null);
    if (nextQuestion) setQuestion(nextQuestion);
    setContextHint(null);

    try {
      const payload = {
        question: finalQuestion,
        context: {
          time_scope: timeScope,
          language: "zh-CN",
          external_benchmark: externalBenchmark,
          analysis_focus: inferAnalysisFocus(rawQuestion, effectiveMode),
          conversation_context: buildSemanticConversationContext(currentContext),
        },
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
    void run(value, { promptLabel: value });
  }

  function handleStarterPrompt(value: string) {
    setQuestion(value);
    setContextHint(null);
    void run(value, { useContextRewrite: false, promptLabel: value });
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

        {!collapseConversationHistory ? (
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
        ) : (
          <details className="conversation-history-drawer panel" data-testid="conversation-history-drawer">
            <summary data-testid="conversation-history-toggle">查看会话历史</summary>
            <section className="conversation-panel" data-testid="conversation-panel">
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
            </section>
          </details>
        )}

        {collapseConversationHistory && contextSnapshotItems.length ? (
          <div className="context-snapshot context-snapshot-inline" data-testid="context-snapshot">
            <span className="context-snapshot-label">当前承接</span>
            {contextSnapshotItems.map((item) => (
              <span className="context-snapshot-item" key={item}>{item}</span>
            ))}
          </div>
        ) : null}

        <div className="quick-strip">
          <PromptBank
            title="常用切入"
            description="点一下就能直接进入经营对话，不用先学系统语法。"
            groups={starterPromptGroups}
            selectedPrompt={selectedPromptLabel}
            onSelect={handleStarterPrompt}
            disabled={isLoading}
            feedbackLabel={selectedPromptLabel && isLoading ? `正在处理：${selectedPromptLabel}` : selectedPromptLabel ? `已选：${selectedPromptLabel}` : null}
            dataTestId="starter-prompts"
          />
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
                    selectedPromptLabel={selectedPromptLabel}
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
                <LoadingCard frame={activeFrame} step={loadingStep} promptLabel={selectedPromptLabel} />
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

              <label className="field view-mode-field">
                <span className="field-label">视图模式</span>
                <button
                  type="button"
                  className={`toggle-btn ${viewMode === "debug" ? "active" : ""}`}
                  onClick={() => setViewMode((current) => (current === "debug" ? "management" : "debug"))}
                  data-testid="view-mode-toggle"
                >
                  {VIEW_MODE_OPTIONS.find((option) => option.value === viewMode)?.label || "管理层视图"}
                </button>
                <span className="field-help">
                  {VIEW_MODE_OPTIONS.find((option) => option.value === viewMode)?.helper}
                </span>
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
