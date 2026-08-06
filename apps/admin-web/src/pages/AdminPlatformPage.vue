<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { AdminDataTable } from "@vav/ui-admin";
import { VAlert, VPageState, VStatusBadge } from "@vav/ui-core";
import { adminPlatformApi, type AdminPlatformRow } from "@/features/admin-platform/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute(); const auth = useAdminAuthStore();
const section = computed(() => String(route.meta.adminPlatformSection ?? "dashboard"));
const rows = ref<AdminPlatformRow[]>([]); const dashboard = ref<AdminPlatformRow>({}); const busy = ref(false); const error = ref("");
const sections = [
  ["dashboard", "概览", "admin.workbench.read"], ["capabilities", "能力注册", "admin.capabilities.read"], ["work-items", "统一工作台", "admin.workbench.read"], ["saved-views", "保存视图", "admin.saved_views.read"], ["bulk-jobs", "批量任务", "admin.bulk.read"], ["approvals", "审批", "admin.approvals.read"], ["exceptions", "异常恢复", "admin.exceptions.read"], ["configurations", "配置中心", "admin.configurations.read"], ["field-access", "字段策略", "admin.fields.policies.read"], ["reveal-history", "揭示审计", "admin.fields.policies.read"], ["certifications", "域认证", "admin.certifications.read"], ["releases", "发布", "admin.certifications.read"], ["audit", "操作审计", "admin.audit.read"]
] as const;
const visibleSections = computed(() => sections.filter((item) => auth.hasPermission(item[2])));
const tableRows = computed(() => rows.value.map((row) => ({ ...row, identifier: row.capability_code ?? row.work_item_code ?? row.approval_number ?? row.exception_code ?? row.namespace_code ?? row.business_domain ?? row.id ?? "-", kind: row.capability_type ?? row.work_item_type ?? row.environment ?? "-", record_state: row.status ?? row.lifecycle_status ?? "-" })));
async function load() { busy.value = true; error.value = ""; try { if (section.value === "dashboard") { dashboard.value = await adminPlatformApi.dashboard(); rows.value = []; } else rows.value = await adminPlatformApi.list(section.value); } catch (cause) { error.value = cause instanceof Error ? cause.message : "管理平台加载失败"; } finally { busy.value = false; } }
onMounted(load); watch(section, load);
</script>

<template>
  <section class="admin-platform">
    <header>
      <div>
        <p class="eyebrow">
          BATCH 26 · ADMIN CONTROL PLANE
        </p><h1>统一管理运营平台</h1><p>所有写操作通过已注册领域命令；敏感字段由后端按权限和用途脱敏。</p>
      </div><VStatusBadge
        status="warning"
        label="NOT CERTIFIED"
      />
    </header>
    <nav aria-label="管理平台分区">
      <RouterLink
        v-for="item in visibleSections"
        :key="item[0]"
        :to="`/admin/platform/${item[0]}`"
      >
        {{ item[1] }}
      </RouterLink>
    </nav>
    <VAlert
      v-if="error"
      tone="danger"
      title="加载失败"
    >
      {{ error }}
    </VAlert>
    <div
      v-if="section === 'dashboard'"
      class="metrics"
    >
      <article><strong>{{ dashboard.capabilities ?? 0 }}</strong><span>注册能力</span></article><article><strong>{{ dashboard.open_work_items ?? 0 }}</strong><span>待办</span></article><article><strong>{{ dashboard.overdue ?? 0 }}</strong><span>超时</span></article><article><strong>{{ dashboard.pending_approvals ?? 0 }}</strong><span>待审批</span></article><article><strong>{{ dashboard.open_exceptions ?? 0 }}</strong><span>异常</span></article><article><strong>{{ dashboard.uncertified_domains ?? 0 }}</strong><span>未认证域</span></article>
    </div>
    <div
      v-else
      class="table-panel"
    >
      <VPageState
        v-if="busy && rows.length === 0"
        state="loading"
        title="正在读取管理状态"
        message="请稍候。"
      /><AdminDataTable
        v-else
        caption="管理平台记录"
        :columns="[{ key: 'identifier', label: '标识', priority: 'primary' }, { key: 'kind', label: '类型' }, { key: 'record_state', label: '状态' }]"
        :rows="tableRows"
        row-key="id"
        :loading="busy"
      />
    </div>
  </section>
</template>

<style scoped>.admin-platform{display:grid;gap:var(--vav-density-page-gap)}header{display:flex;justify-content:space-between;align-items:end;gap:var(--vav-space-6)}header p{max-width:var(--vav-layout-content-reading)}.eyebrow{color:var(--vav-color-action-primary);font-weight:700;letter-spacing:.1em}nav{display:flex;flex-wrap:wrap;gap:var(--vav-space-2)}nav a{padding:var(--vav-space-2) var(--vav-space-3);border-radius:var(--vav-radius-pill);background:var(--vav-color-surface-soft);color:var(--vav-color-text);text-decoration:none}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:var(--vav-space-4)}.metrics article,.table-panel{padding:var(--vav-component-card-padding);border:1px solid var(--vav-color-border);border-radius:var(--vav-component-card-radius);background:var(--vav-color-surface-raised)}.metrics article{display:grid;gap:var(--vav-space-2)}.metrics strong{font-size:var(--vav-font-size-xl)}@media(max-width:48rem){header{align-items:start;flex-direction:column}}</style>
