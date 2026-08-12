<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { localizeAdminLabel, localizeAdminValue } from "@vav/ui-admin";
import { VFormField, VModal } from "@vav/ui-core";

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
  ["dashboard", "概览", "memberships.analytics.read"], ["plans", "会员计划", "memberships.plans.read"], ["plan-versions", "计划版本", "memberships.plans.read"], ["benefits", "权益注册表", "memberships.benefits.read"], ["sku-mappings", "SKU 映射", "memberships.sku_mappings.read"], ["accounts", "会员账户", "memberships.accounts.read"], ["cycles", "会员周期", "memberships.accounts.read"], ["changes", "计划变更", "memberships.changes.read"], ["quotas", "配额桶", "memberships.quotas.read"], ["usage", "使用流水", "memberships.quotas.read"], ["adjustments", "配额调整", "memberships.quotas.read"], ["manual-grants", "人工赠送", "memberships.manual_grants.read"], ["trials", "试用策略", "memberships.trials.read"], ["reconciliation", "对账异常", "memberships.reconciliation.read"], ["audit", "审计", "memberships.audit.read"]
] as const;
const visible = computed(() => sections.filter((item) => auth.hasPermission(item[2])));

const canCreatePlan = computed(() => auth.hasPermission("memberships.plans.create"));
const canUpdatePlan = computed(() => auth.hasPermission("memberships.plans.update"));
const canApproveVersion = computed(() => auth.hasPermission("memberships.plans.approve"));
const canActivateVersion = computed(() => auth.hasPermission("memberships.plans.activate"));
const canRetireVersion = computed(() => auth.hasPermission("memberships.plans.retire"));
const canManageBenefits = computed(() => auth.hasPermission("memberships.benefits.manage"));
const canManageSkuMappings = computed(() => auth.hasPermission("memberships.sku_mappings.manage"));
const canAdjustQuota = computed(() => auth.hasPermission("memberships.quotas.adjust"));
const canCreateGrant = computed(() => auth.hasPermission("memberships.manual_grants.create"));
const canApproveGrant = computed(() => auth.hasPermission("memberships.manual_grants.approve"));
const canRevokeGrant = computed(() => auth.hasPermission("memberships.manual_grants.revoke"));
const canManageTrials = computed(() => auth.hasPermission("memberships.trials.manage"));

/**
 * Versions created in this session, kept so their lifecycle stays reachable:
 * the backend has no endpoint that lists plan versions, so a freshly created
 * draft would otherwise be unaddressable the moment the response scrolled away.
 */
const recentVersions = ref<Array<{ id: string; plan_code: string; semantic_version: string }>>([]);
const versionIdInput = ref("");

const versionDialog = ref({
  open: false,
  plan_id: "",
  plan_code: "",
  semantic_version: "",
  display_name: "",
  valid_from: "",
  valid_until: ""
});
const benefitDialog = ref({
  open: false,
  benefit_code: "",
  semantic_version: "1.0.0",
  benefit_type: "capability",
  owning_module: "",
  sensitivity: "internal",
  value_schema: "{}"
});
const skuDialog = ref({
  open: false,
  catalog_sku_id: "",
  membership_plan_id: "",
  membership_plan_version_id: "",
  billing_period: "monthly",
  valid_from: "",
  valid_until: ""
});
const quotaDialog = ref({
  open: false,
  bucket_id: "",
  quantity: 0,
  adjustment_type: "credit",
  reason_code: "",
  reason: ""
});
const grantDialog = ref({
  open: false,
  user_id: "",
  membership_plan_version_id: "",
  grant_type: "customer_support",
  reason_code: "",
  reason: "",
  starts_at: "",
  expires_at: ""
});
const trialDialog = ref({
  open: false,
  policy_code: "",
  semantic_version: "1.0.0",
  membership_plan_version_id: "",
  duration_days: 14,
  requires_payment_method: false,
  auto_converts: false,
  eligibility_policy: "{}"
});

