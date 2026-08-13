import { resolveApiBaseUrl } from "@/config/api";
import { useAuthStore } from "@/stores/auth";

import type {
  GenerationResult,
  MatchmakingEntitlement,
  RelationshipStatus,
  RelationshipStatusValue,
  WaitPoolState
} from "@/features/matchmaking-access/types";

const baseUrl = resolveApiBaseUrl();

export async function matchmakingAccessApi<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const auth = useAuthStore();
  await auth.bootstrap();
  const headers = new Headers(init.headers);
  if (auth.accessToken) headers.set("Authorization", `Bearer ${auth.accessToken}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers, credentials: "include" });
  const payload = (await response.json()) as {
    data: T;
    error?: { message: string; code?: string };
  };
  if (!response.ok) {
    const error = new Error(payload.error?.message ?? "matchmaking request failed");
    (error as Error & { code?: string }).code = payload.error?.code;
    throw error;
  }
  return payload.data;
}

export const matchmakingAccessApiClient = {
  relationshipStatus(): Promise<RelationshipStatus> {
    return matchmakingAccessApi<RelationshipStatus>("/account/relationship-status");
  },

  setRelationshipStatus(
    status: RelationshipStatusValue,
    reason?: string
  ): Promise<RelationshipStatus> {
    return matchmakingAccessApi<RelationshipStatus>("/account/relationship-status", {
      method: "PUT",
      body: JSON.stringify({ status, reason: reason ?? null })
    });
  },

  /** 403 here means the member is not single — that is a state, not an error. */
  entitlement(): Promise<MatchmakingEntitlement> {
    return matchmakingAccessApi<MatchmakingEntitlement>("/account/matchmaking/entitlement");
  },

  generate(): Promise<GenerationResult> {
    return matchmakingAccessApi<GenerationResult>("/account/matchmaking/generations", {
      method: "POST"
    });
  },

  waitPool(): Promise<WaitPoolState> {
    return matchmakingAccessApi<WaitPoolState>("/account/matchmaking/wait-pool");
  }
};
