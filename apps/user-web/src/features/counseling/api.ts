import { useAuthStore } from "@/stores/auth";

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export interface CounselingService {
  id: string;
  service_code: string;
  name: string;
  slug: string;
  summary?: string | null;
  description_blocks: Array<{ type?: string; text?: string }>;
  scope_notice: string;
  delivery_mode: string;
  participant_mode: string;
  duration_minutes: number;
  booking_mode: string;
  payment_policy: string;
  free_access: boolean;
  mentor_ids: string[];
  prices: Array<{ currency: string; unit_amount_minor: number }>;
}

export interface CounselingAppointment {
  id: string;
  appointment_number: string;
  service_id: string;
  mentor_id?: string | null;
  status: string;
  scheduled_starts_at?: string | null;
  scheduled_ends_at?: string | null;
  payment_status: string;
  summaries?: Array<Record<string, unknown>>;
  follow_ups?: Array<Record<string, unknown>>;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const auth = useAuthStore();
  await auth.bootstrap();
  const headers = new Headers(init.headers);
  if (auth.accessToken) headers.set("Authorization", `Bearer ${auth.accessToken}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers,
    credentials: "include"
  });
  const payload = (await response.json()) as { data: T; error?: { message: string } };
  if (!response.ok) throw new Error(payload.error?.message ?? "咨询服务暂时不可用");
  return payload.data;
}

export const counselingApi = {
  services: (locale: string) =>
    request<{ items: CounselingService[] }>(
      `/public/counseling/services?locale=${encodeURIComponent(locale)}`
    ),
  service: (slug: string, locale: string) =>
    request<CounselingService>(
      `/public/counseling/services/${encodeURIComponent(slug)}?locale=${encodeURIComponent(locale)}`
    ),
  availability: (mentorId: string, serviceId: string, start: string, end: string) =>
    request<{ items: Array<{ starts_at: string; ends_at: string; mentor_timezone: string }> }>(
      `/public/counseling/availability?mentor_id=${mentorId}&service_id=${serviceId}&start_date=${start}&end_date=${end}`
    ),
  hold: (mentorId: string, serviceId: string, startsAt: string) =>
    request<{ id: string; status: string; expires_at: string }>(
      "/account/counseling/slot-holds",
      {
        method: "POST",
        body: JSON.stringify({
          mentor_id: mentorId,
          service_id: serviceId,
          starts_at: startsAt,
          idempotency_key: `web-hold-${crypto.randomUUID()}`
        })
      }
    ),
  book: (serviceId: string, mentorId: string, holdId: string, intake: string) =>
    request<CounselingAppointment>("/account/counseling/appointments", {
      method: "POST",
      body: JSON.stringify({
        mentor_id: mentorId,
        service_id: serviceId,
        slot_hold_id: holdId,
        user_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai",
        intake_schema_version: 1,
        intake_response: { goals: intake },
        idempotency_key: `web-appointment-${crypto.randomUUID()}`
      })
    }),
  appointments: () =>
    request<{ items: CounselingAppointment[] }>("/account/counseling/appointments"),
  appointment: (id: string) =>
    request<CounselingAppointment>(`/account/counseling/appointments/${id}`),
  cancel: (id: string) =>
    request<CounselingAppointment>(`/account/counseling/appointments/${id}/cancel`, {
      method: "POST",
      body: JSON.stringify({ reason: "User requested cancellation" })
    })
};
