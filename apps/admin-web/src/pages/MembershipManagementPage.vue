<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { membershipAdminApi, type MembershipAdminRow } from "@/features/memberships/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute();
const auth = useAdminAuthStore();
const section = computed(() => String(route.meta.membershipSection ?? "dashboard"));
const summary = ref<Record<string, unknown>>({});
const rows = ref<MembershipAdminRow[]>([]);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const planCode = ref("");
const planName = ref("");
const resolution = ref("");

const sections = [
  ["dashboard", "概览", "memberships.analytics.read"], ["plans", "会员计划", "memberships.plans.read"], ["plan-versions", "计划版本", "memberships.plans.read"], ["benefits", "权益注册表", "memberships.benefits.read"], ["sku-mappings", "SKU 映射", "memberships.sku_mappings.read"], ["accounts", "会员账户", "memberships.accounts.read"], ["cycles", "会员周期", "memberships.accounts.read"], ["changes", "计划变更", "memberships.changes.read"], ["quotas", "配额桶", "memberships.quotas.read"], ["usage", "使用流水", "memberships.quotas.read"], ["adjustments", "配额调整", "memberships.quotas.read"], ["manual-grants", "人工赠送", "memberships.manual_grants.read"], ["trials", "试用策略", "memberships.trials.read"], ["reconciliation", "对账异常", "memberships.reconciliation.read"], ["incidents", "事件", "memberships.incidents.read"], ["audit", "审计", "memberships.audit.read"]
] as const;
const visible = computed(() => sections.filter((item) => auth.hasPermission(item[2])));

async function load() {
  busy.value = true; error.value = ""; rows.value = []; summary.value = {};
  try {
    await auth.bootstrap();
    if (section.value === "dashboard") summary.value = await membershipAdminApi.dashboard();
    else if (section.value === "plans" || section.value === "plan-versions" || section.value === "sku-mappings") rows.value = await membershipAdminApi.plans();
    else if (section.value === "benefits") rows.value = await membershipAdminApi.benefits();
    else if (section.value === "reconciliation") rows.value = await membershipAdminApi.reconciliation();
    else if (["accounts","cycles","changes","quotas","usage","adjustments","manual-grants","trials","audit"].includes(section.value)) rows.value = await membershipAdminApi.resource(section.value);
    else summary.value = await membershipAdminApi.dashboard();
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "会员运营中心加载失败"; }
  finally { busy.value = false; }
}

async function createPlan() {
  if (!planCode.value.trim() || !planName.value.trim()) return;
  busy.value = true;
  try {
    await membershipAdminApi.createPlan({ plan_code: planCode.value, internal_name: planName.value, plan_type: "paid", default_locale: "zh-CN", display_order: 10, featured: false });
    notice.value = "草稿计划已创建。必须建立版本、SKU 映射并由另一位管理员审批后才能激活。";
    planCode.value = ""; planName.value = ""; await load();
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "计划创建失败"; }
  finally { busy.value = false; }
}

async function resolve(id: string) {
  if (resolution.value.trim().length < 3 || !window.confirm("确认已从权威 Commerce/Entitlement 数据修复，并关闭此对账问题？")) return;
  busy.value = true;
  try { await membershipAdminApi.resolveIssue(id, resolution.value); notice.value = "对账问题已记录为已解决。"; await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "处理失败"; }
  finally { busy.value = false; }
}

watch(() => route.fullPath, load); onMounted(load);
</script>

<template>
  <section class="membership-admin">
    <header>
      <div>
        <p class="eyebrow">
          BATCH 17 · ENTITLEMENT GOVERNANCE
        </p><h1>会员运营中心</h1>
      </div><p>会员是 Commerce 与 Entitlement 的受控投影。这里不能伪造付款、覆盖使用量或授予安全绕过。</p>
    </header>
    <nav>
      <RouterLink
        v-for="item in visible"
        :key="item[0]"
        :to="`/admin/memberships/${item[0]}`"
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
        <small>{{ key }}</small><strong>{{ typeof value === 'object' ? JSON.stringify(value) : value }}</strong>
      </article>
    </div>
    <article
      v-else
      class="panel"
    >
      <div
        v-if="section === 'plans' && auth.hasPermission('memberships.plans.create')"
        class="editor"
      >
        <h2>创建计划草稿</h2><input
          v-model="planCode"
          placeholder="稳定计划代码"
        ><input
          v-model="planName"
          placeholder="内部名称"
        ><button @click="createPlan">
          创建草稿
        </button>
      </div>
      <p v-if="!['plans','benefits','reconciliation'].includes(section)">
        此视图坚持最小披露。生产操作必须使用对应权限、原因代码、幂等键和追加式审计；Subscription 与付款状态只能由 Commerce 修改。
      </p>
      <table v-if="rows.length">
        <thead><tr><th>ID / Code</th><th>类型</th><th>状态</th><th>安全操作</th></tr></thead><tbody>
          <tr
            v-for="row in rows"
            :key="String(row.id ?? row.plan_code ?? row.benefit_code)"
          >
            <td>{{ row.plan_code ?? row.benefit_code ?? row.issue_code ?? row.id }}</td><td>{{ row.plan_type ?? row.benefit_type ?? row.severity }}</td><td>{{ row.status }}</td><td>
              <div v-if="section === 'reconciliation' && row.status !== 'resolved'">
                <input
                  v-model="resolution"
                  placeholder="修复摘要"
                ><button
                  v-if="auth.hasPermission('memberships.reconciliation.resolve')"
                  @click="resolve(String(row.id))"
                >
                  记录已解决
                </button>
              </div><span v-else>只读</span>
            </td>
          </tr>
        </tbody>
      </table>
      <div
        v-else-if="Object.keys(summary).length"
        class="metrics"
      >
        <article
          v-for="(value,key) in summary"
          :key="key"
        >
          <small>{{ key }}</small><strong>{{ typeof value === 'object' ? JSON.stringify(value) : value }}</strong>
        </article>
      </div>
    </article>
  </section>
</template>

<style scoped>
.membership-admin{display:grid;gap:1rem}header{display:flex;justify-content:space-between;gap:2rem;align-items:end}header>p{max-width:620px}.eyebrow{letter-spacing:.12em;color:#8a6238}nav{display:flex;gap:.55rem;flex-wrap:wrap}nav a{padding:.5rem .8rem;border-radius:999px;background:#f2eee8;color:#333;text-decoration:none}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem}.metrics article,.panel{padding:1rem;border:1px solid #e1ddd5;border-radius:12px;background:white}.metrics strong{display:block;margin-top:.5rem;overflow-wrap:anywhere}.editor{display:flex;gap:.6rem;align-items:end;flex-wrap:wrap;padding:1rem;background:#f7f4ee}.editor h2{width:100%}input{padding:.65rem;border:1px solid #ccc;border-radius:8px}button{padding:.65rem .9rem;border:0;border-radius:999px;background:#365f50;color:white}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:.75rem;border-bottom:1px solid #eee}.alert{padding:.8rem}.error{background:#fde8e7}.notice{background:#e8f5ed}@media(max-width:700px){header{align-items:start;flex-direction:column}table{display:block;overflow:auto}}
</style>
