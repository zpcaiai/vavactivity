<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { catalogApi } from "@/features/catalog/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

type Row = Record<string, unknown> & { id?: string; status?: string };

type Dashboard = {
  pool: Record<string, number>;
  batches: Record<string, number>;
  guardrails: Record<string, unknown>;
  strategy: Record<string, unknown> | null;
  recent_evaluations: Row[];
};

type Diagnostics = {
  user_id: string;
  pool_entry: Row | null;
  aggregate_constraints: Record<string, unknown>;
  recent_batches: Row[];
  /** Only present when the operator holds the sensitive-read permission. */
  sensitive_included: boolean;
};

const sections = [
  ["dashboard", "推荐总览", "recommendations.analytics.read"],
  ["strategies", "策略版本", "recommendations.strategies.read"],
  ["features", "特征清单", "recommendations.features.read"],
  ["constraints", "硬性条件", "recommendations.constraints.read"],
  ["batches", "推荐批次", "recommendations.batches.read"],
  ["exposures", "曝光统计", "recommendations.exposures.read"],
  ["feedback", "反馈统计", "recommendations.feedback.read"],
  ["evaluations", "离线评估", "recommendations.evaluations.read"],
  ["experiments", "实验管理", "recommendations.experiments.read"],
  ["diagnostics", "用户诊断", "recommendations.diagnostics.run"],
  ["audit", "推荐审计", "recommendations.audit.read"]
] as const;

const endpointBySection: Record<string, string> = {
  dashboard: "/admin/recommendations/dashboard",
  strategies: "/admin/recommendations/strategies",
  features: "/admin/recommendations/features",
  constraints: "/admin/recommendations/constraints",
  batches: "/admin/recommendations/batches",
  exposures: "/admin/recommendations/exposures",
  feedback: "/admin/recommendations/feedback",
  evaluations: "/admin/recommendations/evaluations",
  experiments: "/admin/recommendations/experiments",
  audit: "/admin/recommendations/audit"
};

const route = useRoute();
const auth = useAdminAuthStore();
const section = ref(String(route.meta.recommendationSection ?? "dashboard"));
const rows = ref<Row[]>([]);
const dashboard = ref<Dashboard>();
const diagnostics = ref<Diagnostics>();
const diagnosticsUserId = ref("");
const busy = ref(false);
const error = ref("");
const notice = ref("");
const rollbackReason = ref("");

const visibleSections = computed(() => sections.filter((item) => auth.hasPermission(item[2])));
const canApprove = computed(() => auth.hasPermission("recommendations.strategies.approve"));
const canActivate = computed(() => auth.hasPermission("recommendations.strategies.activate"));
const canRollback = computed(() => auth.hasPermission("recommendations.strategies.rollback"));
const canInvalidate = computed(() => auth.hasPermission("recommendations.batches.invalidate"));
const canRebuild = computed(() => auth.hasPermission("recommendations.batches.rebuild"));
const canRunEvaluation = computed(() => auth.hasPermission("recommendations.evaluations.run"));

function columnsOf(items: Row[]): string[] {
  if (!items.length) return [];
  return Object.keys(items[0]).filter(
    (key) => !["feature_manifest", "scoring_policy", "explanation_snapshot"].includes(key)
  );
}

function display(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

async function load() {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    if (section.value === "diagnostics") {
      rows.value = [];
      return;
    }
    const payload = await catalogApi<Record<string, unknown>>(endpointBySection[section.value]);
    if (section.value === "dashboard") {
      dashboard.value = payload as unknown as Dashboard;
      rows.value = (dashboard.value.recent_evaluations ?? []) as Row[];
    } else {
      rows.value = ((payload.items as Row[]) ?? []) as Row[];
    }
  } catch (loadError) {
    error.value = (loadError as Error).message;
  } finally {
    busy.value = false;
  }
}

async function act(path: string, body?: Record<string, unknown>) {
  busy.value = true;
  error.value = "";
  try {
    await catalogApi(path, { method: "POST", body: JSON.stringify(body ?? {}) });
    notice.value = "操作已完成。";
    await load();
  } catch (actionError) {
    error.value = (actionError as Error).message;
  } finally {
    busy.value = false;
  }
}

async function runDiagnostics() {
  if (!diagnosticsUserId.value) return;
  busy.value = true;
  error.value = "";
  try {
    diagnostics.value = await catalogApi<Diagnostics>(
      `/admin/recommendations/diagnostics/${diagnosticsUserId.value}`
    );
  } catch (diagnosticsError) {
    error.value = (diagnosticsError as Error).message;
  } finally {
    busy.value = false;
  }
}

watch(
  () => route.meta.recommendationSection,
  (value) => {
    section.value = String(value ?? "dashboard");
    void load();
  }
);

onMounted(load);
</script>

