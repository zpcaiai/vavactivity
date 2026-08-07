<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { AdminDataTable } from "@vav/ui-admin";
import { VAlert, VButton, VStatusBadge } from "@vav/ui-core";

import { designSystemAdminApi, type DesignRow } from "@/features/design-system/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute();
const auth = useAdminAuthStore();
const rows = ref<DesignRow[]>([]);
const dashboard = ref<DesignRow>({});
const busy = ref(false);
const error = ref("");
const notice = ref("");
const section = computed(() => String(route.meta.designSystemSection ?? "dashboard"));
const sections = [
  ["dashboard", "概览", "design.analytics.read"],
  ["tokens", "Token", "design.tokens.read"],
  ["components", "组件", "design.components.read"],
  ["patterns", "模式", "design.patterns.read"],
  ["pages", "页面", "design.audits.read"],
  ["accessibility", "无障碍", "design.accessibility.read"],
  ["responsive-audits", "响应式", "design.audits.read"],
  ["visual-regression", "视觉回归", "design.audits.read"],
  ["baselines", "基线", "design.baselines.read"],
  ["evidence", "证据", "design.evidence.read"],
  ["releases", "发布", "design.tokens.read"],
  ["audit", "审计", "design.audit.read"]
] as const;
const visibleSections = computed(() => sections.filter((item) => auth.hasPermission(item[2])));
const tableRows = computed(() => rows.value.map((row) => ({
  ...row,
  identifier: row.token_version ?? row.component_code ?? row.pattern_code ?? row.audit_code ?? row.baseline_code ?? row.route_path ?? row.id ?? "-",
  kind: row.record_kind ?? row.audit_type ?? row.application_code ?? "-",
  state: row.status ?? "-"
})));

async function load() {
  busy.value = true;
  error.value = "";
  try {
    if (section.value === "dashboard") {
      dashboard.value = await designSystemAdminApi.dashboard();
      rows.value = [];
    } else {
      rows.value = await designSystemAdminApi.list(section.value);
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "设计系统数据加载失败";
  } finally {
    busy.value = false;
  }
}

async function act(row: DesignRow, action: "approve" | "reject") {
  if (!row.id || !window.confirm("确认执行此独立审核操作？")) return;
  busy.value = true;
  error.value = "";
  try {
    if (section.value === "tokens") await designSystemAdminApi.approveToken(row.id);
    if (section.value === "baselines") await designSystemAdminApi.decideBaseline(row.id, action);
    if (section.value === "evidence") await designSystemAdminApi.acceptEvidence(row.id);
    if (section.value === "accessibility") await designSystemAdminApi.reviewAudit(row.id, action, true);
    if (["responsive-audits", "visual-regression"].includes(section.value)) await designSystemAdminApi.reviewAudit(row.id, action);
    notice.value = "审核决定已追加到不可变审计轨迹。";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "审核操作失败";
  } finally {
    busy.value = false;
  }
}

function tone(status: unknown) {
  if (["approved", "released", "active"].includes(String(status))) return "success";
  if (["failed", "rejected"].includes(String(status))) return "danger";
  return "warning";
}

onMounted(load);
watch(section, load);
</script>

<template>
  <section class="design-console">
    <header>
      <div>
        <p class="eyebrow">
          BATCH 22 · DESIGN SYSTEM CONTROL PLANE
        </p><h1>设计系统与 UI 质量</h1><p>自动检查只形成技术证据；无障碍与视觉基线仍需独立人工审核。</p>
      </div><VStatusBadge
        :status="dashboard.production_certified ? 'success' : 'warning'"
        :label="dashboard.production_certified ? 'PRODUCTION CERTIFIED' : 'NOT CERTIFIED'"
      />
    </header>
    <nav aria-label="设计系统治理分区">
      <RouterLink
        v-for="item in visibleSections"
        :key="item[0]"
        :to="`/admin/design-system/${item[0]}`"
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
    <VAlert
      v-if="notice"
      tone="success"
      title="操作已记录"
    >
      {{ notice }}
    </VAlert>
    <div
      v-if="section === 'dashboard'"
      class="metrics"
      aria-live="polite"
    >
      <article><strong>{{ dashboard.components_active ?? 0 }}</strong><span>活跃组件</span></article><article><strong>{{ dashboard.patterns_active ?? 0 }}</strong><span>页面模式</span></article><article><strong>{{ dashboard.pages_registered ?? 0 }}</strong><span>登记页面</span></article><article><strong>{{ dashboard.audits_failed ?? 0 }}</strong><span>失败审核</span></article><article><strong>{{ dashboard.manual_reviews_open ?? 0 }}</strong><span>待人工复核</span></article><article><strong>{{ dashboard.release_allowed ? 'GO' : 'NO-GO' }}</strong><span>生产发布</span></article>
    </div>
    <div
      v-else
      class="table-panel"
    >
      <AdminDataTable
        caption="设计系统治理记录"
        :columns="[{ key: 'identifier', label: '标识', priority: 'primary' }, { key: 'kind', label: '类型' }, { key: 'state', label: '状态' }]"
        :rows="tableRows"
        row-key="id"
        :loading="busy"
      /><div
        v-for="row in rows"
        :key="`actions-${row.id}`"
        class="review-row"
      >
        <VStatusBadge
          :status="tone(row.status)"
          :label="String(row.status ?? '未知')"
        /><span>{{ row.token_version ?? row.audit_code ?? row.baseline_code ?? row.id }}</span><div
          v-if="row.id && ((section === 'tokens' && row.status === 'draft') || (section === 'baselines' && row.status === 'pending') || (section === 'evidence' && row.status === 'validated') || (['accessibility','responsive-audits','visual-regression'].includes(section) && ['technical_pass','needs_review'].includes(String(row.status))))"
          class="actions"
        >
          <VButton
            variant="secondary"
            :disabled="busy"
            @click="act(row, 'reject')"
          >
            拒绝
          </VButton><VButton
            :disabled="busy"
            @click="act(row, 'approve')"
          >
            批准
          </VButton>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>.design-console{display:grid;gap:var(--vav-density-page-gap)}header{display:flex;justify-content:space-between;align-items:end;gap:var(--vav-space-6)}header p{max-width:var(--vav-layout-content-reading)}.eyebrow{color:var(--vav-color-action-primary);font-weight:700;letter-spacing:.1em}nav{display:flex;flex-wrap:wrap;gap:var(--vav-space-2)}nav a{padding:var(--vav-space-2) var(--vav-space-3);border-radius:var(--vav-radius-pill);background:var(--vav-color-surface-soft);color:var(--vav-color-text);text-decoration:none}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:var(--vav-space-4)}.metrics article,.table-panel{padding:var(--vav-component-card-padding);border:1px solid var(--vav-color-border);border-radius:var(--vav-component-card-radius);background:var(--vav-color-surface-raised)}.metrics article{display:grid;gap:var(--vav-space-2)}.metrics strong{font-size:var(--vav-font-size-xl)}.review-row{display:grid;grid-template-columns:auto minmax(12rem,1fr) auto;align-items:center;gap:var(--vav-space-3);padding-block:var(--vav-space-3);border-top:1px solid var(--vav-color-border)}.actions{display:flex;gap:var(--vav-space-2)}@media(max-width:48rem){header{align-items:start;flex-direction:column}.review-row{grid-template-columns:1fr}.actions{display:grid;grid-template-columns:1fr 1fr}}</style>
