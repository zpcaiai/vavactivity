import { useAuthStore } from "@/stores/auth";

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export interface AiConversation {
  id: string;
  conversation_number: string;
  status: string;
  locale: string;
  primary_topic?: string | null;
  latest_risk_level?: string | null;
  memory_consent_status: string;
  created_at?: string;
  messages?: AiMessage[];
}

export interface AiMessage {
  id: string;
  turn_number: number;
  role: "user" | "assistant";
  message_type: string;
  content: string;
  status: string;
  created_at: string;
}

export interface AiTurnResult {
  turn_id: string;
  message_id: string;
  message: string;
  status: string;
  citations: Array<{
    citation_id: string;
    document_code: string;
    excerpt?: string;
    source_locator?: Record<string, unknown>;
  }>;
  referral?: { risk_level: string; risk_category: string };
  structured?: { action_suggestions?: string[] };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const auth = useAuthStore();
  await auth.bootstrap();
  const headers = new Headers(init.headers);
  if (auth.accessToken) headers.set("Authorization", `Bearer ${auth.accessToken}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    credentials: "include",
    headers
  });
  const payload = (await response.json()) as { data: T; error?: { message: string } };
  if (!response.ok) throw new Error(payload.error?.message ?? "AI assistant request failed");
  return payload.data;
}

export const aiAssistantApi = {
  list: () => request<{ items: AiConversation[] }>("/ai/conversations"),
  detail: (id: string) => request<AiConversation>(`/ai/conversations/${id}`),
  create: (locale: string, memoryOptIn: boolean) =>
    request<AiConversation>("/ai/conversations", {
      method: "POST",
      body: JSON.stringify({
        locale,
        user_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai",
        consent_version: "2026-08-batch-10",
        accept_ai_disclosure: true,
        memory_opt_in: memoryOptIn
      })
    }),
  send: (id: string, content: string, locale: string) =>
    request<AiTurnResult>(`/ai/conversations/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({
        client_message_id: `web-${crypto.randomUUID()}`,
        content,
        locale
      })
    }),
  setMemory: (id: string, enabled: boolean) =>
    request<{ id: string; memory_consent_status: string }>(
      `/ai/conversations/${id}/memory-consent`,
      { method: "PATCH", body: JSON.stringify({ enabled }) }
    ),
  feedback: (messageId: string, rating: "up" | "down") =>
    request(`/ai/messages/${messageId}/feedback`, {
      method: "POST",
      body: JSON.stringify({ rating, reported: false })
    }),
  confirmTool: (id: string, toolCode: string, argumentsValue: Record<string, unknown>) =>
    request<{ confirmation_token: string }>(`/ai/conversations/${id}/tool-confirmations`, {
      method: "POST",
      body: JSON.stringify({ tool_code: toolCode, arguments: argumentsValue })
    }),
  executeTool: (
    id: string,
    toolCode: string,
    confirmationToken: string,
    argumentsValue: Record<string, unknown>
  ) =>
    request<{ status: string; output: Record<string, unknown> }>(
      `/ai/conversations/${id}/tools/${toolCode}/execute`,
      {
        method: "POST",
        body: JSON.stringify({
          confirmation_token: confirmationToken,
          arguments: argumentsValue,
          idempotency_key: `web-tool-${crypto.randomUUID()}`
        })
      }
    ),
  remove: (id: string) => request(`/ai/conversations/${id}`, { method: "DELETE" })
};
