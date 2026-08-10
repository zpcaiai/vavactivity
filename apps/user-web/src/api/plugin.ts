import { createApiClient } from "@vav/api-client";
import type { App, InjectionKey } from "vue";

import { useAuthStore } from "@/stores/auth";
import { resolveApiBaseUrl } from "@/config/api";

export type ApiRequest = ReturnType<typeof createApiClient>;

export const apiKey: InjectionKey<ApiRequest> = Symbol("vav-api-client");

export const apiPlugin = {
  install(app: App) {
    const request = createApiClient({
      baseUrl: resolveApiBaseUrl(),
      getAccessToken: () => useAuthStore().accessToken,
      refreshAccessToken: () => useAuthStore().refresh()
    });
    app.provide(apiKey, request);
  }
};
