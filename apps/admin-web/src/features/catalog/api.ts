import { useAdminAuthStore } from "@/stores/admin-auth";
import { resolveApiBaseUrl } from "@/config/api";

const baseUrl = resolveApiBaseUrl();

export async function catalogApi<T>(
  path: string,
  init: NonNullable<Parameters<typeof fetch>[1]> = {}
) {
  const auth = useAdminAuthStore();
  await auth.bootstrap();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${auth.accessToken}`);
  if (init.body) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    credentials: "include",
    headers
  });
  const payload = (await response.json()) as {
    data: T;
    error?: { message: string };
  };
  if (!response.ok) {
    throw new Error(payload.error?.message ?? "商品中心请求失败");
  }
  return payload.data;
}
