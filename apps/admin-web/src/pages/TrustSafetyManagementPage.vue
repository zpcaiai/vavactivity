<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { localizeAdminValue } from "@vav/ui-admin";

import { safetyAdminApi, type SafetyAdminRow } from "@/features/trust-safety/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute();
const auth = useAdminAuthStore();
const section = computed(() => String(route.meta.safetySection ?? "reports"));
const rows = ref<SafetyAdminRow[]>([]);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const sections = [
  ["reports", "举报队列", "safety.reports.read"],
  ["cases", "安全案件", "safety.cases.read"],
  ["moderation", "内容审核", "safety.moderation.read"],
  ["harassment", "反骚扰", "safety.analytics.read"],
  ["fraud", "反诈骗", "safety.analytics.read"],
  ["restrictions", "账号限制", "safety.restrictions.read"],
  ["appeals", "申诉队列", "safety.appeals.read"],
  ["rules", "规则中心", "safety.rules.read"],
  ["red-team", "红队中心", "safety.red_team.read"],
  ["audit", "安全审计", "safety.audit.read"]
] as const;
const visible = computed(() => sections.filter((item) => auth.hasPermission(item[2])));

async function load() {
  busy.value = true;
  error.value = "";
  rows.value = [];
  try {
    await auth.bootstrap();
    rows.value = await safetyAdminApi.queue(section.value);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "Trust & Safety 工作台加载失败";
  } finally {
    busy.value = false;
  }
}

async function act(row: SafetyAdminRow) {
  const id = String(row.id);
  if (section.value === "cases" && auth.hasPermission("safety.cases.manage")) {
    await safetyAdminApi.transitionCase(id, row.status === "open" ? "triaged" : "investigating");
  } else if (section.value === "moderation" && auth.hasPermission("safety.moderation.decide")) {
    await safetyAdminApi.decideModeration(id, { decision: "escalate", category_codes: [], reason_code: "human_review_required", user_message: "内容正在人工复核。" });
  } else if (section.value === "rules" && auth.hasPermission("safety.rules.activate")) {
    if (!window.confirm("确认已经由另一位管理员审阅，并接受灰度与回滚责任？")) return;
    await safetyAdminApi.activateRule(id);
  }
  notice.value = "操作已追加审计并刷新队列。";
  await load();
}

watch(() => route.fullPath, load);
onMounted(load);
</script>

<template>
  <section class="safety-admin">
    <header>
      <div>
        <p class="eyebrow">
          第 18 批 · 信任与安全运营
        </p><h1>信任与安全中心</h1>
      </div><p>自动信号只能冻结、限速或升级复核；永久停用、重大诈骗与其他高影响决定必须双人审批并允许独立申诉。</p>
    </header>
    <nav>
      <RouterLink
        v-for="item in visible"
        :key="item[0]"
        :to="`/admin/trust-safety/${item[0]}`"
      >
        {{ item[1] }}
      </RouterLink>
    </nav>
    <p
      v-if="busy"
      role="status"
    >
      正在加载最小披露视图…
    </p><p
      v-if="error"
      role="alert"
      class="alert error"
    >
      {{ error }}
    </p><p
      v-if="notice"
      role="status"
      class="alert notice"
    >
      {{ notice }}
    </p>
    <article
      v-if="section === 'red-team'"
      class="panel"
    >
      <h2>生产发布红队门禁</h2><ul><li>屏蔽绕过率必须为 0</li><li>联系方式越权泄漏必须为 0</li><li>跨用户举报与 Reporter Identity 泄漏必须为 0</li><li>规则 DSL 代码执行与审批绕过必须为 0</li></ul><p>未附可复现 fixture、策略版本和全矩阵结果时，状态保持 NOT_CERTIFIED。</p>
    </article>
    <article
      v-else-if="section === 'audit'"
      class="panel"
    >
      <h2>追加式安全审计</h2><p>原始举报描述和证据不在通用审计视图展示；敏感访问使用独立权限并记录目的代码。</p>
    </article>
    <article class="panel">
      <table>
        <thead><tr><th>ID / 编号</th><th>类别</th><th>状态</th><th>最小安全操作</th></tr></thead><tbody>
          <tr
            v-for="row in rows"
            :key="String(row.id)"
          >
            <td>{{ row.report_number ?? row.case_number ?? row.appeal_number ?? row.rule_code ?? row.run_number ?? row.id }}</td><td>{{ localizeAdminValue(row.category ?? row.primary_category ?? row.target_type ?? row.restriction_type ?? row.rule_type ?? row.signal_code ?? row.metric_code ?? row.event_type, "type") }}</td><td>{{ localizeAdminValue(row.status ?? 'recorded', "status") }}</td><td>
              <button
                v-if="['cases','moderation','rules'].includes(section)"
                @click="act(row)"
              >
                {{ section === 'rules' ? '双人审批激活' : '推进人工复核' }}
              </button><span v-else>只读最小披露</span>
            </td>
          </tr>
        </tbody>
      </table><p v-if="!rows.length && !busy">
        队列为空。
      </p>
    </article>
  </section>
</template>

<style scoped>
.safety-admin{display:grid;gap:1rem}header{display:flex;justify-content:space-between;gap:2rem;align-items:end}header>p{max-width:660px}.eyebrow{letter-spacing:.12em;color:var(--vav-color-danger)}nav{display:flex;gap:.55rem;flex-wrap:wrap}nav a{padding:.5rem .8rem;border-radius:999px;background:var(--vav-color-surface-soft);color:var(--vav-color-text);text-decoration:none}.panel{padding:1rem;border:1px solid var(--vav-color-border);border-radius:12px;background:var(--vav-color-surface-raised)}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:.75rem;border-bottom:1px solid var(--vav-color-surface-sunken)}button{padding:.6rem .85rem;border:0;border-radius:999px;background:var(--vav-color-danger);color:white}.alert{padding:.8rem}.error{background:var(--vav-color-surface-danger)}.notice{background:var(--vav-color-surface-success)}@media(max-width:700px){header{align-items:start;flex-direction:column}table{display:block;overflow:auto}}
</style>
