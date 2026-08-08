<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { AdminDataTable } from "@vav/ui-admin";
import { VAlert, VButton, VPageState, VStatusBadge } from "@vav/ui-core";

import { experienceAdminApi, type ExperienceAdminRow } from "@/features/experience/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute();
const auth = useAdminAuthStore();
const rows = ref<ExperienceAdminRow[]>([]);
const dashboard = ref<ExperienceAdminRow>({});
const busy = ref(false);
const error = ref("");
const notice = ref("");
const section = computed(() => String(route.meta.experienceSection ?? "dashboard"));
const sections = [
  ["dashboard", "概览", "experience.analytics.read"], ["ia", "信息架构", "experience.ia.read"], ["routes", "路由", "experience.routes.read"], ["navigation", "导航", "experience.navigation.read"], ["tasks", "任务", "experience.tasks.read"], ["journeys", "旅程", "experience.journeys.read"], ["handoffs", "Handoff", "experience.handoffs.read"], ["search-governance", "搜索治理", "experience.search.read"], ["help", "帮助", "experience.help.read"], ["support", "支持", "experience.support.read"], ["dead-ends", "死路检测", "experience.dead_ends.read"], ["analytics", "分析", "experience.analytics.read"], ["evidence", "证据", "experience.closure.read"], ["release", "发布", "experience.closure.read"], ["audit", "审计", "experience.audit.read"]
] as const;
const visibleSections = computed(() => sections.filter((item) => auth.hasPermission(item[2])));
const tableRows = computed(() => rows.value.map((row) => ({
  ...row,
  identifier: row.route_code ?? row.node_code ?? row.task_code ?? row.journey_code ?? row.handoff_code ?? row.article_code ?? row.finding_code ?? row.capability_code ?? row.id ?? "-",
  kind: row.finding_type ?? row.source_module ?? row.application_code ?? row.category ?? "-",
  record_state: row.status ?? row.state ?? row.technical_status ?? "-"
})));

async function load() {
  busy.value = true;
  error.value = "";
  try {
    if (section.value === "dashboard") {
      dashboard.value = await experienceAdminApi.dashboard();
      rows.value = [];
    } else rows.value = await experienceAdminApi.list(section.value);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "体验治理数据加载失败";
  } finally {
    busy.value = false;
  }
}

async function scan() {
  busy.value = true;
  try {
    const result = await experienceAdminApi.scanDeadEnds();
    notice.value = `已扫描 ${result.routes_scanned} 条路由；关键死路 ${result.critical_count}。`;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "扫描失败";
  } finally {
    busy.value = false;
  }
}

onMounted(load);
watch(section, load);
</script>

<template>
  <section class="experience-console">
    <header>
      <div>
        <p class="eyebrow">
          BATCH 23 · EXPERIENCE ORCHESTRATION
        </p><h1>信息架构与体验闭环</h1><p>导航、任务和旅程是权威业务状态的安全投影；体验层不会直接修改所属业务状态。</p>
      </div><VStatusBadge
        :status="dashboard.production_certified ? 'success' : 'warning'"
        :label="dashboard.production_certified ? 'PRODUCTION CERTIFIED' : 'NOT CERTIFIED'"
      />
    </header>
    <nav aria-label="体验治理分区">
      <RouterLink
        v-for="item in visibleSections"
        :key="item[0]"
        :to="`/admin/experience/${item[0]}`"
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
    </VAlert><VAlert
      v-if="notice"
      tone="success"
      title="扫描完成"
    >
      {{ notice }}
    </VAlert>
    <div
      v-if="section === 'dashboard'"
      class="metrics"
      aria-live="polite"
    >
      <article><strong>{{ dashboard.ia_nodes ?? 0 }}</strong><span>IA 节点</span></article><article><strong>{{ dashboard.active_routes ?? 0 }}</strong><span>活跃路由</span></article><article><strong>{{ dashboard.active_tasks ?? 0 }}</strong><span>活跃任务</span></article><article><strong>{{ dashboard.active_journeys ?? 0 }}</strong><span>进行中旅程</span></article><article><strong>{{ dashboard.critical_dead_ends ?? 0 }}</strong><span>关键死路</span></article><article><strong>{{ dashboard.release_allowed ? 'GO' : 'NO-GO' }}</strong><span>生产发布</span></article>
    </div>
    <div
      v-else
      class="table-panel"
    >
      <div
        v-if="section === 'dead-ends'"
        class="actions"
      >
        <VButton
          :disabled="busy || !auth.hasPermission('experience.dead_ends.scan')"
          @click="scan"
        >
          运行死路扫描
        </VButton>
      </div>
      <VPageState
        v-if="busy && rows.length === 0"
        state="loading"
        title="正在读取体验治理状态"
        message="请稍候。"
      />
      <AdminDataTable
        v-else
        caption="体验治理记录"
        :columns="[{ key: 'identifier', label: '标识', priority: 'primary' }, { key: 'kind', label: '类型' }, { key: 'record_state', label: '状态' }]"
        :rows="tableRows"
        row-key="id"
        :loading="busy"
      />
    </div>
  </section>
</template>

<style scoped>.experience-console{display:grid;gap:var(--vav-density-page-gap)}header{display:flex;justify-content:space-between;align-items:end;gap:var(--vav-space-6)}header p{max-width:var(--vav-layout-content-reading)}.eyebrow{color:var(--vav-color-action-primary);font-weight:700;letter-spacing:.1em}nav{display:flex;flex-wrap:wrap;gap:var(--vav-space-2)}nav a{padding:var(--vav-space-2) var(--vav-space-3);border-radius:var(--vav-radius-pill);background:var(--vav-color-surface-soft);color:var(--vav-color-text);text-decoration:none}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:var(--vav-space-4)}.metrics article,.table-panel{padding:var(--vav-component-card-padding);border:1px solid var(--vav-color-border);border-radius:var(--vav-component-card-radius);background:var(--vav-color-surface-raised)}.metrics article{display:grid;gap:var(--vav-space-2)}.metrics strong{font-size:var(--vav-font-size-xl)}.actions{display:flex;justify-content:flex-end;margin-bottom:var(--vav-space-3)}@media(max-width:48rem){header{align-items:start;flex-direction:column}}</style>
