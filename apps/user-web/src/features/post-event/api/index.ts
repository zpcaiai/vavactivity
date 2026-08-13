import { resolveApiBaseUrl } from "@/config/api";
import { useAuthStore } from "@/stores/auth";

import type {
  CandidateBoard,
  ResultLetterDetail,
  ResultLetterSummary,
  SelectionPayload,
  SelectionState,
  SurveyDetail,
  SurveyResponsePayload,
  SurveyTask
} from "@/features/post-event/types";

const baseUrl = resolveApiBaseUrl();

/**
 * Thin fetch wrapper for the post-event endpoints.
 *
 * The server's error `code` is preserved on the thrown error so callers can
 * localize the message from the code — the English `message` is for operators
 * and is never rendered to a member.
 */
export async function postEventApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  const auth = useAuthStore();
  await auth.bootstrap();
  const headers = new Headers(init.headers);
  if (auth.accessToken) headers.set("Authorization", `Bearer ${auth.accessToken}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers, credentials: "include" });
  const payload = (await response.json()) as {
    data: T;
    error?: { message: string; code?: string; details?: unknown[] };
  };
  if (!response.ok) {
    const error = new Error(payload.error?.message ?? "post-event request failed");
    (error as Error & { code?: string }).code = payload.error?.code;
    (error as Error & { details?: unknown[] }).details = payload.error?.details;
    throw error;
  }
  return payload.data;
}

export const postEventApiClient = {
  /** The frozen candidate list this member may choose from. */
  candidates(activityId: string): Promise<CandidateBoard> {
    return postEventApi<CandidateBoard>(`/account/activities/${activityId}/candidates`);
  },

  selection(activityId: string): Promise<SelectionState> {
    return postEventApi<SelectionState>(`/account/activities/${activityId}/selection`);
  },

  /** Saves a draft or submits. The server re-validates either way. */
  saveSelection(activityId: string, payload: SelectionPayload): Promise<SelectionState> {
    return postEventApi<SelectionState>(`/account/activities/${activityId}/selection`, {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  },

  surveyTasks(): Promise<{ items: SurveyTask[] }> {
    return postEventApi<{ items: SurveyTask[] }>("/account/survey-tasks");
  },

  survey(assignmentId: string): Promise<SurveyDetail> {
    return postEventApi<SurveyDetail>(`/account/surveys/${assignmentId}`);
  },

  saveSurvey(assignmentId: string, payload: SurveyResponsePayload): Promise<SurveyDetail> {
    return postEventApi<SurveyDetail>(`/account/surveys/${assignmentId}/response`, {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  },

  /** Only published letters are ever returned by the server. */
  resultLetters(): Promise<{ items: ResultLetterSummary[] }> {
    return postEventApi<{ items: ResultLetterSummary[] }>("/account/result-letters");
  },

  resultLetter(letterId: string): Promise<ResultLetterDetail> {
    return postEventApi<ResultLetterDetail>(`/account/result-letters/${letterId}`);
  }
};