<template>
  <section class="recommendation-ops">
    <header>
      <h1>推荐运营中心</h1>
      <p class="recommendation-ops__lead">
        策略必须先通过评估与审批才能上线；任何操作都不能绕过用户的硬性条件与安全限制。
      </p>
      <nav class="recommendation-ops__tabs">
        <RouterLink
          v-for="entry in visibleSections"
          :key="entry[0]"
          :to="{ name: `admin-recommendations-${entry[0]}` }"
          :class="{ 'is-active': section === entry[0] }"
        >
          {{ entry[1] }}
        </RouterLink>
      </nav>
    </header>

    <p
      v-if="error"
      class="recommendation-ops__error"
      role="alert"
    >
      {{ error }}
    </p>
    <p
      v-if="notice"
      class="recommendation-ops__notice"
    >
      {{ notice }}
    </p>
    <p v-if="busy">
      处理中…
    </p>

    <section
      v-if="section === 'dashboard' && dashboard"
      class="recommendation-ops__cards"
    >
      <article>
        <h2>候选池</h2>
        <p
          v-for="(value, key) in dashboard.pool"
          :key="key"
        >
          {{ key }}: {{ value }}
        </p>
      </article>
      <article>
        <h2>批次</h2>
        <p
          v-for="(value, key) in dashboard.batches"
          :key="key"
        >
          {{ key }}: {{ value }}
        </p>
      </article>
      <article>
        <h2>安全护栏</h2>
        <p
          v-for="(value, key) in dashboard.guardrails"
          :key="key"
        >
          {{ key }}: {{ display(value) }}
        </p>
      </article>
      <article v-if="dashboard.strategy">
        <h2>当前策略</h2>
        <p>{{ display(dashboard.strategy.strategy_code) }} v{{ display(dashboard.strategy.semantic_version) }}</p>
      </article>
    </section>

    <section
      v-else-if="section === 'diagnostics'"
      class="recommendation-ops__panel"
    >
      <label>
        用户 ID
        <input
          v-model="diagnosticsUserId"
          type="text"
          placeholder="uuid"
        >
      </label>
      <button
        type="button"
        :disabled="busy || !diagnosticsUserId"
        @click="runDiagnostics"
      >
        运行诊断
      </button>
      <p class="recommendation-ops__hint">
        诊断只返回聚合口径的排除原因，不会展示任何一位候选人的档案内容。
      </p>
      <pre v-if="diagnostics">{{ JSON.stringify(diagnostics, null, 2) }}</pre>
    </section>

    <table
      v-else-if="rows.length"
      class="recommendation-ops__table"
    >
      <thead>
        <tr>
          <th
            v-for="column in columnsOf(rows)"
            :key="column"
          >
            {{ column }}
          </th>
          <th v-if="section === 'strategies' || section === 'batches'">
            操作
          </th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="(row, index) in rows"
          :key="String(row.id ?? index)"
        >
          <td
            v-for="column in columnsOf(rows)"
            :key="column"
          >
            {{ display(row[column]) }}
          </td>
          <td v-if="section === 'strategies'">
            <button
              v-if="canApprove && row.status === 'draft'"
              type="button"
              @click="act(`/admin/recommendations/strategies/${row.id}/approve`)"
            >
              审批
            </button>
            <button
              v-if="canActivate && row.status === 'approved'"
              type="button"
              @click="act(`/admin/recommendations/strategies/${row.id}/activate`)"
            >
              上线
            </button>
            <button
              v-if="canRollback && row.status === 'active'"
              type="button"
              @click="act(`/admin/recommendations/strategies/${row.id}/rollback`, { reason: rollbackReason || '运营回滚' })"
            >
              回滚
            </button>
          </td>
          <td v-else-if="section === 'batches'">
            <button
              v-if="canInvalidate"
              type="button"
              @click="act(`/admin/recommendations/batches/${row.id}/invalidate`, { reason: '运营人工作废' })"
            >
              作废
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <p v-else-if="!busy">
      暂无数据。
    </p>

    <footer
      v-if="section === 'evaluations' && canRunEvaluation"
      class="recommendation-ops__footer"
    >
      <p>离线评估必须在策略上线前通过；任何安全护栏失败都会阻断发布。</p>
    </footer>
    <footer
      v-else-if="section === 'batches' && canRebuild"
      class="recommendation-ops__footer"
    >
      <button
        type="button"
        @click="act('/admin/recommendations/pool/rebuild')"
      >
        重建候选池
      </button>
    </footer>
  </section>
</template>

<style scoped>
.recommendation-ops {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.25rem;
}

.recommendation-ops__lead {
  color: #5b6472;
}

.recommendation-ops__tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.recommendation-ops__tabs a {
  border: 1px solid #d7dce4;
  border-radius: 999px;
  padding: 0.3rem 0.85rem;
  text-decoration: none;
  color: #29313d;
}

.recommendation-ops__tabs a.is-active {
  background: #1f3d7a;
  border-color: #1f3d7a;
  color: #fff;
}

.recommendation-ops__error {
  color: #a4262c;
}

.recommendation-ops__notice {
  color: #1f6f43;
}

.recommendation-ops__cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
  gap: 1rem;
}

.recommendation-ops__cards article {
  border: 1px solid #e2e6ec;
  border-radius: 0.65rem;
  padding: 0.85rem;
  background: #fff;
}

.recommendation-ops__table {
  border-collapse: collapse;
  width: 100%;
  font-size: 0.85rem;
}

.recommendation-ops__table th,
.recommendation-ops__table td {
  border: 1px solid #e2e6ec;
  padding: 0.35rem 0.5rem;
  text-align: left;
  vertical-align: top;
}

.recommendation-ops__hint {
  color: #6b7280;
  font-size: 0.85rem;
}

pre {
  background: #f6f8fb;
  padding: 0.75rem;
  overflow: auto;
}
</style>
