import { useAuthStore } from "@/stores/auth";
import { resolveApiBaseUrl } from "@/config/api";

const baseUrl = resolveApiBaseUrl();

export interface ActivityTicket {
  id: string;
  ticket_code: string;
  name: string;
  catalog_product_id: string;
  catalog_sku_id: string;
  waitlist_enabled: boolean;
  description?: string | null;
  eligibility_notice?: string | null;
  prices: Array<{ currency: string; unit_amount_minor: number; billing_type: string }>;
  availability: { status: "available" | "limited" | "sold_out" | "hidden"; remaining?: number | null };
}

export interface PublicActivity {
  id: string;
  activity_code: string;
  status: string;
  format: string;
  title: string;
  slug: string;
  summary?: string | null;
  description_blocks: Array<Record<string, unknown>>;
  timezone: string;
  starts_at: string;
  ends_at: string;
  locations: Array<Record<string, unknown>>;
  sessions: Array<Record<string, unknown>>;
  ticket_types: ActivityTicket[];
  registration_form: {
    schema_version: number;
    form_schema: {
      fields: Array<{
        key: string;
        type: string;
        label?: string;
        required?: boolean;
        options?: Array<{ label: string; value: string }>;
      }>;
    };
    consent_requirements: Array<{ key: string; label?: string; required?: boolean }>;
  };
}

export interface ActivityRegistration {
  id: string;
  registration_number: string;
  activity_id: string;
  status: string;
  attendance_status: string;
  order_id?: string | null;
  entitlement_id?: string | null;
  user_visible_review_message?: string | null;
}

export interface ActivityWaitlistEntry {
  id: string;
  activity_id: string;
  ticket_type_id: string;
  registration_id: string;
  status: string;
  sequence_number: number;
  promotion_offer_expires_at?: string | null;
}

export interface ActivityParticipant {
  user_id: string;
  display_name: string;
  brief_introduction?: string | null;
}

export interface ActivityMatch {
  id: string;
  activity_id: string;
  participant_user_id: string;
  status: string;
  matched_at: string;
  contact_disclosed: false;
}

export interface ActivityGroup {
  plan_id: string;
  group_id: string;
  group_code: string;
  display_name?: string | null;
  members: Array<{ display_name: string; brief_introduction?: string | null }>;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const auth = useAuthStore();
  await auth.bootstrap();
  const headers = new Headers(init.headers);
  if (auth.accessToken) headers.set("Authorization", `Bearer ${auth.accessToken}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers, credentials: "include" });
  const payload = (await response.json()) as {
    data: T;
    error?: { message: string };
  };
  if (!response.ok) throw new Error(payload.error?.message ?? "活动服务暂时不可用");
  return payload.data;
}

export const activityApi = {
  list: (locale: string) =>
    request<{ items: PublicActivity[] }>(`/activities?locale=${encodeURIComponent(locale)}`),
  detail: (slug: string, locale: string) =>
    request<PublicActivity>(
      `/activities/${encodeURIComponent(slug)}?locale=${encodeURIComponent(locale)}`
    ),
  register: (
    activityId: string,
    ticketTypeId: string,
    locale: string,
    formResponse: Record<string, unknown>,
    acceptedConsents: string[]
  ) =>
    request<ActivityRegistration>(`/activities/${activityId}/registrations`, {
      method: "POST",
      body: JSON.stringify({
        ticket_type_id: ticketTypeId,
        locale,
        currency_code: "USD",
        form_response: formResponse,
        accepted_consents: acceptedConsents
      })
    }),
  registrations: () =>
    request<{ items: ActivityRegistration[] }>("/account/activity-registrations"),
  registration: (registrationId: string) =>
    request<ActivityRegistration>(`/account/activity-registrations/${registrationId}`),
  cancelRegistration: (registrationId: string, reason: string) =>
    request<ActivityRegistration>(`/account/activity-registrations/${registrationId}/cancel`, {
      method: "POST",
      body: JSON.stringify({ reason_code: "user_cancelled", reason })
    }),
  waitlist: () => request<{ items: ActivityWaitlistEntry[] }>("/account/activity-waitlist"),
  acceptWaitlist: (entryId: string) =>
    request<ActivityRegistration>(`/account/activity-waitlist/${entryId}/accept`, {
      method: "POST"
    }),
  declineWaitlist: (entryId: string, reason: string) =>
    request<ActivityWaitlistEntry>(`/account/activity-waitlist/${entryId}/decline`, {
      method: "POST",
      body: JSON.stringify({ reason_code: "user_declined", reason })
    }),
  access: (activityId: string) =>
    request<PublicActivity>(`/account/activity-registrations/${activityId}/access`),
  credential: (activityId: string) =>
    request<{ token: string; valid_from: string; valid_until: string }>(
      `/account/activity-registrations/${activityId}/checkin-credential`,
      { method: "POST" }
    ),
  saveParticipantProfile: (
    activityId: string,
    value: { display_name: string; brief_introduction: string; visibility_status: string; consent: boolean }
  ) =>
    request(`/account/activities/${activityId}/participant-profile`, {
      method: "PUT",
      body: JSON.stringify(value)
    }),
  participants: (activityId: string) =>
    request<{ items: ActivityParticipant[] }>(`/account/activities/${activityId}/participants`),
  choices: (activityId: string) =>
    request<{ items: Array<{ chosen_user_id: string; choice: string }> }>(
      `/account/activities/${activityId}/choices`
    ),
  choose: (activityId: string, participantId: string, choice: "interested" | "pass") =>
    request(`/account/activities/${activityId}/choices`, {
      method: "PUT",
      body: JSON.stringify({ chosen_user_id: participantId, choice })
    }),
  withdrawChoice: (activityId: string, participantId: string) =>
    request(`/account/activities/${activityId}/choices/${participantId}`, { method: "DELETE" }),
  group: (activityId: string) =>
    request<ActivityGroup>(`/account/activities/${activityId}/group`),
  matches: () => request<{ items: ActivityMatch[] }>("/account/activity-mutual-choices")
};