const GRANT_TYPES = [
  { value: "customer_support", label: "客服补偿" },
  { value: "service_compensation", label: "服务补偿" },
  { value: "promotional", label: "市场活动" },
  { value: "staff", label: "内部员工" },
  { value: "migration", label: "迁移补齐" }
];
const ADJUSTMENT_TYPES = [
  { value: "credit", label: "增加额度" },
  { value: "debit", label: "扣减额度" },
  { value: "compensation", label: "补偿" },
  { value: "correction", label: "更正" }
];
const BENEFIT_TYPES = ["capability", "resource_scope", "quota", "limit_override", "price_benefit", "priority_access"];

function parseJson(value: string, field: string) {
  try {
    const parsed = JSON.parse(value || "{}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
    throw new Error("not an object");
  } catch {
    error.value = `${field}必须是合法的 JSON 对象。`;
    return null;
  }
}

async function load() {
  busy.value = true; error.value = ""; rows.value = []; summary.value = {};
  try {
    await auth.bootstrap();
    if (section.value === "dashboard") summary.value = await membershipAdminApi.dashboard();
    else if (section.value === "plans" || section.value === "plan-versions") rows.value = await membershipAdminApi.plans();
    else if (section.value === "benefits") rows.value = await membershipAdminApi.benefits();
    else if (section.value === "reconciliation") rows.value = await membershipAdminApi.reconciliation();
    else if (section.value === "sku-mappings") rows.value = [];
    else rows.value = await membershipAdminApi.resource(section.value);
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "会员运营中心加载失败"; }
  finally { busy.value = false; }
}

async function run(label: string, action: () => Promise<unknown>) {
  busy.value = true; error.value = "";
  try {
    await action();
    notice.value = `${label}已完成。`;
    await load();
    return true;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : `${label}失败`;
    return false;
  } finally { busy.value = false; }
}

async function createPlan() {
  if (!planCode.value.trim() || !planName.value.trim()) {
    error.value = "请填写计划代码与内部名称。";
    return;
  }
  const ok = await run("计划草稿创建", () => membershipAdminApi.createPlan({
    plan_code: planCode.value.trim(),
    internal_name: planName.value.trim(),
    plan_type: "paid",
    default_locale: "zh-CN",
    display_order: 10,
    featured: false
  }));
  if (ok) {
    notice.value = "草稿计划已创建。必须建立版本、SKU 映射并由另一位管理员审批后才能激活。";
    planCode.value = ""; planName.value = "";
  }
}

function openVersionDialog(row: MembershipAdminRow) {
  error.value = "";
  versionDialog.value = {
    open: true,
    plan_id: String(row.id ?? ""),
    plan_code: String(row.plan_code ?? ""),
    semantic_version: "",
    display_name: String(row.internal_name ?? ""),
    valid_from: "",
    valid_until: ""
  };
}

async function createVersion() {
  const form = versionDialog.value;
  if (!form.semantic_version.trim()) {
    error.value = "请填写语义化版本号，例如 1.0.0。";
    return;
  }
  if (!form.display_name.trim()) {
    error.value = "请填写该版本对用户展示的名称。";
    return;
  }
  if (!form.valid_from) {
    error.value = "请填写版本生效时间。";
    return;
  }
  busy.value = true; error.value = "";
  try {
    const created = await membershipAdminApi.createPlanVersion(form.plan_id, {
      semantic_version: form.semantic_version.trim(),
      localizations: [{ locale: "zh-CN", display_name: form.display_name.trim() }],
      benefits: [],
      access_policy_snapshot: {},
      quota_policy_snapshot: {},
      valid_from: form.valid_from,
      valid_until: form.valid_until || null
    });
    if (created?.id) {
      recentVersions.value = [
        { id: String(created.id), plan_code: form.plan_code, semantic_version: form.semantic_version.trim() },
        ...recentVersions.value.filter((item) => item.id !== String(created.id))
      ];
    }
    notice.value = "版本草稿已创建。下面可以直接送审、批准并上线。";
    versionDialog.value.open = false;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "版本创建失败";
  } finally { busy.value = false; }
}

async function transitionVersion(versionId: string, action: "submit-review" | "approve" | "activate" | "retire") {
  if (!versionId.trim()) {
    error.value = "请先填写或选择版本编号。";
    return;
  }
  const label = { "submit-review": "送审", approve: "批准", activate: "上线", retire: "下线" }[action];
  if (action === "retire" && !window.confirm("确认下线该版本？下线后新的购买不会再使用它。")) return;
  await run(`版本${label}`, () => membershipAdminApi.transitionVersion(versionId.trim(), action));
}

async function createBenefit() {
  const form = benefitDialog.value;
  const schema = parseJson(form.value_schema, "权益取值结构");
  if (!schema) return;
  if (form.benefit_code.trim().length < 3 || form.owning_module.trim().length < 2) {
    error.value = "请填写权益代码与归属模块。";
    return;
  }
  const ok = await run("权益登记", () => membershipAdminApi.createBenefit({
    benefit_code: form.benefit_code.trim(),
    semantic_version: form.semantic_version.trim(),
    benefit_type: form.benefit_type,
    value_schema: schema,
    owning_module: form.owning_module.trim(),
    sensitivity: form.sensitivity
  }));
  if (ok) form.open = false;
}

async function createSkuMapping() {
  const form = skuDialog.value;
  if (!form.catalog_sku_id.trim() || !form.membership_plan_id.trim() || !form.membership_plan_version_id.trim()) {
    error.value = "请填写商品 SKU、会员计划与计划版本三个编号。";
    return;
  }
  if (!form.valid_from) {
    error.value = "请填写映射生效时间。";
    return;
  }
  const ok = await run("SKU 映射创建", () => membershipAdminApi.createSkuMapping({
    catalog_sku_id: form.catalog_sku_id.trim(),
    membership_plan_id: form.membership_plan_id.trim(),
    membership_plan_version_id: form.membership_plan_version_id.trim(),
    billing_period: form.billing_period,
    valid_from: form.valid_from,
    valid_until: form.valid_until || null
  }));
  if (ok) form.open = false;
}

function openQuotaDialog(row: MembershipAdminRow) {
  error.value = "";
  quotaDialog.value = {
    open: true,
    bucket_id: String(row.id ?? ""),
    quantity: 0,
    adjustment_type: "credit",
    reason_code: "",
    reason: ""
  };
}

async function adjustQuota() {
  const form = quotaDialog.value;
  if (!form.quantity) {
    error.value = "调整数量不能为 0；增加填正数，扣减填负数。";
    return;
  }
  if (form.reason_code.trim().length < 3) {
    error.value = "请填写原因代码。";
    return;
  }
  if (form.reason.trim().length < 10) {
    error.value = "请填写至少 10 个字符的调整说明，说明会写入配额审计。";
    return;
  }
  const ok = await run("配额调整", () => membershipAdminApi.adjustQuota(form.bucket_id, {
    quantity: form.quantity,
    adjustment_type: form.adjustment_type,
    reason_code: form.reason_code.trim(),
    reason: form.reason.trim()
  }));
  if (ok) form.open = false;
}

async function createGrant() {
  const form = grantDialog.value;
  if (!form.user_id.trim() || !form.membership_plan_version_id.trim()) {
    error.value = "请填写用户编号与要授予的计划版本编号。";
    return;
  }
  if (form.reason_code.trim().length < 3) {
    error.value = "请填写原因代码。";
    return;
  }
  if (!form.starts_at || !form.expires_at) {
    error.value = "请填写起止时间；人工赠送必须有到期时间。";
    return;
  }
  const ok = await run("人工赠送创建", () => membershipAdminApi.createManualGrant({
    user_id: form.user_id.trim(),
    membership_plan_version_id: form.membership_plan_version_id.trim(),
    grant_type: form.grant_type,
    reason_code: form.reason_code.trim(),
    reason: form.reason.trim() || null,
    starts_at: form.starts_at,
    expires_at: form.expires_at
  }));
  if (ok) {
    notice.value = "赠送已登记，需另一位具备审批权限的管理员批准后才会生效。";
    form.open = false;
  }
}

async function decideGrant(row: MembershipAdminRow, action: "approve" | "revoke") {
  if (action === "revoke" && !window.confirm("确认撤销该人工赠送？用户会立即失去对应权益。")) return;
  await run(action === "approve" ? "赠送批准" : "赠送撤销", () =>
    membershipAdminApi.decideManualGrant(String(row.id), action)
  );
}

async function createTrial() {
  const form = trialDialog.value;
  const eligibility = parseJson(form.eligibility_policy, "试用资格策略");
  if (!eligibility) return;
  if (!form.policy_code.trim() || !form.membership_plan_version_id.trim()) {
    error.value = "请填写策略代码与关联的计划版本编号。";
    return;
  }
  const ok = await run("试用策略创建", () => membershipAdminApi.createTrialPolicy({
    policy_code: form.policy_code.trim(),
    semantic_version: form.semantic_version.trim(),
    membership_plan_version_id: form.membership_plan_version_id.trim(),
    duration_days: Number(form.duration_days) || 14,
    eligibility_policy: eligibility,
    requires_payment_method: form.requires_payment_method,
    auto_converts: form.auto_converts
  }));
  if (ok) form.open = false;
}

async function resolve(id: string) {
  if (resolution.value.trim().length < 3 || !window.confirm("确认已从权威 Commerce/Entitlement 数据修复，并关闭此对账问题？")) return;
  await run("对账问题处理", () => membershipAdminApi.resolveIssue(id, resolution.value));
}

watch(() => route.fullPath, load); onMounted(load);
</script>

<template>
  <section class="membership-admin">
    <header>
      <div>
        <p class="eyebrow">
          第 17 批 · 权益治理
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
        <small>{{ localizeAdminLabel(key) }}</small><strong>{{ localizeAdminValue(value, key) }}</strong>
      </article>
    </div>
    <article
      v-else
      class="panel"
    >
      <div
        v-if="section === 'plans' && canCreatePlan"
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

      <div
        v-if="section === 'plan-versions'"
        class="editor version-console"
      >
        <h2>版本生命周期</h2>
        <p class="hint">
          后端没有提供版本列表端点，因此这里显示每个计划的当前版本；本次会话中新建的版本会留在下方，其它版本可直接粘贴版本编号操作。
        </p>
        <ul v-if="recentVersions.length">
          <li
            v-for="item in recentVersions"
            :key="item.id"
          >
            {{ item.plan_code }} · v{{ item.semantic_version }} · {{ item.id }}
            <button @click="transitionVersion(item.id, 'submit-review')">
              送审
            </button>
            <button
              v-if="canApproveVersion"
              @click="transitionVersion(item.id, 'approve')"
            >
              批准
            </button>
            <button
              v-if="canActivateVersion"
              @click="transitionVersion(item.id, 'activate')"
            >
              上线
            </button>
          </li>
        </ul>
        <input
          v-model="versionIdInput"
          placeholder="版本编号（UUID）"
        >
        <button @click="transitionVersion(versionIdInput, 'submit-review')">
          送审
        </button>
        <button
          v-if="canApproveVersion"
          @click="transitionVersion(versionIdInput, 'approve')"
        >
          批准
        </button>
        <button
          v-if="canActivateVersion"
          @click="transitionVersion(versionIdInput, 'activate')"
        >
          上线
        </button>
        <button
          v-if="canRetireVersion"
          @click="transitionVersion(versionIdInput, 'retire')"
        >
          下线
        </button>
      </div>

      <div
        v-if="section === 'benefits' && canManageBenefits"
        class="editor"
      >
        <button @click="benefitDialog.open = true">
          登记权益
        </button>
      </div>
      <div
        v-if="section === 'sku-mappings'"
        class="editor"
      >
        <p class="hint">
          SKU 映射把商品 SKU 绑定到具体的会员计划版本。后端没有列表端点，此处只提供创建入口；已有映射请在商品中心核对。
        </p>
        <button
          v-if="canManageSkuMappings"
          @click="skuDialog.open = true"
        >
          创建 SKU 映射
        </button>
      </div>
      <div
        v-if="section === 'manual-grants' && canCreateGrant"
        class="editor"
      >
        <button @click="grantDialog.open = true">
          新建人工赠送
        </button>
      </div>
      <div
        v-if="section === 'trials' && canManageTrials"
        class="editor"
      >
        <button @click="trialDialog.open = true">
          新建试用策略
        </button>
      </div>

      <p v-if="!['plans','benefits','reconciliation','plan-versions','sku-mappings','manual-grants','quotas','trials'].includes(section)">
        此视图坚持最小披露。生产操作必须使用对应权限、原因代码、幂等键和追加式审计；Subscription 与付款状态只能由 Commerce 修改。
      </p>
      <table v-if="rows.length">
        <thead><tr><th>编号或代码</th><th>类型</th><th>状态</th><th>安全操作</th></tr></thead><tbody>
          <tr
            v-for="row in rows"
            :key="String(row.id ?? row.plan_code ?? row.benefit_code)"
          >
            <td>{{ row.plan_code ?? row.benefit_code ?? row.issue_code ?? row.id }}</td><td>{{ localizeAdminValue(row.plan_type ?? row.benefit_type ?? row.severity, "type") }}</td><td>{{ localizeAdminValue(row.status, "status") }}</td><td>
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
              </div>
              <div v-else-if="section === 'plans' && canUpdatePlan">
                <button @click="openVersionDialog(row)">
                  新建版本
                </button>
              </div>
              <div v-else-if="section === 'plan-versions' && canUpdatePlan">
                <button @click="openVersionDialog(row)">
                  新建版本
                </button>
                <button
                  v-if="row.current_version_id && canActivateVersion"
                  @click="transitionVersion(String(row.current_version_id), 'retire')"
                >
                  下线当前版本
                </button>
              </div>
              <div v-else-if="section === 'quotas' && canAdjustQuota">
                <button @click="openQuotaDialog(row)">
                  调整额度
                </button>
              </div>
              <div v-else-if="section === 'manual-grants'">
                <button
                  v-if="canApproveGrant && row.status === 'pending_approval'"
                  @click="decideGrant(row, 'approve')"
                >
                  批准
                </button>
                <button
                  v-if="canRevokeGrant && ['approved','active'].includes(String(row.status))"
                  @click="decideGrant(row, 'revoke')"
                >
                  撤销
                </button>
              </div>
              <span v-else>只读</span>
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
          <small>{{ localizeAdminLabel(key) }}</small><strong>{{ localizeAdminValue(value, key) }}</strong>
        </article>
      </div>
    </article>

    <VModal
      :open="versionDialog.open"
      title="新建计划版本"
      @close="versionDialog.open = false"
      @confirm="createVersion"
    >
      <VFormField
        label="语义化版本"
        hint="例如 1.0.0"
        required
      >
        <input v-model="versionDialog.semantic_version">
      </VFormField>
      <VFormField
        label="展示名称"
        required
      >
        <input v-model="versionDialog.display_name">
      </VFormField>
      <VFormField
        label="生效时间"
        required
      >
        <input
          v-model="versionDialog.valid_from"
          type="datetime-local"
        >
      </VFormField>
      <VFormField
        label="失效时间"
        hint="留空表示长期有效。"
      >
        <input
          v-model="versionDialog.valid_until"
          type="datetime-local"
        >
      </VFormField>
      <template #confirm>
        创建版本
      </template>
    </VModal>

    <VModal
      :open="benefitDialog.open"
      title="登记权益"
      @close="benefitDialog.open = false"
      @confirm="createBenefit"
    >
      <VFormField
        label="权益代码"
        required
      >
        <input v-model="benefitDialog.benefit_code">
      </VFormField>
      <VFormField
        label="语义化版本"
        required
      >
        <input v-model="benefitDialog.semantic_version">
      </VFormField>
      <VFormField
        label="权益类型"
        required
      >
        <select v-model="benefitDialog.benefit_type">
          <option
            v-for="type in BENEFIT_TYPES"
            :key="type"
            :value="type"
          >
            {{ type }}
          </option>
        </select>
      </VFormField>
      <VFormField
        label="归属模块"
        hint="谁是这项权益的权威来源，例如 counseling。"
        required
      >
        <input v-model="benefitDialog.owning_module">
      </VFormField>
      <VFormField label="敏感级别">
        <select v-model="benefitDialog.sensitivity">
          <option value="public">
            公开
          </option>
          <option value="internal">
            内部
          </option>
          <option value="sensitive">
            敏感
          </option>
        </select>
      </VFormField>
      <VFormField
        label="取值结构"
        hint="JSON 对象，描述该权益的取值形态。"
        required
      >
        <textarea
          v-model="benefitDialog.value_schema"
          rows="3"
        />
      </VFormField>
      <template #confirm>
        登记
      </template>
    </VModal>

    <VModal
      :open="skuDialog.open"
      title="创建 SKU 映射"
      @close="skuDialog.open = false"
      @confirm="createSkuMapping"
    >
      <VFormField
        label="商品 SKU 编号"
        required
      >
        <input v-model="skuDialog.catalog_sku_id">
      </VFormField>
      <VFormField
        label="会员计划编号"
        required
      >
        <input v-model="skuDialog.membership_plan_id">
      </VFormField>
      <VFormField
        label="计划版本编号"
        required
      >
        <input v-model="skuDialog.membership_plan_version_id">
      </VFormField>
      <VFormField
        label="计费周期"
        required
      >
        <select v-model="skuDialog.billing_period">
          <option value="monthly">
            按月
          </option>
          <option value="yearly">
            按年
          </option>
          <option value="custom">
            自定义
          </option>
          <option value="none">
            一次性
          </option>
        </select>
      </VFormField>
      <VFormField
        label="生效时间"
        required
      >
        <input
          v-model="skuDialog.valid_from"
          type="datetime-local"
        >
      </VFormField>
      <VFormField label="失效时间">
        <input
          v-model="skuDialog.valid_until"
          type="datetime-local"
        >
      </VFormField>
      <template #confirm>
        创建映射
      </template>
    </VModal>

    <VModal
      :open="quotaDialog.open"
      title="调整配额额度"
      @close="quotaDialog.open = false"
      @confirm="adjustQuota"
    >
      <VFormField
        label="调整数量"
        hint="增加填正数，扣减填负数；不允许为 0。"
        required
      >
        <input
          v-model.number="quotaDialog.quantity"
          type="number"
        >
      </VFormField>
      <VFormField
        label="调整类型"
        required
      >
        <select v-model="quotaDialog.adjustment_type">
          <option
            v-for="option in ADJUSTMENT_TYPES"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </option>
        </select>
      </VFormField>
      <VFormField
        label="原因代码"
        required
      >
        <input v-model="quotaDialog.reason_code">
      </VFormField>
      <VFormField
        label="调整说明"
        hint="至少 10 个字符，会写入配额审计。"
        required
      >
        <textarea
          v-model="quotaDialog.reason"
          rows="3"
        />
      </VFormField>
      <template #confirm>
        提交调整
      </template>
    </VModal>

    <VModal
      :open="grantDialog.open"
      title="新建人工赠送"
      @close="grantDialog.open = false"
      @confirm="createGrant"
    >
      <p class="hint">
        赠送需要另一位具备审批权限的管理员批准后才生效，且必须有到期时间。
      </p>
      <VFormField
        label="用户编号"
        required
      >
        <input v-model="grantDialog.user_id">
      </VFormField>
      <VFormField
        label="计划版本编号"
        required
      >
        <input v-model="grantDialog.membership_plan_version_id">
      </VFormField>
      <VFormField
        label="赠送类型"
        required
      >
        <select v-model="grantDialog.grant_type">
          <option
            v-for="option in GRANT_TYPES"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </option>
        </select>
      </VFormField>
      <VFormField
        label="原因代码"
        required
      >
        <input v-model="grantDialog.reason_code">
      </VFormField>
      <VFormField label="补充说明">
        <textarea
          v-model="grantDialog.reason"
          rows="2"
        />
      </VFormField>
      <VFormField
        label="生效时间"
        required
      >
        <input
          v-model="grantDialog.starts_at"
          type="datetime-local"
        >
      </VFormField>
      <VFormField
        label="到期时间"
        required
      >
        <input
          v-model="grantDialog.expires_at"
          type="datetime-local"
        >
      </VFormField>
      <template #confirm>
        提交赠送
      </template>
    </VModal>

    <VModal
      :open="trialDialog.open"
      title="新建试用策略"
      @close="trialDialog.open = false"
      @confirm="createTrial"
    >
      <VFormField
        label="策略代码"
        required
      >
        <input v-model="trialDialog.policy_code">
      </VFormField>
      <VFormField
        label="语义化版本"
        required
      >
        <input v-model="trialDialog.semantic_version">
      </VFormField>
      <VFormField
        label="计划版本编号"
        required
      >
        <input v-model="trialDialog.membership_plan_version_id">
      </VFormField>
      <VFormField
        label="试用天数"
        hint="1–365 天。"
        required
      >
        <input
          v-model.number="trialDialog.duration_days"
          type="number"
          min="1"
          max="365"
        >
      </VFormField>
      <VFormField
        label="资格策略"
        hint="JSON 对象，描述谁可以试用。"
        required
      >
        <textarea
          v-model="trialDialog.eligibility_policy"
          rows="3"
        />
      </VFormField>
      <VFormField label="需要绑定支付方式">
        <input
          v-model="trialDialog.requires_payment_method"
          type="checkbox"
        >
      </VFormField>
      <VFormField label="到期自动转正">
        <input
          v-model="trialDialog.auto_converts"
          type="checkbox"
        >
      </VFormField>
      <template #confirm>
        创建策略
      </template>
    </VModal>
  </section>
</template>

<style scoped>
.membership-admin{display:grid;gap:1rem}header{display:flex;justify-content:space-between;gap:2rem;align-items:end}header>p{max-width:620px}.eyebrow{letter-spacing:.12em;color:var(--vav-color-accent)}nav{display:flex;gap:.55rem;flex-wrap:wrap}nav a{padding:.5rem .8rem;border-radius:999px;background:var(--vav-color-surface-soft);color:var(--vav-color-text);text-decoration:none}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem}.metrics article,.panel{padding:1rem;border:1px solid var(--vav-color-border);border-radius:12px;background:white}.metrics strong{display:block;margin-top:.5rem;overflow-wrap:anywhere}.editor{display:flex;gap:.6rem;align-items:end;flex-wrap:wrap;padding:1rem;background:var(--vav-color-surface-soft);margin-bottom:1rem}.editor h2{width:100%}.version-console ul{width:100%;list-style:none;padding:0;display:grid;gap:.5rem}.version-console li{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;overflow-wrap:anywhere}.hint{width:100%;color:var(--vav-color-text-muted);margin:0}input,select,textarea{padding:.65rem;border:1px solid var(--vav-color-border-strong);border-radius:8px}button{padding:.65rem .9rem;border:0;border-radius:999px;background:var(--vav-color-success);color:white}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:.75rem;border-bottom:1px solid var(--vav-color-surface-sunken)}.alert{padding:.8rem}.error{background:var(--vav-color-surface-danger)}.notice{background:var(--vav-color-surface-success)}@media(max-width:700px){header{align-items:start;flex-direction:column}table{display:block;overflow:auto}}
</style>
