<script setup lang="ts">
import { onMounted, ref } from "vue";
import { resolveApiBaseUrl } from "@/config/api";

import { useAuthStore } from "@/stores/auth";

interface SessionItem {
  id: string;
  device_name: string | null;
  issued_at: string;
  last_used_at: string | null;
  expires_at: string;
  current: boolean;
}

const auth = useAuthStore();
const sessions = ref<SessionItem[]>([]);
const error = ref("");
const baseUrl = resolveApiBaseUrl();

async function load() {
  await auth.bootstrap();
  if (!auth.accessToken) {
    return;
  }
  const response = await fetch(`${baseUrl}/auth/sessions`, {
    credentials: "include",
    headers: { Authorization: `Bearer ${auth.accessToken}` }
  });
  const payload = (await response.json()) as {
    data?: { items: SessionItem[] };
    error?: { message: string };
  };
  if (!response.ok) {
    error.value = payload.error?.message ?? "无法加载会话";
    return;
  }
  sessions.value = payload.data?.items ?? [];
}

async function revoke(sessionId: string) {
  if (!auth.accessToken) {
    return;
  }
  await fetch(`${baseUrl}/auth/sessions/${sessionId}`, {
    method: "DELETE",
    credentials: "include",
    headers: { Authorization: `Bearer ${auth.accessToken}` }
  });
  await load();
}

onMounted(() => void load());
</script>

<template>
  <section class="account-page">
    <p class="eyebrow">
      ACCOUNT SECURITY
    </p>
    <h1>登录设备</h1>
    <p
      v-if="error"
      class="form-error"
    >
      {{ error }}
    </p>
    <article
      v-for="item in sessions"
      :key="item.id"
      class="session-card"
    >
      <div>
        <strong>{{ item.device_name || "未知设备" }}</strong>
        <span v-if="item.current">当前设备</span>
        <p>最近使用：{{ item.last_used_at || item.issued_at }}</p>
        <p>过期：{{ item.expires_at }}</p>
      </div>
      <button
        type="button"
        @click="revoke(item.id)"
      >
        撤销
      </button>
    </article>
  </section>
</template>
