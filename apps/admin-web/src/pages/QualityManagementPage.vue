<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { localizeAdminValue } from "@vav/ui-admin";

import { qualityAdminApi, type QualityRow } from "@/features/quality/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute();
const auth = useAdminAuthStore();
const rows = ref<QualityRow[]>([]);
const dashboard = ref<QualityRow>({});
const busy = ref(false);
const error = ref("");
const notice = ref("");
const section = computed(() => String(route.meta.qualitySection ?? "dashboard"));
const sections = [
  ["dashboard", "概览", "quality.analytics.read"],
  ["requirements", "需求", "quality.requirements.read"],
  ["capabilities", "能力", "quality.capabilities.read"],
  ["traceability", "追踪", "quality.traceability.read"],
  ["business-flows", "业务闭环", "quality.business_flows.read"],
  ["gaps", "缺口", "quality.gaps.read"],
  ["risks", "风险", "quality.risks.read"],
  ["waivers", "Waiver", "quality.waivers.read"],
  ["evidence", "证据", "quality.evidence.read"],
  ["gates", "门禁", "quality.gates.read"],
  ["gate-runs", "门禁运行", "quality.gates.read"],
  ["releases", "发布", "quality.releases.read"],
  ["certifications", "认证", "quality.releases.read"],
  ["audit", "审计", "quality.audit.read"]
] as const;
const visibleSections = computed(() => sections.filter((item) => auth.hasPermission(item[2])));

function rowLabel(row: QualityRow) {
  return String(
    row.requirement_code ?? row.capability_code ?? row.gap_code ?? row.gate_code ??
      row.release_version ?? row.id ?? "-"
  );
}

async function load() {
  busy.value = true;
  error.value = "";
  try {
    if (section.value === "dashboard") {
      dashboard.value = await qualityAdminApi.dashboard();
      rows.value = [];
    } else {
      rows.value = await qualityAdminApi.list(section.value);
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "质量数据加载失败";
  } finally {
    busy.value = false;
  }
}

async function act(row: QualityRow, action: string) {
  if (!row.id || !window.confirm("确认执行此受审计操作？")) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    if (section.value === "requirements") await qualityAdminApi.transitionRequirement(row.id, action);
    if (section.value === "gaps") await qualityAdminApi.resolveGap(row.id);
    if (section.value === "waivers") await qualityAdminApi.decideWaiver(row.id, action as "approve" | "revoke");
    if (section.value === "evidence") await qualityAdminApi.transitionEvidence(row.id, action as "validate" | "accept");
    if (section.value === "gates") await qualityAdminApi.approveGate(row.id);
    notice.value = "操作已记录，请复核最新状态。";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "操作失败";
  } finally {
    busy.value = false;
  }
}

onMounted(load);
watch(section, load);
</script>

