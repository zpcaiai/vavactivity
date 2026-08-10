<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { relationshipAdminApi, type RelationshipAdminRow } from "@/features/relationships/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute();
const auth = useAdminAuthStore();
const section = computed(() => String(route.meta.relationshipSection ?? "dashboard"));
const detailId = computed(() => String(route.params.id ?? ""));
const summary = ref<Record<string, unknown>>({});
const rows = ref<RelationshipAdminRow[]>([]);
const detail = ref<Record<string, unknown>>();
const reason = ref("");
const purpose = ref("");
const busy = ref(false);
const error = ref("");
const notice = ref("");

const sections = [
  ["dashboard", "运行概览", "relationships.analytics.read"], ["journeys", "关系旅程", "relationships.read"], ["stages", "阶段策略", "relationships.stages.read"], ["proposals", "阶段提议", "relationships.proposals.read"], ["pauses", "暂停与恢复", "relationships.pauses.read"], ["endings", "结束记录", "relationships.endings.read"], ["milestones", "里程碑", "relationships.milestones.read"], ["checkins", "自愿回顾", "relationships.checkins.read"], ["reminders", "非操纵提醒", "relationships.reminders.read"], ["audit", "关系审计", "relationships.audit.read"]
] as const;
const visibleSections = computed(() => sections.filter((item) => auth.hasPermission(item[2])));

async function load() {
  busy.value = true; error.value = ""; detail.value = undefined; rows.value = []; summary.value = {};
  try {
    await auth.bootstrap();
    if (section.value === "dashboard") summary.value = await relationshipAdminApi.dashboard();
    else {
      rows.value = await relationshipAdminApi.journeys();
      if (detailId.value) detail.value = await relationshipAdminApi.journey(detailId.value);
    }
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "关系运营中心加载失败"; }
  finally { busy.value = false; }
}

function requirementsReady() {
  if (reason.value.trim().length >= 3 && purpose.value.trim().length >= 4) return true;
  error.value = "安全操作必须填写原因和调查用途，并写入审计。"; return false;
}
async function run(action: () => Promise<unknown>, message: string) {
  if (!requirementsReady() || !window.confirm("这是安全处置，会立即影响双方。确定继续吗？")) return;
  busy.value = true;
  try { await action(); notice.value = message; await load(); notice.value = message; }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "安全操作失败"; }
  finally { busy.value = false; }
}

watch(() => route.fullPath, load); onMounted(load);
</script>

<template>
  <section class="relationship-admin">
    <header>
      <div>
        <p class="eyebrow">
          BATCH 16 · CONSENT BOUNDARY
        </p><h1>关系运营中心</h1>
      </div><p>管理员可诊断和执行安全冻结，但不能代替成员确认阶段、恢复关系，或恢复已经结束的关系。</p>
    </header>
    <nav>
      <RouterLink
        v-for="item in visibleSections"
        :key="item[0]"
        :to="`/admin/relationships/${item[0]}`"
      >
        {{ item[1] }}
      </RouterLink>
    </nav>
    <p
      v-if="error"
      class="alert error"
      role="alert"
    >
      {{ error }}
    </p><p
      v-if="notice"
      class="alert notice"
      role="status"
    >
      {{ notice }}
    </p><p v-if="busy">
      加载中…
    </p>
    <div
      v-if="section === 'dashboard'"
      class="metrics"
    >
      <article
        v-for="(value,key) in summary"
        :key="key"
      >
        <small>{{ key }}</small><strong>{{ value }}</strong>
      </article>
    </div>
    <article
      v-else-if="detail"
      class="panel"
    >
      <RouterLink to="/admin/relationships/journeys">
        ← 返回旅程列表
      </RouterLink><h2>{{ detail.journey_number }}</h2><pre>{{ JSON.stringify(detail, null, 2) }}</pre><div class="safety">
        <h3>安全处置</h3><input
          v-model="reason"
          placeholder="原因代码"
        ><input
          v-model="purpose"
          placeholder="调查用途"
        ><div>
          <button
            v-if="auth.hasPermission('relationships.freeze')"
            @click="run(() => relationshipAdminApi.freeze(detailId, reason, purpose), '已安全冻结。')"
          >
            安全冻结
          </button><button
            v-if="auth.hasPermission('relationships.unfreeze')"
            @click="run(() => relationshipAdminApi.unfreeze(detailId, reason, purpose), '已解除安全冻结。')"
          >
            解除冻结
          </button><button
            v-if="auth.hasPermission('relationships.end_for_safety')"
            class="danger"
            @click="run(() => relationshipAdminApi.endForSafety(detailId, reason, purpose), '已因安全原因结束。')"
          >
            安全结束
          </button>
        </div>
      </div>
    </article>
    <div
      v-else
      class="panel"
    >
      <p v-if="section !== 'journeys'">
        该视图坚持最小披露，当前仅显示相关旅程的过程状态；私人反思、暂停原因和回顾回答不会在此列表展示。
      </p><table>
        <thead><tr><th>编号</th><th>匿名成员</th><th>状态</th><th>阶段</th><th>更新</th></tr></thead><tbody>
          <tr
            v-for="row in rows"
            :key="String(row.journey_id)"
          >
            <td>
              <RouterLink :to="`/admin/relationships/journeys/${row.journey_id}`">
                {{ row.journey_number }}
              </RouterLink>
            </td><td>{{ row.members }}</td><td>{{ row.status }}</td><td>{{ row.current_stage_code }}</td><td>{{ row.updated_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.relationship-admin{display:grid;gap:1rem}header{display:flex;justify-content:space-between;gap:2rem;align-items:end}header>p{max-width:620px}.eyebrow{letter-spacing:.12em;color:#8a6238}nav{display:flex;gap:.55rem;flex-wrap:wrap}nav a{padding:.5rem .8rem;border-radius:999px;background:#f2eee8;color:#333;text-decoration:none}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:1rem}.metrics article,.panel{padding:1rem;border:1px solid #e1ddd5;border-radius:12px;background:white}.metrics strong{display:block;font-size:1.8rem;margin-top:.5rem}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:.75rem;border-bottom:1px solid #eee}pre{overflow:auto;padding:1rem;background:#f7f7f5}.safety{display:grid;gap:.7rem;margin-top:1rem;padding:1rem;background:#fff5ee}.safety input{padding:.65rem;margin-right:.5rem}.safety button{margin:.3rem;padding:.6rem .9rem}.danger{background:#9b3434;color:white}.alert{padding:.8rem}.error{background:#fde8e7}.notice{background:#e8f5ed}
</style>
