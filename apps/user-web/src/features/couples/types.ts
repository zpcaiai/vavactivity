/**
 * Couples binding and SCOPE assessment types (B16 COUPLE-001 / SCOPE-001).
 *
 * The rule that shapes this whole UI: the report does not exist until both
 * partners have submitted. Until then the server returns `report_ready: false`
 * with a `waiting_on` list and writes nothing — no partial score, no preview.
 * So the client must never compute or display an interim result, and must
 * never read the partner's raw answers: those are sealed per-owner and the
 * server enforces it at a single choke point.
 */

export type RelationshipKind = "dating" | "engaged" | "married";
export type InvitationStatus = "pending" | "accepted" | "rejected" | "cancelled" | "expired";
export type RelationshipState = "active" | "unbound";

export interface CoupleInvitation {
  invitation_id: string;
  direction: "incoming" | "outgoing";
  counterparty_user_id: string;
  relationship_kind: RelationshipKind;
  status: InvitationStatus;
  note: string | null;
  expires_at: string | null;
  responded_at: string | null;
  /** Server-computed: whether this invitation can still be acted on. */
  actionable: boolean;
}

export interface CoupleRelationship {
  relationship_id: string;
  state: RelationshipState;
  relationship_kind: RelationshipKind;
  partner_user_id: string;
  bound_at: string | null;
}

export interface ScopeVersion {
  id: string;
  version_label: string;
  status: string;
  algorithm_version: string;
  published_at: string | null;
}

export type AssessmentState = "collecting" | "scoring" | "completed" | "cancelled";
export type ParticipantState = "not_started" | "in_progress" | "submitted";

export interface ScopePartnerStatus {
  user_id: string;
  status: ParticipantState;
  /** Progress only. Never the partner's answers. */
  answer_count: number;
}

export interface ScopeAssessment {
  assessment_id: string;
  state: AssessmentState;
  version_id: string;
  my_status: ParticipantState;
  /** The caller's own answers, keyed by question id. */
  my_answers: Record<string, unknown>;
  partner: ScopePartnerStatus | null;
}

export interface ScopeStartResult {
  assessment_id: string;
  state: AssessmentState;
  created: boolean;
  /** Free assessments left for this pair after this call. */
  free_benefit_remaining: number;
}

export interface ScopeSaveResult {
  assessment_id: string;
  status: ParticipantState;
  answer_count: number;
  /** Present only after a submit. */
  report_ready?: boolean;
  waiting_on?: string[];
  reason_code?: string;
}

export interface ScopeReport {
  assessment_id: string;
  algorithm_version: string;
  scores: Record<string, number>;
  scores_fingerprint: string;
  /** AI narrative, kept in its own field and never merged into `scores`. */
  advice: string | null;
  advice_status: string;
  generated_at: string;
  /** Canonical display order for the score dimensions. */
  dimensions: string[];
}
