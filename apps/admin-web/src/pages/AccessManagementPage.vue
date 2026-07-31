<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute();
const auth = useAdminAuthStore();
const items = ref<Record<string, unknown>[]>([]);
const error = ref("");
const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
const endpoint = computed(() => String(route.meta.endpoint ?? "/admin/users"));

async function load() {
  await auth.bootstrap();
  if (!auth.accessToken) {
    return;
  }
  const response = await fetch(`${baseUrl}${endpoint.value}`, {
    credentials: "include",
    headers: { Authorization: `Bearer ${auth.accessToken}` }
  });
  const payload = (await response.json()) as {
    data?: { items?: Record<string, unknown>[] };
    error?: { message: string };
  };
  if (!response.ok) {
    error.value = payload.error?.message ?? "无法加载数据";
    return;
  }
  items.value = payload.data?.items ?? [];
}

onMounted(() => void load());
</script>

<template>
  <section>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
    />
    <el-table
      v-else
      :data="items"
      stripe
    >
      <el-table-column
        v-for="key in Object.keys(items[0] ?? {})"
        :key="key"
        :prop="key"
        :label="key"
        min-width="140"
      />
    </el-table>
  </section>
</template>
