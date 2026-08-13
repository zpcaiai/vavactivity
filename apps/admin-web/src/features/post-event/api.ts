import { catalogApi } from "@/features/catalog/api";

/**
 * Post-event closure console API (B09 candidate freeze, B11 letter review).
 *
 * Two rules the console has to respect rather than route around:
 *
 * 1. A frozen snapshot is never edited. Re-freezing supersedes it as a new
 *    version, so the "re-freeze" call must send `supersede_existing`.
 * 2. A review decision carries the hash of the text the reviewer actually
 *    read. If the draft changed in the meantime the server refuses the
 *    decision, so the console must send back the hash it was given — never a
 *    freshly-computed one.
 */

export type PostEventRow = Record<string, unknown> & { id?: string; status?: string };

export interface CandidateSnapshot extends PostEventRow {
  snapshot_version?: number;
  cutoff_at?: string;
  eligible_count?: number;
  excluded_count?: number;
  considered_count?: number;
  entries?: CandidateEntry[];
}

export interface CandidateEntry {
  user_id: string;
  display_name: string;
  gender: string | null;
  eligibility: "eligible" | "excluded";
  exclusion_kind: string | null;
  exclusion_reason: string | null;
  checked_in_at: string | null;
}

export interface LetterSummary extends PostEventRow {
  recipient_user_id?: string;
  outcome?: string;
  version?: number;
  content_hash?: string;
  generated_at?: string;
  published_at?: string | null;
}

export interface LetterDetail extends LetterSummary {
  subject: string;
  body: string;
  content_hash: string;
  matched_user_ids: string[];
  authored_by: string | null;
}

/** Only these exclusion kinds may be undone — attendance facts stay facts. */
export const REVERSIBLE_EXCLUSION_KINDS = ["manual"];

/**
 * The letter state machine, mirrored from the backend's `_LETTER_TRANSITIONS`.
 * Deriving the buttons from the row's own status means the console can only
 * offer a move the server will accept.
 */
export const LETTER_TRANSITIONS: Record<string, string[]> = {
  draft: ["pending_review", "revoked"],
  pending_review: ["approved", "rejected", "revoked"],
  rejected: ["draft", "revoked"],
  approved: ["published", "revoked"],
  published: ["revoked"],
  revoked: []
};

