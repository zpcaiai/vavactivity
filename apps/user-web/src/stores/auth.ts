import { defineStore } from "pinia";
import { computed, ref } from "vue";

export const useAuthStore = defineStore("auth", () => {
  const accessToken = ref<string>();
  const accountName = ref<string>();
  const isAuthenticated = computed(() => Boolean(accessToken.value));

  function clearSession() {
    accessToken.value = undefined;
    accountName.value = undefined;
  }

  return { accessToken, accountName, isAuthenticated, clearSession };
});

