import { catalogApi } from "@/features/catalog/api";

const base = "/admin/trust-safety";
export type SafetyAdminRow = Record<string, unknown> & { id?: string; status?: string };

/**
 * The case state machine, mirrored from the backend's CASE_TRANSITIONS. The
 * console used to offer two hard-coded edges and send whatever the operator
 * clicked, so most buttons produced SAFETY_CASE_TRANSITION_INVALID. Deriving
 * the options from the row's own status means the console can only ever offer
 * a move the backend will accept.
 */
export const CASE_TRANSITIONS: Record<string, string[]> = {
  open: ["triaged", "assigned", "closed"],
  triaged: ["assigned", "investigating", "closed"],
  assigned: ["investigating", "pending_action", "resolved"],
  investigating: ["pending_action", "resolved"],
  pending_action: ["investigating", "resolved"],
  resolved: ["closed", "reopened"],
  closed: ["reopened"],
  reopened: ["assigned", "investigating"]
};

/** Restrictions the backend treats as high impact — they need a second approver. */
export const HIGH_IMPACT_RESTRICTIONS = [
  "account_permanently_disabled",
  "account_temporarily_suspended",
  "reverification_required"
];

export const RESTRICTION_TYPES = [
  "profile_hidden",
  "profile_edit_review_required",
  "recommendation_disabled",
  "like_disabled",
  "invitation_disabled",
  "contact_exchange_disabled",
  "relationship_interaction_frozen",
  "activity_registration_disabled",
  "ai_write_actions_disabled",
  "communication_rate_limited",
  "reverification_required",
  "account_temporarily_suspended",
  "account_permanently_disabled"
];

export const safetyAdminApi = {
  queue: (section: string) =>
    catalogApi<SafetyAdminRow[]>(`${base}/${encodeURIComponent(section)}`),

  transitionCase: (id: string, targetStatus: string) =>
    catalogApi<SafetyAdminRow>(`${base}/cases/${encodeURIComponent(id)}/transition`, {
      method: "POST",
      body: JSON.stringify({ target_status: targetStatus })
    }),

  assignCase: (id: string, assignedTo: string, assignedTeam: string, expectedVersion: number) =>
    catalogApi<SafetyAdminRow>(`${base}/cases/${encodeURIComponent(id)}/assign`, {
      method: "POST",
      body: JSON.stringify({
        assigned_to: assignedTo,
        assigned_team: assignedTeam,
        expected_version: expectedVersion
      })
    }),

  decideModeration: (id: string, payload: Record<string, unknown>) =>
    catalogApi<SafetyAdminRow>(`${base}/moderation/${encodeURIComponent(id)}/decisions`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),

  decideAppeal: (id: string, payload: Record<string, unknown>) =>
    catalogApi<SafetyAdminRow>(`${base}/appeals/${encodeURIComponent(id)}/decision`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),

  activateRule: (id: string) =>
    catalogApi<SafetyAdminRow>(`${base}/rules/${encodeURIComponent(id)}/activate`, {
      method: "POST"
    }),

  createRestriction: (payload: Record<string, unknown>) =>
    catalogApi<SafetyAdminRow>(`${base}/restrictions`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),

  approveRestriction: (id: string) =>
    catalogApi<SafetyAdminRow>(`${base}/restrictions/${encodeURIComponent(id)}/approve`, {
      method: "POST"
    }),

  liftRestriction: (id: string, reason: string) =>
    catalogApi<SafetyAdminRow>(`${base}/restrictions/${encodeURIComponent(id)}/lift`, {
      method: "POST",
      body: JSON.stringify({ reason })
    })
};
