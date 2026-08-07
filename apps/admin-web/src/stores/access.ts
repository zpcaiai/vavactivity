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

const baseUrl = resolveApiBaseUrl();

function csrfToken() {
  return document.cookie
    .split("; ")
    .find((cookie) => cookie.startsWith("vav_csrf="))
    ?.split("=")
    .slice(1)
    .join("=");
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
      throw new Error(explainApiConnectionError("管理员认证", baseUrl));
    }

    const text = await response.text();
    let result: (AuthResponse & {
      error?: { message: string };
    }) | null = null;
    if (text) {
      try {
        result = JSON.parse(text);
      } catch {
        if (!response.ok) {
          throw new Error(text);
        }
        throw new Error("管理员认证返回了无效响应");
      }
    }
    if (!response.ok) {
      if (result && "error" in result && result.error?.message) {
        throw new Error(result.error.message);
      }
      throw new Error(text.trim() ? text : "管理员认证失败");
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
