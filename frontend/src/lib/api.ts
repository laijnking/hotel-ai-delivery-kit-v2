const defaultApiUrl = "/api/v1/ai/query";
const API_URL = import.meta.env.VITE_API_URL || defaultApiUrl;
const REPORT_API_URL = import.meta.env.VITE_REPORT_API_URL || API_URL.replace("/ai/query", "/ai/report");
const SETTINGS_API_URL = import.meta.env.VITE_SETTINGS_API_URL || API_URL.replace("/ai/query", "/system/settings");
const INTENT_PREVIEW_API_URL = import.meta.env.VITE_INTENT_PREVIEW_API_URL || API_URL.replace("/ai/query", "/ai/intent-preview");
const REQUEST_TIMEOUT_MS = 90000;

export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(message: string, status: number, payload: unknown = null) {
    super(message);
    this.name = "ApiError";
    Object.setPrototypeOf(this, ApiError.prototype);
    this.status = status;
    this.payload = payload;
  }
}

async function readBody(response: Response) {
  const text = await response.text();
  if (!text) return null;

  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function getErrorMessage(payload: unknown, status: number) {
  if (typeof payload === "string" && payload.trim()) return payload.trim();
  if (payload && typeof payload === "object") {
    const maybeMessage = (payload as { message?: unknown; detail?: unknown }).message ?? (payload as { message?: unknown; detail?: unknown }).detail;
    if (typeof maybeMessage === "string" && maybeMessage.trim()) return maybeMessage.trim();
    if (maybeMessage && typeof maybeMessage === "object") {
      const nestedMessage = (maybeMessage as { message?: unknown; error?: unknown; stage?: unknown }).message ?? (maybeMessage as { message?: unknown; error?: unknown; stage?: unknown }).error;
      const stage = (maybeMessage as { stage?: unknown }).stage;
      if (typeof nestedMessage === "string" && nestedMessage.trim()) {
        return typeof stage === "string" ? `${stage}：${nestedMessage}` : nestedMessage.trim();
      }
    }
  }
  if (status === 502) return "后端服务调用异常，请稍后重试；如果持续出现，可打开诊断信息查看具体阶段。";
  return `请求失败 (${status})`;
}

function normalizeNetworkError(error: unknown) {
  if (error instanceof DOMException && error.name === "AbortError") {
    return new ApiError("请求超时：系统仍在处理或后端服务不可用，请稍后重试。", 0);
  }
  if (error instanceof TypeError) {
    return new ApiError("无法连接后端服务：请确认本机服务已启动，或检查当前网络/端口访问。", 0);
  }
  return error;
}

async function requestJson(url: string, payload: any) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload),
      signal: controller.signal
    });

    const body = await readBody(response);

    if (!response.ok) {
      throw new ApiError(getErrorMessage(body, response.status), response.status, body);
    }

    return body;
  } catch (error) {
    throw normalizeNetworkError(error);
  } finally {
    clearTimeout(timeoutId);
  }
}

async function getJson(url: string) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(url, {
      method: "GET",
      headers: {
        "Content-Type": "application/json"
      },
      signal: controller.signal
    });

    const body = await readBody(response);

    if (!response.ok) {
      throw new ApiError(getErrorMessage(body, response.status), response.status, body);
    }

    return body;
  } catch (error) {
    throw normalizeNetworkError(error);
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function submitQuery(payload: any) {
  return requestJson(API_URL, payload);
}

export async function submitReport(payload: any) {
  return requestJson(REPORT_API_URL, payload);
}

export async function fetchSystemSettings() {
  return getJson(SETTINGS_API_URL);
}

export async function fetchIntentPreview(payload: any) {
  return requestJson(INTENT_PREVIEW_API_URL, payload);
}
