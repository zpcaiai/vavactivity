/**
 * Attendee preview and follow graph types (B14 ATT-001 / SOC-001).
 *
 * Two contract details the UI must respect rather than reinterpret:
 *
 * - Appearing in the preview is opt-in (DEC-002). `not_asked` is the state of
 *   every member who has never seen the prompt, and it behaves exactly like a
 *   refusal — so the UI must never render it as "pending" in a way that
 *   suggests the member is already listed.
 * - A follow, a like and a want-to-meet are three different things with three
 *   different visibilities. The server states `relation_kind` on every
 *   response precisely so a client cannot conflate them.
 */

export type PreviewConsentState = "not_asked" | "granted" | "declined" | "withdrawn";

export interface AttendeePreviewItem {
  user_id: string;
  display_name: string;
  avatar_url: string | null;
  intro_line: string | null;
}

export interface AttendeePreview {
  activity_id: string;
  items: AttendeePreviewItem[];
  /**
   * Consented attendees beyond the page limit. Safe to show: it counts only
   * people who already agreed to be visible. There is deliberately no count of
   * non-consenting attendees — that number would leak the headcount for a
   * small event.
   */
  additional_visible_count: number;
}

export interface PreviewConsent {
  registration_id: string;
  consent_state: PreviewConsentState;
  granted_at: string | null;
  withdrawn_at: string | null;
  intro_line: string | null;
}

export type FollowState = "active" | "unfollowed" | "blocked";
export type FollowAction = "created" | "reactivated" | "unchanged" | "removed";

export interface FollowResult {
  follower_id: string;
  followee_id: string;
  state: FollowState;
  action: FollowAction;
  /** Always `"follow"` here. Stated by the server so it cannot be mistaken
   *  for a mutual-selection signal. */
  relation_kind: "follow";
}

export interface FollowEdge {
  user_id: string;
  followed_at: string;
  /** Computed from the reverse active edge by the server, not from this page. */
  is_mutual: boolean;
  /** Lists are self-describing so they cannot be confused with likes/matches. */
  relation_kind: "follow";
}

export interface WantToMeetResult {
  user_id: string;
  target_user_id: string;
  activity_id: string;
  relation_kind: string;
  semantics: {
    is_event_scoped: boolean;
    visible_to_target: boolean;
  };
}

export interface SocialNotificationPreferences {
  followed_user_registered: boolean;
}
