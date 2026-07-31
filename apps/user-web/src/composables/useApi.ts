import { inject } from "vue";

import { apiKey } from "@/api/plugin";

export function useApi() {
  const api = inject(apiKey);
  if (!api) {
    throw new Error("VAV API client is not installed");
  }
  return api;
}

