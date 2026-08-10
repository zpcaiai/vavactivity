<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { resolveApiBaseUrl } from "@/config/api";

import { useAdminAuthStore } from "@/stores/admin-auth";
import PaginationBar from "@/components/PaginationBar.vue";

const route = useRoute();
const auth = useAdminAuthStore();
const items = ref<Record<string, unknown>[]>([]);
const error = ref("");
const loading = ref(false);
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
const baseUrl = resolveApiBaseUrl();
const endpoint = computed(() => String(route.meta.endpoint ?? "/admin/users"));

async function load() {
  loading.value = true;
  error.value = "";
  await auth.bootstrap();
  if (!auth.accessToken) {
    loading.value = false;
    return;
  }
  try {
    const url = new URL(`${baseUrl}${endpoint.value}`, window.location.origin);
    url.searchParams.set("page", String(page.value));
    url.searchParams.set("page_size", String(pageSize.value));
    const response = await fetch(url, {
      credentials: "include",
      headers: { Authorization: `Bearer ${auth.accessToken}` }
    });
    const payload = (await response.json()) as {
      data?: { items?: Record<string, unknown>[]; total?: number };
      error?: { message: string };
    };
    if (!response.ok) {
      error.value = payload.error?.message ?? "无法加载数据";
      return;
    }
    items.value = payload.data?.items ?? [];
    total.value = payload.data?.total ?? items.value.length;
  } catch {
    error.value = "无法连接管理 API";
  } finally {
    loading.value = false;
  }
}

onMounted(() => void load());
watch(endpoint, () => {
  page.value = 1;
  void load();
});
watch([page, pageSize], () => void load());
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
      v-loading="loading"
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
    <PaginationBar
      v-if="total > pageSize || page > 1"
      v-model:page="page"
      v-model:page-size="pageSize"
      :total="total"
    />
  </section>
</template>
