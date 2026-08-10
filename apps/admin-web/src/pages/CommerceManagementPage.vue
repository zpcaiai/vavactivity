<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { catalogApi } from "@/features/catalog/api";

type CommerceRow = Record<string, unknown> & { id: string; status?: string };

const route = useRoute();
const section = computed(() => String(route.meta.commerceSection ?? "orders"));
const rows = ref<CommerceRow[]>([]);
const loading = ref(false);
const error = ref("");

const labels: Record<string, string> = {
  orders: "订单",
  payments: "支付尝试",
  subscriptions: "订阅",
  refunds: "退款",
  webhooks: "Webhook",
  reconciliation: "对账差异",
  entitlements: "权益"
};

const columns = computed(() => {
  const keys = new Set<string>();
  for (const row of rows.value) {
    for (const key of Object.keys(row)) {
      if (!["payload", "expected", "actual", "client_action", "id"].includes(key)) keys.add(key);
    }
  }
  return [...keys].slice(0, 8);
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const result = await catalogApi<{ items: CommerceRow[] }>(
      `/admin/commerce/${section.value}`
    );
    rows.value = result.items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

async function action(row: CommerceRow, name: string) {
  try {
    await catalogApi(`/admin/commerce/${section.value}/${row.id}/${name}`, {
      method: "POST",
      body: JSON.stringify({ reason: `Operator reviewed and requested ${name}` })
    });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "操作失败";
  }
}

async function scan() {
  try {
    await catalogApi("/admin/commerce/reconciliation/scan", { method: "POST" });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "对账扫描失败";
  }
}

onMounted(() => void load());
watch(section, () => void load());
</script>

<template>
  <section v-loading="loading">
    <header class="page-toolbar">
      <div>
        <p class="admin-kicker">
          COMMERCE CONTROL PLANE
        </p>
        <h2>{{ labels[section] }}</h2>
        <p>金额均为最小货币单位；支付成功只来自已验签 Webhook。</p>
      </div>
      <el-button
        v-if="section === 'reconciliation'"
        type="primary"
        @click="scan"
      >
        执行对账扫描
      </el-button>
    </header>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
    />
    <el-table
      :data="rows"
      stripe
    >
      <el-table-column
        v-for="column in columns"
        :key="column"
        :prop="column"
        :label="column"
      />
      <el-table-column
        label="操作"
        width="250"
      >
        <template #default="{ row }">
          <el-button
            v-if="section === 'webhooks' && row.processing_status !== 'processed'"
            size="small"
            @click="action(row, 'replay')"
          >
            重放
          </el-button>
          <template v-if="section === 'refunds'">
            <el-button
              v-if="row.status === 'approval_required'"
              size="small"
              @click="action(row, 'approve')"
            >
              批准
            </el-button>
            <el-button
              v-if="row.status === 'approved'"
              size="small"
              type="primary"
              @click="action(row, 'submit')"
            >
              提交 Provider
            </el-button>
          </template>
          <el-button
            v-if="section === 'entitlements' && row.status === 'active'"
            size="small"
            type="danger"
            @click="action(row, 'revoke')"
          >
            撤销
          </el-button>
          <el-button
            v-if="section === 'reconciliation' && row.status === 'open'"
            size="small"
            @click="action(row, 'resolve')"
          >
            标记已解决
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty
      v-if="!loading && !rows.length"
      description="暂无记录"
    />
  </section>
</template>
