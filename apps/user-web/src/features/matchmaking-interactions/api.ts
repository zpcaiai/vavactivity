import { useAuthStore } from "@/stores/auth";

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export type InteractionRow = Record<string, unknown> & {
  status?: string;
  like_id?: string;
  skip_id?: string;
  mutual_match_id?: string;
  invitation_id?: string;
  invitation_version?: number;
  contact_exchange_id?: string;
  contact_exchange_request_id?: string;
  role?: "sender" | "recipient";
};

function idempotencyKey(operation: string) {
  return `${operation}-${crypto.randomUUID()}`;
}

async function interactionApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  const auth = useAuthStore();
  await auth.bootstrap();
  const headers = new Headers(init.headers);
  if (auth.accessToken) headers.set("Authorization", `Bearer ${auth.accessToken}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers,
    credentials: "include"
  });
  const payload = (await response.json()) as {
    data: T;
    error?: { message: string; code?: string };
  };
  if (!response.ok) {
    const error = new Error(payload.error?.message ?? "互动服务请求失败");
    (error as Error & { code?: string }).code = payload.error?.code;
    throw error;
  }
  return payload.data;
}

function write<T>(path: string, operation: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  headers.set("Idempotency-Key", idempotencyKey(operation));
  return interactionApi<T>(path, { ...init, headers });
}

export const matchmakingInteractionsApi = {
  like: (recommendationItemId: string) =>
    write<InteractionRow>(
      `/recommendations/${encodeURIComponent(recommendationItemId)}/like`,
      "like",
      { method: "POST" }
    ),
  skip: (
    recommendationItemId: string,
    payload: { skip_type: string; reason_code?: string; reason_details?: string }
  ) =>
    write<InteractionRow>(
      `/recommendations/${encodeURIComponent(recommendationItemId)}/skip`,
      "skip",
      { method: "POST", body: JSON.stringify(payload) }
    ),
  outgoingLikes: () =>
    interactionApi<InteractionRow[]>("/account/matchmaking/outgoing-likes"),
  skips: () => interactionApi<InteractionRow[]>("/account/matchmaking/skips"),
  withdrawLike: (likeId: string) =>
    write<InteractionRow>(
      `/account/matchmaking/likes/${encodeURIComponent(likeId)}`,
      "withdraw-like",
      { method: "DELETE" }
    ),
  withdrawSkip: (skipId: string) =>
    write<InteractionRow>(
      `/account/matchmaking/skips/${encodeURIComponent(skipId)}`,
      "withdraw-skip",
      { method: "DELETE" }
    ),
  matches: () => interactionApi<InteractionRow[]>("/account/matchmaking/mutual-matches"),
  match: (matchId: string) =>
    interactionApi<InteractionRow>(
      `/account/matchmaking/mutual-matches/${encodeURIComponent(matchId)}`
    ),
  closeMatch: (matchId: string, reasonCode?: string) =>
    write<InteractionRow>(
      `/account/matchmaking/mutual-matches/${encodeURIComponent(matchId)}/close`,
      "close-match",
      { method: "POST", body: JSON.stringify({ reason_code: reasonCode ?? null }) }
    ),
  sendInvitation: (matchId: string, message: string) =>
    write<InteractionRow>(
      `/account/matchmaking/mutual-matches/${encodeURIComponent(matchId)}/invitations`,
      "send-invitation",
      { method: "POST", body: JSON.stringify({ message: message || null }) }
    ),
  invitations: () => interactionApi<InteractionRow[]>("/account/matchmaking/invitations"),
  invitation: (invitationId: string) =>
    interactionApi<InteractionRow>(
      `/account/matchmaking/invitations/${encodeURIComponent(invitationId)}`
    ),
  invitationDecision: (
    invitationId: string,
    action: "accept" | "decline" | "cancel",
    version: number,
    reasonCode?: string
  ) =>
    write<InteractionRow>(
      `/account/matchmaking/invitations/${encodeURIComponent(invitationId)}/${action}`,
      `invitation-${action}`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_invitation_version: version,
          reason_code: action === "decline" ? reasonCode ?? null : undefined
        })
      }
    ),
  requestContactExchange: (matchId: string) =>
    write<InteractionRow>(
      `/account/matchmaking/mutual-matches/${encodeURIComponent(matchId)}/contact-exchange`,
      "request-contact-exchange",
      { method: "POST" }
    ),
  contactExchange: (exchangeId: string) =>
    interactionApi<InteractionRow>(
      `/account/matchmaking/contact-exchanges/${encodeURIComponent(exchangeId)}`
    ),
  consentContactExchange: (
    exchangeId: string,
    selectedContactPointIds: string[],
    platformOnly: boolean
  ) =>
    write<InteractionRow>(
      `/account/matchmaking/contact-exchanges/${encodeURIComponent(exchangeId)}/consent`,
      "contact-consent",
      {
        method: "POST",
        body: JSON.stringify({
          selected_contact_point_ids: selectedContactPointIds,
          platform_only: platformOnly
        })
      }
    ),
  withdrawContactConsent: (exchangeId: string) =>
    write<InteractionRow>(
      `/account/matchmaking/contact-exchanges/${encodeURIComponent(exchangeId)}/consent`,
      "contact-withdraw",
      { method: "DELETE" }
    ),
  revealToken: (exchangeId: string, contactPointId: string) =>
    interactionApi<{ reveal_token: string; expires_at: string }>(
      `/account/matchmaking/contact-exchanges/${encodeURIComponent(exchangeId)}/reveal-token`,
      { method: "POST", body: JSON.stringify({ contact_point_id: contactPointId }) }
    ),
  reveal: (exchangeId: string, revealToken: string) =>
    interactionApi<{ type: string; value: string; disclosure: string }>(
      `/account/matchmaking/contact-exchanges/${encodeURIComponent(exchangeId)}/reveal`,
      { method: "POST", body: JSON.stringify({ reveal_token: revealToken }) }
    )
};

export const interactionApiForTests = { interactionApi, idempotencyKey };
