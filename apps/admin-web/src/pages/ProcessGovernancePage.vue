<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { AdminDataTable } from "@vav/ui-admin";
import { VAlert, VButton, VPageState, VStatusBadge } from "@vav/ui-core";

import { processApi, type ProcessRow } from "@/features/process-governance/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute();
const auth = useAdminAuthStore();
const section = computed(() => String(route.meta.processSection ?? "dashboard"));
const rows = ref<ProcessRow[]>([]);
const dashboard = ref<ProcessRow>({});
const busy = ref(false);
const error = ref("");
const notice = ref("");
const sections = [
  ["dashboard", "概览", "process.dashboard.read"], ["definitions", "流程定义", "process.definitions.read"], ["state-machines", "状态机", "process.state_machines.read"], ["instances", "流程实例", "process.instances.read"], ["sagas", "Saga", "process.sagas.read"], ["timeouts", "超时", "process.timeouts.read"], ["cancellations", "取消", "process.cancellations.read"], ["compensations", "补偿", "process.compensations.read"], ["stuck", "卡死检测", "process.stuck.read"], ["interventions", "人工干预", "process.interventions.read"], ["simulations", "模拟", "process.simulations.read"], ["certifications", "业务认证", "process.certifications.read"], ["release", "发布", "process.release.read"]
] as const;
const visibleSections = computed(() => sections.filter((item) => auth.hasPermission(item[2])));
const tableRows = computed(() => rows.value.map((row) => ({
  ...row,
  identifier: row.process_number ?? row.process_code ?? row.machine_code ?? row.finding_code ?? row.scenario_code ?? row.business_domain ?? row.id ?? "-",
  kind: row.business_domain ?? row.finding_type ?? row.process_type ?? row.current_step_code ?? "-",
  record_state: row.status ?? row.verification_status ?? row.technical_status ?? "-"
})));

async function load() {
  busy.value = true; error.value = "";
  try {
    if (section.value === "dashboard") { dashboard.value = await processApi.dashboard(); rows.value = []; }
    else rows.value = await processApi.list(section.value);
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "流程治理数据加载失败"; }
  finally { busy.value = false; }
}

async function verifyMachines() {
  busy.value = true;
  try { const result = await processApi.verifyMachines(); notice.value = `状态机验证：${result.status.toUpperCase()}，共 ${result.results.length} 个。`; await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "验证失败"; }
  finally { busy.value = false; }
}

async function scanStuck() {
  busy.value = true;
  try { const result = await processApi.scanStuck(); notice.value = `已创建 ${result.created} 个新卡死流程干预任务。`; await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "扫描失败"; }
  finally { busy.value = false; }
}

onMounted(load); watch(section, load);
</script>

<template>
  <section class="process-console">
    <header>
      <div>
        <p class="eyebrow">
          BATCH 24 · PROCESS GOVERNANCE
        </p><h1>业务流程与 Saga 控制中心</h1><p>领域模块保持权威；本控制面只执行注册命令、验证回执并协调超时、取消、补偿与恢复。</p>
      </div><VStatusBadge
        status="warning"
        label="NOT CERTIFIED"
      />
    </header>
    <nav aria-label="流程治理分区">
      <RouterLink
        v-for="item in visibleSections"
        :key="item[0]"
        :to="`/admin/processes/${item[0]}`"
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
      title="操作完成"
    >
      {{ notice }}
    </VAlert>
    <div
      v-if="section === 'dashboard'"
      class="metrics"
      aria-live="polite"
    >
      <article><strong>{{ dashboard.active_definitions ?? 0 }}</strong><span>活跃流程</span></article><article><strong>{{ dashboard.verified_machines ?? 0 }}</strong><span>有效状态机</span></article><article><strong>{{ dashboard.active_instances ?? 0 }}</strong><span>运行实例</span></article><article><strong>{{ dashboard.open_stuck ?? 0 }}</strong><span>未解决卡死</span></article><article><strong>{{ dashboard.compensation_failures ?? 0 }}</strong><span>补偿失败</span></article><article><strong>{{ dashboard.interventions ?? 0 }}</strong><span>人工干预</span></article>
    </div>
    <div
      v-else
      class="table-panel"
    >
      <div class="actions">
        <VButton
          v-if="section === 'state-machines'"
          :disabled="busy || !auth.hasPermission('process.state_machines.verify')"
          @click="verifyMachines"
        >
          运行状态机验证
        </VButton><VButton
          v-if="section === 'stuck'"
          :disabled="busy || !auth.hasPermission('process.stuck.scan')"
          @click="scanStuck"
        >
          扫描卡死流程
        </VButton>
      </div>
      <VPageState
        v-if="busy && rows.length === 0"
        state="loading"
        title="正在读取流程控制面"
        message="请稍候。"
      />
      <AdminDataTable
        v-else
        caption="流程治理记录"
        :columns="[{ key: 'identifier', label: '标识', priority: 'primary' }, { key: 'kind', label: '类型' }, { key: 'record_state', label: '状态' }]"
        :rows="tableRows"
        row-key="id"
        :loading="busy"
      />
    </div>
  </section>
</template>

<style scoped>.process-console{display:grid;gap:var(--vav-density-page-gap)}header{display:flex;justify-content:space-between;align-items:end;gap:var(--vav-space-6)}header p{max-width:var(--vav-layout-content-reading)}.eyebrow{color:var(--vav-color-action-primary);font-weight:700;letter-spacing:.1em}nav{display:flex;flex-wrap:wrap;gap:var(--vav-space-2)}nav a{padding:var(--vav-space-2) var(--vav-space-3);border-radius:var(--vav-radius-pill);background:var(--vav-color-surface-soft);color:var(--vav-color-text);text-decoration:none}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:var(--vav-space-4)}.metrics article,.table-panel{padding:var(--vav-component-card-padding);border:1px solid var(--vav-color-border);border-radius:var(--vav-component-card-radius);background:var(--vav-color-surface-raised)}.metrics article{display:grid;gap:var(--vav-space-2)}.metrics strong{font-size:var(--vav-font-size-xl)}.actions{display:flex;justify-content:flex-end;gap:var(--vav-space-2);margin-bottom:var(--vav-space-3)}@media(max-width:48rem){header{align-items:start;flex-direction:column}}</style>
