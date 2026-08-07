<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { AdminDataTable } from "@vav/ui-admin";
import { VAlert, VPageState, VStatusBadge } from "@vav/ui-core";
import { dataGovernanceApi, type DataGovernanceRow } from "@/features/data-governance/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute(); const auth = useAdminAuthStore();
const section = computed(() => String(route.meta.dataGovernanceSection ?? "dashboard"));
const rows = ref<DataGovernanceRow[]>([]); const dashboard = ref<DataGovernanceRow>({}); const busy = ref(false); const error = ref("");
const sections = [
  ["dashboard", "概览", "data.dashboard.read"], ["assets", "数据资产", "data.assets.read"], ["contracts", "数据契约", "data.contracts.read"], ["lineage", "数据血缘", "data.lineage.read"], ["events", "事件", "data.events.read"], ["event-gaps", "事件缺口", "data.events.read"], ["dead-letters", "死信", "data.dead_letters.read"], ["quality", "数据质量", "data.quality.read"], ["reconciliations", "对账", "data.reconciliations.read"], ["differences", "差异", "data.reconciliations.read"], ["backfills", "Backfill", "data.backfills.read"], ["repairs", "修复", "data.repairs.read"], ["projections", "投影重建", "data.projections.read"], ["erasures", "删除传播", "data.erasures.read"], ["certifications", "完整性认证", "data.certifications.read"], ["release", "发布", "data.release.read"]
] as const;
const visibleSections = computed(() => sections.filter((item) => auth.hasPermission(item[2])));
const tableRows = computed(() => rows.value.map((row) => ({ ...row, identifier: row.asset_code ?? row.contract_code ?? row.gap_code ?? row.reconciliation_code ?? row.backfill_code ?? row.event_type ?? row.business_domain ?? row.id ?? "-", kind: row.asset_type ?? row.contract_type ?? row.dimension ?? row.category ?? "-", record_state: row.status ?? row.lifecycle_status ?? row.technical_status ?? "-" })));
async function load() { busy.value = true; error.value = ""; try { if (section.value === "dashboard") { dashboard.value = await dataGovernanceApi.dashboard(); rows.value = []; } else rows.value = await dataGovernanceApi.list(section.value); } catch (cause) { error.value = cause instanceof Error ? cause.message : "数据治理加载失败"; } finally { busy.value = false; } }
onMounted(load); watch(section, load);
</script>

<template>
  <section class="data-console">
    <header>
      <div>
        <p class="eyebrow">
          BATCH 25 · DATA INTEGRITY
        </p><h1>数据治理与完整性中心</h1><p>权威数据由领域模块持有；本中心验证契约、血缘、事件、对账、Backfill 与删除传播，不直接改写业务事实。</p>
      </div><VStatusBadge
        status="warning"
        label="NOT CERTIFIED"
      />
    </header>
    <nav aria-label="数据治理分区">
      <RouterLink
        v-for="item in visibleSections"
        :key="item[0]"
        :to="`/admin/data-governance/${item[0]}`"
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
      aria-live="polite"
    >
      <article><strong>{{ dashboard.active_assets ?? 0 }}</strong><span>活跃资产</span></article><article><strong>{{ dashboard.active_contracts ?? 0 }}</strong><span>活跃契约</span></article><article><strong>{{ dashboard.open_event_gaps ?? 0 }}</strong><span>事件缺口</span></article><article><strong>{{ dashboard.open_dead_letters ?? 0 }}</strong><span>死信</span></article><article><strong>{{ dashboard.open_differences ?? 0 }}</strong><span>对账差异</span></article><article><strong>{{ dashboard.erasure_failures ?? 0 }}</strong><span>删除失败</span></article>
    </div>
    <div
      v-else
      class="table-panel"
    >
      <VPageState
        v-if="busy && rows.length === 0"
        state="loading"
        title="正在读取数据完整性状态"
        message="请稍候。"
      /><AdminDataTable
        v-else
        caption="数据治理记录"
        :columns="[{ key: 'identifier', label: '标识', priority: 'primary' }, { key: 'kind', label: '类型' }, { key: 'record_state', label: '状态' }]"
        :rows="tableRows"
        row-key="id"
        :loading="busy"
      />
    </div>
  </section>
</template>

<style scoped>.data-console{display:grid;gap:var(--vav-density-page-gap)}header{display:flex;justify-content:space-between;align-items:end;gap:var(--vav-space-6)}header p{max-width:var(--vav-layout-content-reading)}.eyebrow{color:var(--vav-color-action-primary);font-weight:700;letter-spacing:.1em}nav{display:flex;flex-wrap:wrap;gap:var(--vav-space-2)}nav a{padding:var(--vav-space-2) var(--vav-space-3);border-radius:var(--vav-radius-pill);background:var(--vav-color-surface-soft);color:var(--vav-color-text);text-decoration:none}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:var(--vav-space-4)}.metrics article,.table-panel{padding:var(--vav-component-card-padding);border:1px solid var(--vav-color-border);border-radius:var(--vav-component-card-radius);background:var(--vav-color-surface-raised)}.metrics article{display:grid;gap:var(--vav-space-2)}.metrics strong{font-size:var(--vav-font-size-xl)}@media(max-width:48rem){header{align-items:start;flex-direction:column}}</style>
