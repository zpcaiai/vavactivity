import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { explainApiConnectionError, resolveApiBaseUrl } from "@/config/api";

export interface CurrentUser {
  id: string;
  email: string;
  status: string;
  email_verified: boolean;
  preferred_locale: string;
  timezone: string;
  permissions: string[];
}

export function normalizeLoginIdentifier(identifier: string) {
  const normalized = identifier.trim();
  return normalized.toLocaleLowerCase() === "test" ? "test@example.com" : normalized;
}

interface AuthResponse {
  data: {
    access_token: string;
    expires_in: number;
    user: CurrentUser;
  };
}

type AuthStatus = "unknown" | "authenticated" | "anonymous" | "refreshing";

const baseUrl = resolveApiBaseUrl();

function csrfToken() {
  return document.cookie
    .split("; ")
    .find((cookie) => cookie.startsWith("vav_csrf="))
    ?.split("=")
    .slice(1)
    .join("=");
}

export const useAuthStore = defineStore("auth", () => {
  const accessToken = ref<string>();
  const user = ref<CurrentUser | null>(null);
  const status = ref<AuthStatus>("unknown");
  const accountName = computed(() => user.value?.email);
  const isAuthenticated = computed(() => status.value === "authenticated");

  async function authRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    if (init.body) {
      headers.set("Content-Type", "application/json");
    }
    let response: Response;
    try {
      response = await fetch(`${baseUrl}${path}`, {
        ...init,
        credentials: "include",
        headers
      });
    } catch {
      throw new Error(explainApiConnectionError("用户认证", baseUrl));
    }
    const body = (await response.json()) as T & {
      error?: { code: string; message: string };
    };
    if (!response.ok) {
      throw new Error(body.error?.message ?? "Authentication request failed");
    }
    return body;
  }

  function applyAuth(result: AuthResponse) {
    accessToken.value = result.data.access_token;
    user.value = result.data.user;
    status.value = "authenticated";
  }

  async function login(email: string, password: string, deviceName = "Web browser") {
    const result = await authRequest<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: normalizeLoginIdentifier(email),
        password,
        device_name: deviceName
      })
    });
    applyAuth(result);
  }

  async function register(payload: {
    email: string;
    password: string;
    preferred_locale: string;
    timezone: string;
    terms_version: string;
    privacy_version: string;
  }) {
    return authRequest<{ data: { registration_status: string; email: string } }>(
      "/auth/register",
      { method: "POST", body: JSON.stringify(payload) }
    );
  }

  async function refresh() {
    status.value = "refreshing";
    try {
      const token = csrfToken();
      if (!token) {
        clearSession();
        return false;
      }
      const result = await authRequest<AuthResponse>("/auth/refresh", {
        method: "POST",
        headers: { "X-CSRF-Token": token }
      });
      applyAuth(result);
      return true;
    } catch {
      clearSession();
      return false;
    }
  }

  async function bootstrap() {
    if (status.value !== "unknown") {
      return;
    }
    await refresh();
  }

  async function logout(allDevices = false) {
    if (!accessToken.value) {
      clearSession();
      return;
    }
    const token = csrfToken();
    await authRequest(allDevices ? "/auth/logout-all" : "/auth/logout", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken.value}`,
        ...(token ? { "X-CSRF-Token": token } : {})
      }
    });
    clearSession();
  }

  function clearSession() {
    accessToken.value = undefined;
    user.value = null;
    status.value = "anonymous";
  }

  return {
    accessToken,
    user,
    status,
    accountName,
    isAuthenticated,
    login,
    register,
    refresh,
    bootstrap,
    logout,
    clearSession
  };
});