export const postEventAdminApi = {
  freeze(activityId: string, payload: { cutoff_at?: string | null; freeze_note?: string | null; supersede_existing: boolean }) {
    return catalogApi<CandidateSnapshot>(`/admin/activities/${activityId}/candidate-snapshots`, {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },

  snapshot(snapshotId: string, includeExcluded = true) {
    return catalogApi<CandidateSnapshot>(
      `/admin/candidate-snapshots/${snapshotId}?include_excluded=${includeExcluded}`
    );
  },

  /** Requires a typed reason; the server rejects anything under 4 characters. */
  exclude(snapshotId: string, userId: string, reason: string) {
    return catalogApi<PostEventRow>(`/admin/candidate-snapshots/${snapshotId}/exclusions`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId, reason })
    });
  },

  restore(snapshotId: string, userId: string, reason: string) {
    return catalogApi<PostEventRow>(`/admin/candidate-snapshots/${snapshotId}/restorations`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId, reason })
    });
  },

  matches(snapshotId: string) {
    return catalogApi<{ pairs: string[][]; count: number }>(
      `/admin/candidate-snapshots/${snapshotId}/matches`
    );
  },

  setSelectionPolicy(
    activityId: string,
    payload: {
      visibility_mode: string;
      max_selections: number;
      min_selections: number;
      edit_window_hours: number;
      allow_edit_after_submit: boolean;
    }
  ) {
    return catalogApi<PostEventRow>(`/admin/activities/${activityId}/selection-policy`, {
      method: "PUT",
      body: JSON.stringify({ ...payload, custom_rule: {} })
    });
  },

  passReasons(activityId: string) {
    return catalogApi<{ items: { reason_code: string; requires_note: boolean }[] }>(
      `/admin/activities/${activityId}/pass-reasons`
    );
  },

  upsertPassReason(
    activityId: string,
    payload: { reason_code: string; sort_order: number; requires_note: boolean; is_active: boolean }
  ) {
    return catalogApi<PostEventRow>(`/admin/activities/${activityId}/pass-reasons`, {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  },

  generateLetters(activityId: string, snapshotId: string, locale: string, regenerate: boolean) {
    return catalogApi<PostEventRow>(`/admin/activities/${activityId}/result-letters`, {
      method: "POST",
      body: JSON.stringify({ snapshot_id: snapshotId, locale, regenerate })
    });
  },

  letters(activityId: string, status?: string) {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return catalogApi<{ items: LetterSummary[] }>(
      `/admin/activities/${activityId}/result-letters${query}`
    );
  },

  letter(letterId: string) {
    return catalogApi<LetterDetail>(`/admin/result-letters/${letterId}`);
  },

  submitForReview(letterId: string) {
    return catalogApi<PostEventRow>(`/admin/result-letters/${letterId}/submit`, { method: "POST" });
  },

  /** `reviewedContentHash` must be the hash returned by `letter()`. */
  review(
    letterId: string,
    decision: "approved" | "rejected" | "changes_requested",
    reviewedContentHash: string,
    comment?: string
  ) {
    return catalogApi<PostEventRow>(`/admin/result-letters/${letterId}/review`, {
      method: "POST",
      body: JSON.stringify({
        decision,
        comment: comment ?? null,
        reviewed_content_hash: reviewedContentHash
      })
    });
  },

  publish(letterId: string, notify: boolean) {
    return catalogApi<PostEventRow>(`/admin/result-letters/${letterId}/publish`, {
      method: "POST",
      body: JSON.stringify({ notify })
    });
  },

  revoke(letterId: string, reason: string) {
    return catalogApi<PostEventRow>(`/admin/result-letters/${letterId}/revoke`, {
      method: "POST",
      body: JSON.stringify({ reason })
    });
  }
};

// ---------------------------------------------------------------------------
// B10 survey authoring
// ---------------------------------------------------------------------------

export type SurveyQuestionType =
  | "rating"
  | "segment_rating"
  | "single_choice"
  | "multi_choice"
  | "open_text"
  | "boolean";

export interface SurveyQuestionDraft {
  question_code: string;
  question_type: SurveyQuestionType;
  prompt: string;
  help_text?: string | null;
  is_required: boolean;
  /** Asks the question once per person the member met, not once overall. */
  per_subject: boolean;
  position: number;
  config: Record<string, unknown>;
}

export interface SurveyDefinition extends PostEventRow {
  definition_id?: string;
  survey_code?: string;
  semantic_version?: string;
  title?: string;
  status?: string;
  questions?: SurveyQuestionDraft[];
}

export interface SurveyAggregate extends PostEventRow {
  assignment_id?: string;
  response_count?: number;
  completion_rate_bps?: number;
  /** Suppressed below the k-anonymity floor; the server decides, not the UI. */
  suppressed?: boolean;
  suppression_reason?: string;
  questions?: Record<string, unknown>[];
}

export const surveyAdminApi = {
  /**
   * Create a draft definition. The platform ships no questionnaire content, so
   * every item here is authored by an operator (DEC-001).
   */
  createDefinition(payload: {
    survey_code: string;
    semantic_version: string;
    title: string;
    description?: string | null;
    default_locale?: string;
    questions: SurveyQuestionDraft[];
  }) {
    return catalogApi<SurveyDefinition>("/admin/surveys/definitions", {
      method: "POST",
      body: JSON.stringify({ scope: "post_event", default_locale: "zh-CN", ...payload })
    });
  },

  definition(definitionId: string) {
    return catalogApi<SurveyDefinition>(`/admin/surveys/definitions/${definitionId}`);
  },

  /** Publishing freezes the item set. Later edits need a new version. */
  publishDefinition(definitionId: string) {
    return catalogApi<SurveyDefinition>(`/admin/surveys/definitions/${definitionId}/publish`, {
      method: "POST"
    });
  },

  assign(
    activityId: string,
    payload: {
      definition_id: string;
      deadline_at: string;
      opens_at?: string | null;
      display_timezone?: string;
      reminder_offsets_hours?: number[];
      snapshot_id?: string | null;
    }
  ) {
    return catalogApi<PostEventRow>(`/admin/activities/${activityId}/survey-assignments`, {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },

  /** Materialize one task per eligible participant. Idempotent server-side. */
  generateTasks(assignmentId: string) {
    return catalogApi<PostEventRow>(`/admin/survey-assignments/${assignmentId}/tasks`, {
      method: "POST"
    });
  },

  sendReminders(assignmentId: string) {
    return catalogApi<PostEventRow>(`/admin/survey-assignments/${assignmentId}/reminders`, {
      method: "POST"
    });
  },

  aggregate(assignmentId: string) {
    return catalogApi<SurveyAggregate>(`/admin/survey-assignments/${assignmentId}/aggregate`);
  },

  /** Reopen one member's response. Requires a typed reason for the audit trail. */
  reopen(assignmentId: string, userId: string, reason: string) {
    return catalogApi<PostEventRow>(
      `/admin/survey-assignments/${assignmentId}/responses/${userId}/reopen`,
      { method: "POST", body: JSON.stringify({ reason }) }
    );
  }
};
