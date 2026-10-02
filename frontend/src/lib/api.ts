import type { AskResponse, ScenarioResponse, UserProfile } from "../types/agent";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function askAgent(message: string, threadId?: string | null, signal?: AbortSignal): Promise<AskResponse> {
  return request<AskResponse>("/api/v1/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, thread_id: threadId || null }),
    signal,
  });
}

export function restoreConversation(threadId: string, signal?: AbortSignal): Promise<AskResponse> {
  return request(`/api/v1/ask/${encodeURIComponent(threadId)}`, { signal });
}

export function compareScenarios(baseline: UserProfile, profile: UserProfile, signal?: AbortSignal): Promise<ScenarioResponse> {
  return request("/api/v1/scenarios", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({baseline, scenarios: [{name: "변경 조건", profile}]}), signal});
}

async function request<T>(path: string, options: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {...options,
    signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(180000)]) : AbortSignal.timeout(180000)});

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error("서버 응답을 읽지 못했습니다.");
  }

  if (!response.ok) {
    const detail = typeof payload === "object" && payload && "detail" in payload
      ? String((payload as { detail: unknown }).detail)
      : "요청을 처리하지 못했습니다.";
    throw new Error(detail);
  }

  return payload as T;
}
