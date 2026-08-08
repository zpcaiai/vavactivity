import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { explainApiConnectionError, resolveApiBaseUrl } from "@/config/api";

export interface AdminUser {
  id: string;
  email: string;
  status: string;
  email_verified: boolean;
  permissions: string[];
}

interface AuthResponse {
  data: {
    access_token: string;
    expires_in: number;
    user: AdminUser;
  };
}

interface ApiErrorPayload {
  error?: {
    code?: string;
    message?: string;
  };
  detail?: Array<{ msg?: string; message?: string; loc?: unknown }>;
  message?: string;
}

const baseUrl = resolveApiBaseUrl();

function csrfToken() {
  return document.cookie
    .split("; ")
    .find((cookie) => cookie.startsWith("vav_csrf="))
    ?.split("=")
    .slice(1)
    .join("=");
}

function isHtmlResponse(text: string, contentType: string | null): boolean {
  if (text.startsWith("<!DOCTYPE") || text.includes("<html")) {
    return true;
  }
  if (contentType?.includes("text/html")) {
    return true;
  }
  return false;
}

function humanizeAuthError(payload: ApiErrorPayload, fallback: string): string {
  if (payload.error?.message?.trim()) {
    return payload.error.message.trim();
  }
  if (payload.message?.trim()) {
    return payload.message.trim();
  }
  if (Array.isArray(payload.detail) && payload.detail.length > 0) {
    const detailMessage = payload.detail
      .map((row) => row?.msg || row?.message)
      .filter(Boolean)
      .filter((value): value is string => typeof value === "string" && value.trim().length > 0);
    if (detailMessage.length > 0) {
      return detailMessage.join("; ");
    }
  }
  return fallback;
}

export const useAccessStore = defineStore("access", () => {
  const accessToken = ref<string>();
  const permissions = ref<string[]>([]);
  const user = ref<AdminUser | null>(null);
  const status = ref<"unknown" | "authenticated" | "anonymous" | "refreshing">("unknown");
  const foundationPreview = ref(false);
  const isAuthenticated = computed(() => Boolean(accessToken.value));

  function hasPermission(required: string | string[]) {
    const requested = Array.isArray(required) ? required : [required];
    return requested.every((item) => permissions.value.includes(item));
  }

  function clearSession() {
    accessToken.value = undefined;
    permissions.value = [];
    user.value = null;
    status.value = "anonymous";
  }

  async function requestAuth(path: string, init: RequestInit = {}) {
    const requestUrl = `${baseUrl}${path}`;
    const headers = new Headers(init.headers);
    if (init.body) {
      headers.set("Content-Type", "application/json");
    }
    let response: Response;
    try {
      response = await fetch(requestUrl, {
        ...init,
        credentials: "include",
        headers
      });
    } catch {
      throw new Error(explainApiConnectionError("管理员认证", baseUrl));
    }

    const text = await response.text();
    const contentType = response.headers.get("content-type");
    let result: (AuthResponse & ApiErrorPayload) | null = null;
    if (!isHtmlResponse(text, contentType) && text) {
      try {
        result = JSON.parse(text) as AuthResponse & ApiErrorPayload;
      } catch {
        if (!response.ok) {
          if (isHtmlResponse(text, contentType)) {
            throw new Error(`管理员认证失败：后端返回了非 JSON 响应，当前请求 ${requestUrl} 可能不是真正 API。`);
          }
          throw new Error(text);
        }
        throw new Error("管理员认证返回了无效响应");
      }
    } else if (isHtmlResponse(text, contentType)) {
      throw new Error(`管理员认证失败：后端返回了 HTML 响应，当前请求 ${requestUrl} 可能不是 API 域名。`);
    }
    if (!response.ok) {
      if (result && "error" in result && result.error?.message) {
        throw new Error(humanizeAuthError(result as ApiErrorPayload, result.error.message));
      }
      const fallback = text.trim() ? text : "管理员认证失败";
      throw new Error(result ? humanizeAuthError(result as ApiErrorPayload, fallback) : fallback);
    }
    if (!result) {
      throw new Error("管理员认证返回为空");
    }
    return result;
  }

  function applyAuth(result: AuthResponse) {
    accessToken.value = result.data.access_token;
    permissions.value = result.data.user.permissions;
    user.value = result.data.user;
    status.value = "authenticated";
  }

  async function login(email: string, password: string) {
    const result = await requestAuth("/admin/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email,
        password,
        device_name: "Admin web browser"
      })
    });
    applyAuth(result);
  }

  async function refresh() {
    status.value = "refreshing";
    try {
      const csrf = csrfToken();
      if (!csrf) {
        clearSession();
        return false;
      }
      const result = await requestAuth("/admin/auth/refresh", {
        method: "POST",
        headers: { "X-CSRF-Token": csrf }
      });
      applyAuth(result);
      return true;
    } catch {
      clearSession();
      return false;
    }
  }

  async function bootstrap() {
    if (status.value === "unknown") {
      await refresh();
    }
  }

  async function logout() {
    if (!accessToken.value) {
      clearSession();
      return;
    }
    const csrf = csrfToken();
    await requestAuth("/admin/auth/logout", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken.value}`,
        ...(csrf ? { "X-CSRF-Token": csrf } : {})
      }
    });
    clearSession();
  }

  return {
    accessToken,
    permissions,
    user,
    status,
    foundationPreview,
    isAuthenticated,
    hasPermission,
    login,
    refresh,
    bootstrap,
    logout,
    clearSession
  };
});
