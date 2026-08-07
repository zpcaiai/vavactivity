import { useAuthStore } from "@/stores/auth";
import { resolveApiBaseUrl } from "@/config/api";

const baseUrl = resolveApiBaseUrl();

export type PrivacyProfile = {
  user_id: string;
  display_name?: string | null;
  legal_name?: string | null;
  date_of_birth?: string | null;
  city?: string | null;
  region?: string | null;
  country_code?: string | null;
  preferred_locale: "zh-CN" | "zh-TW" | "en";
  timezone: string;
  public_bio?: string | null;
  profile_status: string;
  completeness_basis_points: number;
  version: number;
};

export type Consent = {
  consent_code: string;
  category: string;
  required_for_service: boolean;
  withdrawable: boolean;
  release_id: string;
  semantic_version: string;
  title: string;
  summary: string;
  status: string;
};

export type PrivacyRequest = {
  id: string;
  request_number: string;
  request_type: string;
  status: string;
  submitted_at: string;
  completed_at?: string | null;
};

export type MemoryItem = {
  id: string;
  memory_type: string;
  status: string;
  content: string;
  certainty: string;
  expires_at?: string | null;
};

export async function privacyApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  const auth = useAuthStore();
  await auth.bootstrap();
  const headers = new Headers(init.headers);
  if (auth.accessToken) headers.set("Authorization", `Bearer ${auth.accessToken}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers, credentials: "include" });
  const payload = (await response.json()) as { data: T; error?: { message: string } };
  if (!response.ok) throw new Error(payload.error?.message ?? "隐私中心请求失败");
  return payload.data;
}
