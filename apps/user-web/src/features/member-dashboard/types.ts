/**
 * Member dashboard types (B18 / DASH-001).
 *
 * Two things about this contract shape the UI and are easy to get wrong:
 *
 * 1. A section that failed comes back as `{ available: false, error_code }`
 *    inside `sections`, *and* its key is listed in `degraded`. It carries no
 *    count, because a zero would read as "nothing to do" when the truth is
 *    "we could not find out".
 * 2. A section the member is not eligible for is absent from both `sections`
 *    and `degraded`. "Not for you" and "temporarily broken" must not look
 *    alike, so the UI must never render a placeholder for a missing key.
 *
 * The server ships no display copy — only `title_code` identifiers — so every
 * label here is localized from a code.
 */

export type DashboardSectionKey =
  | "survey_tasks"
  | "result_letters"
  | "registrations"
  | "mutual_selection"
  | "matchmaking"
  | "notifications";

export type DashboardTaskType =
  | "survey_pending"
  | "mutual_selection_pending"
  | "result_letter_unread"
  | "registration_upcoming"
  | "matchmaking_attempt_available"
  | "notification_unread";

export type TaskPriority = "urgent" | "high" | "normal" | "low";

export interface DashboardTask {
  task_type: DashboardTaskType;
  /** Stable per-member key. Dismissals are keyed on it. */
  task_key: string;
  section: DashboardSectionKey;
  subject_id: string;
  /** Server-owned route. Never rebuild this path in the client. */
  deep_link: string;
  priority: TaskPriority;
  due_at: string | null;
  activity_id: string | null;
  title_code: string;
  metadata: Record<string, unknown>;
}

export interface DashboardSectionOk {
  key: DashboardSectionKey;
  available?: true;
  count: number;
  items: DashboardTask[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  [extra: string]: unknown;
}

export interface DashboardSectionUnavailable {
  key: DashboardSectionKey;
  available: false;
  error_code: string;
}

export type DashboardSection = DashboardSectionOk | DashboardSectionUnavailable;

export function isSectionAvailable(section: DashboardSection): section is DashboardSectionOk {
  return (section as DashboardSectionUnavailable).available !== false;
}

export interface DashboardView {
  sections: Partial<Record<DashboardSectionKey, DashboardSection>>;
  /** Keys whose source module failed. Never includes ineligible sections. */
  degraded: DashboardSectionKey[];
  counts: Partial<Record<DashboardSectionKey, number>>;
  total_open_tasks: number;
  generated_at: string;
  relationship_gate: { matchmaking_available: boolean };
}

export interface DashboardPreferences {
  hidden_sections: DashboardSectionKey[];
  page_size: number;
}

export interface DismissalResult {
  task_key: string;
  dismissed: boolean;
}
