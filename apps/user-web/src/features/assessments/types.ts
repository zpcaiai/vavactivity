/**
 * Paid assessment types (B17 ASSESS-001).
 *
 * Contract facts that constrain this UI:
 *
 * - An entitlement is bound to one exact version. `version_id` is never
 *   resolved to "latest", so a member always answers and is scored on the
 *   version they bought.
 * - Draft versions are invisible to members even by direct id, because a draft
 *   may carry content whose licence has not been checked.
 * - `title_code` / `category_code` are identifiers, not display copy. The
 *   platform ships no assessment content, so every label is localized here
 *   from a code and an unknown code must degrade visibly rather than render
 *   blank.
 */

export type VersionStatus = "draft" | "published" | "retired";
export type ContentSource =
  | "administrator_authored"
  | "licensed_third_party"
  | "public_domain"
  | "partner_supplied";

export interface CatalogueEntry {
  id: string;
  product_id: string;
  product_code: string;
  title_code: string;
  category_code: string;
  semantic_version: string;
  status: VersionStatus;
  price_minor_units: number;
  currency: string;
  question_count: number;
  content_source: ContentSource;
}

export type EntitlementStatus = "active" | "consumed" | "expired" | "revoked";

export interface Entitlement {
  id: string;
  version_id: string;
  status: EntitlementStatus;
  attempts_granted: number;
  attempts_consumed: number;
  expires_at: string | null;
  semantic_version: string;
  algorithm_version: string;
  product_code: string;
}

export interface PurchaseResult {
  purchase_id: string;
  entitlement_id: string;
  version_id: string;
  semantic_version: string;
  /** True when the same order id was already recorded — a replay, not a
   *  second charge. */
  replayed: boolean;
}

export type AttemptStatus = "in_progress" | "submitted" | "expired" | "abandoned";

export interface AssessmentQuestion {
  question_code: string;
  dimension_code: string;
  prompt_text: string;
  scale_min: number;
  scale_max: number;
  position: number;
}

export interface Attempt {
  attempt_id: string;
  status: AttemptStatus;
  version_id: string;
  semantic_version: string;
  questions: AssessmentQuestion[];
  answers: Record<string, number>;
}

export interface AttemptSaveResult {
  attempt_id: string;
  status: AttemptStatus;
  answer_count: number;
  /** Present only after a submit. */
  report_id?: string;
}

export interface AssessmentReport {
  report_id: string;
  attempt_id: string;
  algorithm_version: string;
  scores: Record<string, number>;
  scores_fingerprint: string;
  advice: string | null;
  generated_at: string;
}
