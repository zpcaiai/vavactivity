/**
 * Post-event closure types (B09 mutual selection, B10 survey, B11 result letters).
 *
 * These mirror the API envelopes exactly. Where the server owns a rule — the
 * selection ceiling, the edit deadline, which letters exist — the type carries
 * the server's value rather than a local constant, so the UI cannot drift from
 * the enforcement.
 */

export interface PassReasonOption {
  reason_code: string;
  requires_note: boolean;
}

export interface FrozenCandidate {
  user_id: string;
  display_name: string;
  group_id: string | null;
}

export interface CandidateBoard {
  snapshot_id: string;
  snapshot_version: number;
  /** Server-enforced ceiling. Never hardcode 3 in a component. */
  max_selections: number;
  min_selections: number;
  edit_window_hours: number;
  pass_reasons: PassReasonOption[];
  candidates: FrozenCandidate[];
}

export type SelectionStatus = "not_started" | "draft" | "submitted" | "withdrawn";

export interface SelectionState {
  snapshot_id: string;
  submission_id?: string;
  status: SelectionStatus;
  selection_count?: number;
  selected_user_ids: string[];
  no_selection_reason_code?: string | null;
  no_selection_reason_note?: string | null;
  submitted_at?: string | null;
  /** After this instant the server refuses an edit. */
  editable_until?: string | null;
  version?: number;
}

export interface SelectionPayload {
  selected_user_ids: string[];
  no_selection_reason_code?: string | null;
  no_selection_reason_note?: string | null;
  status: "draft" | "submitted";
}

export type SurveyTaskStatus = "pending" | "in_progress" | "completed" | "expired" | "waived";

export interface SurveyTask {
  id: string;
  assignment_id: string;
  activity_id: string;
  status: SurveyTaskStatus;
  due_at: string;
  completed_at: string | null;
  display_timezone: string;
  opens_at: string | null;
  title: string;
}

export type SurveyQuestionType =
  | "rating"
  | "segment_rating"
  | "single_choice"
  | "multi_choice"
  | "open_text"
  | "boolean";

export interface SurveyQuestionConfig {
  scale_min?: number;
  scale_max?: number;
  options?: string[];
  max_length?: number;
  min_selections?: number;
  max_selections?: number;
}

export interface SurveyQuestion {
  id: string;
  question_code: string;
  question_type: SurveyQuestionType;
  prompt: string;
  help_text: string | null;
  is_required: boolean;
  /** Answered once per participant rather than once per event. */
  per_subject: boolean;
  position: number;
  config: SurveyQuestionConfig;
}

export interface SurveyDefinition {
  id: string;
  survey_code: string;
  semantic_version: string;
  title: string;
  description: string | null;
  questions: SurveyQuestion[];
}

export interface SurveySubject {
  user_id: string;
  display_name: string;
}

export interface SurveyAnswer {
  question_code: string;
  rating_value?: number | null;
  boolean_value?: boolean | null;
  choice_values?: string[];
  text_value?: string | null;
  subject_user_id?: string | null;
}

export interface SurveyDetail {
  assignment_id: string;
  activity_id: string;
  definition: SurveyDefinition;
  opens_at: string | null;
  deadline_at: string;
  display_timezone: string;
  subjects: SurveySubject[];
  response: {
    status: "draft" | "submitted";
    submitted_at: string | null;
    edit_count: number;
    answers: SurveyAnswer[];
  } | null;
}

export interface SurveyResponsePayload {
  answers: SurveyAnswer[];
  status: "draft" | "submitted";
}

export type LetterOutcome = "mutual_match" | "no_match" | "not_eligible";

export interface ResultLetterSummary {
  id: string;
  activity_id: string;
  outcome: LetterOutcome;
  published_at: string | null;
  read_at: string | null;
}

export interface ResultLetterDetail extends ResultLetterSummary {
  version: number;
  subject: string;
  body: string;
  content_hash: string;
}
