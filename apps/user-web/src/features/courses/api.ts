import { useAuthStore } from "@/stores/auth";

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export interface CourseLesson {
  id: string;
  lesson_code: string;
  title: string;
  summary?: string | null;
  lesson_type: string;
  required: boolean;
  preview_policy: string;
  content_blocks: Array<Record<string, unknown>>;
  completion_mode?: string;
  exercise_id?: string | null;
}

export interface PublicCourse {
  id: string;
  course_code: string;
  course_type: string;
  status: string;
  title: string;
  slug: string;
  subtitle?: string | null;
  summary?: string | null;
  difficulty_level?: string | null;
  estimated_duration_minutes?: number | null;
  free_enrollment: boolean;
  catalog_product_id?: string | null;
  catalog_sku_id?: string | null;
  access_duration_days?: number | null;
  prices?: Array<{
    currency: string;
    unit_amount_minor: number;
    billing_type: string;
  }>;
  learning_outcomes?: Array<{ text?: string }>;
  target_audience?: Array<{ text?: string }>;
  prerequisites?: Array<{ text?: string }>;
  modules?: Array<{
    id: string;
    title: string;
    required: boolean;
    lessons: CourseLesson[];
  }>;
}

export interface Enrollment {
  id: string;
  course_id: string;
  course_version_id: string;
  status: string;
  source_type: string;
  access_expires_at?: string | null;
  course?: PublicCourse;
  progress?: Array<{
    lesson_id: string;
    status: string;
    progress_basis_points: number;
  }>;
}

export interface ExerciseQuestion {
  id: string;
  question_type: "single_choice" | "multiple_choice" | "true_false" | "text" | "file";
  points: number;
  required: boolean;
  prompt_blocks: Array<{ type?: string; text?: string }>;
  options: Array<{ value: unknown; label: string }>;
}

export interface ExerciseAttempt {
  id: string;
  attempt_number: number;
  status: string;
  questions: ExerciseQuestion[];
}

export interface CourseCertificate {
  certificate_number: string;
  verification_token: string;
  recipient_name: string;
  course_title: string;
  issued_at: string;
  status: string;
  revoked_at?: string | null;
  credential_type: string;
  accreditation_claim: null;
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
  if (!response.ok) throw new Error(payload.error?.message ?? "课程服务暂时不可用");
  return payload.data;
}

export const courseApi = {
  list: (locale: string) =>
    request<{ items: PublicCourse[] }>(`/courses?locale=${encodeURIComponent(locale)}`),
  detail: (slug: string, locale: string) =>
    request<PublicCourse>(
      `/courses/${encodeURIComponent(slug)}?locale=${encodeURIComponent(locale)}`
    ),
  enroll: (courseId: string) =>
    request<Enrollment>(`/courses/${courseId}/enroll`, { method: "POST" }),
  enrollments: () => request<{ items: Enrollment[] }>("/account/courses"),
  dashboard: (enrollmentId: string) =>
    request<Enrollment>(`/account/courses/${enrollmentId}`),
  lesson: (enrollmentId: string, lessonId: string) =>
    request<{
      id: string;
      title: string;
      lesson_type: string;
      content_blocks: Array<{ type?: string; text?: string }>;
      completion_mode: string;
      exercise_id?: string | null;
    }>(`/account/courses/${enrollmentId}/lessons/${lessonId}`),
  event: (
    enrollmentId: string,
    lessonId: string,
    eventType: "lesson_opened" | "manual_completed"
  ) =>
    request(`/account/courses/${enrollmentId}/events`, {
      method: "POST",
      body: JSON.stringify({
        lesson_id: lessonId,
        event_type: eventType,
        event_sequence: Date.now(),
        idempotency_key: `${eventType}-${lessonId}-${Date.now()}`,
        occurred_at: new Date().toISOString(),
        payload: {}
      })
    }),
  playback: (enrollmentId: string, lessonId: string) =>
    request<{
      session_id: string;
      playback_url: string;
      heartbeat_interval_seconds: number;
      download_enabled: boolean;
    }>(`/account/courses/${enrollmentId}/lessons/${lessonId}/playback`, {
      method: "POST"
    }),
  heartbeat: (
    sessionId: string,
    sequence: number,
    positionSeconds: number,
    playedSeconds: number
  ) =>
    request(`/account/playback/${sessionId}/heartbeat`, {
      method: "POST",
      body: JSON.stringify({
        sequence,
        position_seconds: positionSeconds,
        played_seconds: playedSeconds,
        playback_rate: 1,
        occurred_at: new Date().toISOString()
      })
    }),
  startAttempt: (enrollmentId: string, exerciseId: string) =>
    request<ExerciseAttempt>(
      `/account/courses/${enrollmentId}/exercises/${exerciseId}/attempts`,
      { method: "POST" }
    ),
  submitAttempt: (attemptId: string, responses: Record<string, unknown>) =>
    request<{
      id: string;
      status: string;
      score_basis_points?: number | null;
      passed?: boolean | null;
    }>(`/account/exercise-attempts/${attemptId}/submit`, {
      method: "POST",
      body: JSON.stringify({ responses })
    }),
  saveAttempt: (attemptId: string, responses: Record<string, unknown>) =>
    request<{ id: string; status: string; saved: boolean }>(
      `/account/exercise-attempts/${attemptId}/draft`,
      {
        method: "PUT",
        body: JSON.stringify({ responses })
      }
    ),
  certificates: () =>
    request<{ items: CourseCertificate[] }>("/account/certificates"),
  verifyCertificate: (verificationToken: string) =>
    request<Omit<CourseCertificate, "verification_token">>(
      `/certificates/verify/${encodeURIComponent(verificationToken)}`
    )
};