<template>
  <section class="quality-console">
    <header>
      <div>
        <p class="eyebrow">
          第 21 批 · 质量控制台
        </p>
        <h1>质量治理与发布门禁</h1>
        <p>证据缺失、过期或提交不匹配均按失败处理；生产环境不接受 Conditional Go。</p>
      </div>
      <strong class="fail-closed">默认阻断</strong>
    </header>
    <nav aria-label="质量治理分区">
      <router-link
        v-for="item in visibleSections"
        :key="item[0]"
        :to="`/admin/quality/${item[0]}`"
      >
        {{ item[1] }}
      </router-link>
    </nav>
    <p
      v-if="error"
      role="alert"
      class="alert error"
    >
      {{ error }}
    </p>
    <p
      v-if="notice"
      role="status"
      class="alert notice"
    >
      {{ notice }}
    </p>
    <div
      v-if="section === 'dashboard'"
      class="metrics"
      aria-live="polite"
    >
      <div><strong>{{ dashboard.requirements_total ?? 0 }}</strong><span>需求</span></div>
      <div><strong>{{ dashboard.capabilities ?? 0 }}</strong><span>可用能力</span></div>
      <div><strong>{{ dashboard.critical_gaps_open ?? 0 }}</strong><span>关键缺口</span></div>
      <div><strong>{{ dashboard.gate_failures ?? 0 }}</strong><span>门禁失败</span></div>
      <div><strong>{{ dashboard.releases_no_go ?? 0 }}</strong><span>禁止发布</span></div>
      <div><strong>{{ dashboard.release_allowed ? "允许发布" : "禁止发布" }}</strong><span>当前结构状态</span></div>
    </div>
    <div
      v-else
      class="panel"
      :aria-busy="busy"
    >
      <table>
        <thead><tr><th>标识</th><th>状态</th><th>详情</th><th>受控操作</th></tr></thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="String(row.id ?? rowLabel(row))"
          >
            <td>{{ rowLabel(row) }}</td>
            <td>{{ localizeAdminValue(row.status ?? row.decision, row.status ? "status" : "decision") }}</td>
            <td><code>{{ JSON.stringify(row) }}</code></td>
            <td class="actions">
              <button
                v-if="section === 'requirements' && row.status === 'draft'"
                :disabled="!auth.hasPermission('quality.requirements.approve')"
                @click="act(row, 'approved')"
              >
                批准
              </button>
              <button
                v-if="section === 'gaps' && row.status !== 'resolved'"
                :disabled="!auth.hasPermission('quality.gaps.resolve')"
                @click="act(row, 'resolve')"
              >
                标记已解决
              </button>
              <button
                v-if="section === 'waivers' && row.status === 'requested'"
                :disabled="!auth.hasPermission('quality.waivers.approve')"
                @click="act(row, 'approve')"
              >
                批准
              </button>
              <button
                v-if="section === 'waivers' && row.status === 'approved'"
                :disabled="!auth.hasPermission('quality.waivers.revoke')"
                @click="act(row, 'revoke')"
              >
                撤销
              </button>
              <button
                v-if="section === 'evidence' && row.status === 'registered'"
                :disabled="!auth.hasPermission('quality.evidence.validate')"
                @click="act(row, 'validate')"
              >
                验证
              </button>
              <button
                v-if="section === 'evidence' && row.status === 'validated'"
                :disabled="!auth.hasPermission('quality.evidence.accept')"
                @click="act(row, 'accept')"
              >
                接受
              </button>
              <button
                v-if="section === 'gates' && row.status === 'draft'"
                :disabled="!auth.hasPermission('quality.gates.approve')"
                @click="act(row, 'approve')"
              >
                启用
              </button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="4">
              暂无记录。没有记录不代表通过。
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.quality-console{display:grid;gap:1rem}header{display:flex;justify-content:space-between;gap:2rem;align-items:end}header>div>p{max-width:720px}.eyebrow{letter-spacing:.12em;color:var(--vav-color-focus)}.fail-closed{padding:.6rem .8rem;border-radius:8px;background:var(--vav-color-danger);color:var(--vav-color-surface-raised)}nav{display:flex;gap:.5rem;flex-wrap:wrap}nav a{padding:.5rem .8rem;border-radius:999px;background:var(--vav-color-surface-info);color:var(--vav-color-text);text-decoration:none}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:1rem}.metrics div,.panel{padding:1rem;border:1px solid var(--vav-color-border);border-radius:12px;background:var(--vav-color-surface-raised)}.metrics div{display:grid;gap:.35rem}.metrics strong{font-size:1.7rem}.panel{overflow:auto}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:.65rem;border-bottom:1px solid var(--vav-color-surface-soft);vertical-align:top}td code{display:block;max-width:540px;max-height:8rem;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}.actions{display:flex;gap:.4rem;flex-wrap:wrap}button{padding:.5rem .75rem;border:0;border-radius:999px;background:var(--vav-color-focus);color:var(--vav-color-surface-raised)}button:disabled{opacity:.45}.alert{padding:.8rem}.error{background:var(--vav-color-surface-danger)}.notice{background:var(--vav-color-surface-success)}@media(max-width:700px){header{align-items:start;flex-direction:column}}
</style>
