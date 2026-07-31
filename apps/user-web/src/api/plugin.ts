import { createApiClient } from "@vav/api-client";
import type { App, InjectionKey } from "vue";

import { useAuthStore } from "@/stores/auth";

export type ApiRequest = ReturnType<typeof createApiClient>;

export const apiKey: InjectionKey<ApiRequest> = Symbol("vav-api-client");

export const apiPlugin = {
  install(app: App) {
    const request = createApiClient({
      baseUrl: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1",
      getAccessToken: () => useAuthStore().accessToken,
      refreshAccessToken: () => useAuthStore().refresh()
    });
    app.provide(apiKey, request);
  }
};
