import { defineStore } from "pinia";
import { computed, ref } from "vue";

export const useAccessStore = defineStore("access", () => {
  const accessToken = ref<string>();
  const permissions = ref<string[]>([]);
  const foundationPreview = ref(import.meta.env.DEV);
  const isAuthenticated = computed(() => Boolean(accessToken.value));

  function hasPermission(required: string | string[]) {
    const requested = Array.isArray(required) ? required : [required];
    return requested.every((item) => permissions.value.includes(item));
  }

  function clearSession() {
    accessToken.value = undefined;
    permissions.value = [];
  }

  return {
    accessToken,
    permissions,
    foundationPreview,
    isAuthenticated,
    hasPermission,
    clearSession
  };
});

