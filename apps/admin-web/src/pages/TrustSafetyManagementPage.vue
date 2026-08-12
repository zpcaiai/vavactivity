<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { localizeAdminValue } from "@vav/ui-admin";
import { VFormField, VModal } from "@vav/ui-core";

import {
  CASE_TRANSITIONS,
  HIGH_IMPACT_RESTRICTIONS,
  RESTRICTION_TYPES,
  safetyAdminApi,
  type SafetyAdminRow
} from "@/features/trust-safety/api";
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

const canManageCase = computed(() => auth.hasPermission("safety.cases.manage"));
const canDecideModeration = computed(() => auth.hasPermission("safety.moderation.decide"));
const canDecideAppeal = computed(() => auth.hasPermission("safety.appeals.decide"));
const canActivateRule = computed(() => auth.hasPermission("safety.rules.activate"));
const canCreateRestriction = computed(() => auth.hasPermission("safety.restrictions.create"));
const canApproveRestriction = computed(() =>
  auth.hasPermission("safety.restrictions.high_impact.approve")
);
const canLiftRestriction = computed(() => auth.hasPermission("safety.restrictions.lift"));

const STATUS_LABELS: Record<string, string> = {
  triaged: "已分诊",
  assigned: "已指派",
  investigating: "调查中",
  pending_action: "待执行",
  resolved: "已处置",
  closed: "已关闭",
  reopened: "重新打开"
};

const MODERATION_DECISIONS = [
  { value: "approve", label: "通过" },
  { value: "reject", label: "拒绝" },
  { value: "limit", label: "限制展示" },
  { value: "remove", label: "下架" },
  { value: "escalate", label: "升级人工复核" }
];

const APPEAL_OUTCOMES = [
  { value: "upheld", label: "维持原处置" },
  { value: "modified", label: "调整处置" },
  { value: "overturned", label: "撤销处置" },
  { value: "ineligible", label: "不受理" }
];

/** Only the moves the backend's state machine allows from this row's status. */
function caseTransitions(row: SafetyAdminRow) {
  return CASE_TRANSITIONS[String(row.status ?? "")] ?? [];
}

function isHighImpact(row: SafetyAdminRow) {
  return HIGH_IMPACT_RESTRICTIONS.includes(String(row.restriction_type ?? ""));
}

const moderationDialog = ref({
  open: false,
  task_id: "",
  decision: "escalate",
  category_codes: "",
  reason_code: "",
  user_message: "",
  internal_note: ""
});
const appealDialog = ref({
  open: false,
  appeal_id: "",
  outcome: "upheld",
  outcome_message: "",
  internal_review: ""
});
const restrictionDialog = ref({
  open: false,
  user_id: "",
  restriction_type: "profile_hidden",
  source_type: "manual",
  reason_code: "",
  user_message: "",
  internal_reason: "",
  starts_at: "",
  ends_at: "",
  appeal_allowed: true
});
const liftDialog = ref({ open: false, restriction_id: "", reason: "" });

function splitCodes(value: string) {
  return value.split(/[,，\s]+/u).map((item) => item.trim()).filter(Boolean);
}

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

async function run(label: string, action: () => Promise<unknown>) {
  busy.value = true;
  error.value = "";
  try {
    await action();
    notice.value = `${label}已完成，并已追加安全审计。`;
    await load();
    return true;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : `${label}失败`;
    return false;
  } finally {
    busy.value = false;
  }
}

async function transitionCase(row: SafetyAdminRow, target: string) {
  await run(`案件流转到「${STATUS_LABELS[target] ?? target}」`, () =>
    safetyAdminApi.transitionCase(String(row.id), target)
  );
}

function openModeration(row: SafetyAdminRow) {
  error.value = "";
  moderationDialog.value = {
    open: true,
    task_id: String(row.id),
    decision: "escalate",
    category_codes: "",
    reason_code: "",
    user_message: "",
    internal_note: ""
  };
}

async function decideModeration() {
  const form = moderationDialog.value;
  const categories = splitCodes(form.category_codes);
  // A removal or limit with no category is an unexplainable decision: the user
  // gets told their content was actioned but not under which rule.
  if (["remove", "limit", "reject"].includes(form.decision) && !categories.length) {
    error.value = "下架、限制或拒绝必须至少填写一个违规类别代码。";
    return;
  }
  if (form.internal_note.trim().length < 10) {
    error.value = "请填写至少 10 个字符的内部说明，供复核与申诉时还原判断依据。";
    return;
  }
  const ok = await run("审核决定", () =>
    safetyAdminApi.decideModeration(form.task_id, {
      decision: form.decision,
      category_codes: categories,
      reason_code: form.reason_code.trim() || null,
      user_message: form.user_message.trim() || null,
      internal_note: form.internal_note.trim()
    })
  );
  if (ok) form.open = false;
}

function openAppeal(row: SafetyAdminRow) {
  error.value = "";
  appealDialog.value = {
    open: true,
    appeal_id: String(row.id),
    outcome: "upheld",
    outcome_message: "",
    internal_review: ""
  };
}

async function decideAppeal() {
  const form = appealDialog.value;
  if (form.outcome === "modified") {
    error.value = "「调整处置」需要同时提交调整后的范围或到期时间，当前控制台不支持；请改用维持、撤销或不受理。";
    return;
  }
  if (form.outcome_message.trim().length < 3 || form.internal_review.trim().length < 3) {
    error.value = "请同时填写给申诉人的结论说明与内部复核记录。";
    return;
  }
  const ok = await run("申诉裁决", () =>
    safetyAdminApi.decideAppeal(form.appeal_id, {
      outcome: form.outcome,
      outcome_message: form.outcome_message.trim(),
      internal_review: form.internal_review.trim()
    })
  );
  if (ok) form.open = false;
}

async function activateRule(row: SafetyAdminRow) {
  if (!window.confirm("确认已经由另一位管理员审阅，并接受灰度与回滚责任？")) return;
  await run("规则激活", () => safetyAdminApi.activateRule(String(row.id)));
}

async function createRestriction() {
  const form = restrictionDialog.value;
  if (!form.user_id.trim()) {
    error.value = "请填写被限制的用户编号。";
    return;
  }
  if (form.reason_code.trim().length < 3) {
    error.value = "请填写原因代码。";
    return;
  }
  if (!form.starts_at) {
    error.value = "请填写限制生效时间。";
    return;
  }
  if (HIGH_IMPACT_RESTRICTIONS.includes(form.restriction_type)
    && !window.confirm("这是高影响限制，创建后需要另一位管理员批准才会生效。确认继续？")) return;
  const ok = await run("限制创建", () =>
    safetyAdminApi.createRestriction({
      user_id: form.user_id.trim(),
      restriction_type: form.restriction_type,
      scope_definition: {},
      source_type: form.source_type,
      reason_code: form.reason_code.trim(),
      user_message: form.user_message.trim() || null,
      internal_reason: form.internal_reason.trim() || null,
      starts_at: form.starts_at,
      ends_at: form.ends_at || null,
      appeal_allowed: form.appeal_allowed
    })
  );
  if (ok) form.open = false;
}

async function approveRestriction(row: SafetyAdminRow) {
  if (!window.confirm("确认批准该高影响限制？批准人必须与创建人不同。")) return;
  await run("限制批准", () => safetyAdminApi.approveRestriction(String(row.id)));
}

function openLift(row: SafetyAdminRow) {
  error.value = "";
  liftDialog.value = { open: true, restriction_id: String(row.id), reason: "" };
}

async function liftRestriction() {
  const form = liftDialog.value;
  if (form.reason.trim().length < 10) {
    error.value = "请填写至少 10 个字符的解除理由。";
    return;
  }
  const ok = await run("限制解除", () =>
    safetyAdminApi.liftRestriction(form.restriction_id, form.reason.trim())
  );
  if (ok) form.open = false;
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
      <div
        v-if="section === 'restrictions' && canCreateRestriction"
        class="panel-toolbar"
      >
        <button @click="restrictionDialog.open = true">
          新建账号限制
        </button>
      </div>
      <table>
        <thead><tr><th>ID / 编号</th><th>类别</th><th>状态</th><th>最小安全操作</th></tr></thead><tbody>
          <tr
            v-for="row in rows"
            :key="String(row.id)"
          >
            <td>{{ row.report_number ?? row.case_number ?? row.appeal_number ?? row.rule_code ?? row.run_number ?? row.id }}</td><td>{{ localizeAdminValue(row.category ?? row.primary_category ?? row.target_type ?? row.restriction_type ?? row.rule_type ?? row.signal_code ?? row.metric_code ?? row.event_type, "type") }}</td><td>{{ localizeAdminValue(row.status ?? 'recorded', "status") }}</td><td>
              <template v-if="section === 'cases' && canManageCase">
                <button
                  v-for="target in caseTransitions(row)"
                  :key="target"
                  @click="transitionCase(row, target)"
                >
                  {{ STATUS_LABELS[target] ?? target }}
                </button>
                <span v-if="!caseTransitions(row).length">无可用流转</span>
              </template>
              <button
                v-else-if="section === 'moderation' && canDecideModeration"
                @click="openModeration(row)"
              >
                作出审核决定
              </button>
              <button
                v-else-if="section === 'appeals' && canDecideAppeal"
                @click="openAppeal(row)"
              >
                裁决申诉
              </button>
              <button
                v-else-if="section === 'rules' && canActivateRule"
                @click="activateRule(row)"
              >
                双人审批激活
              </button>
              <template v-else-if="section === 'restrictions'">
                <button
                  v-if="canApproveRestriction && isHighImpact(row) && row.status === 'pending_approval'"
                  @click="approveRestriction(row)"
                >
                  批准
                </button>
                <button
                  v-if="canLiftRestriction && ['active','pending_approval'].includes(String(row.status))"
                  @click="openLift(row)"
                >
                  解除
                </button>
                <span v-if="!canApproveRestriction && !canLiftRestriction">只读最小披露</span>
              </template>
              <span v-else>只读最小披露</span>
            </td>
          </tr>
        </tbody>
      </table><p v-if="!rows.length && !busy">
        队列为空。
      </p>
    </article>

    <VModal
      :open="moderationDialog.open"
      title="内容审核决定"
      @close="moderationDialog.open = false"
      @confirm="decideModeration"
    >
      <VFormField
        label="决定"
        required
      >
        <select v-model="moderationDialog.decision">
          <option
            v-for="option in MODERATION_DECISIONS"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </option>
        </select>
      </VFormField>
      <VFormField
        label="违规类别代码"
        hint="多个用逗号分隔。下架、限制或拒绝时必填，否则用户只知道被处置、不知道依据哪条规则。"
      >
        <input v-model="moderationDialog.category_codes">
      </VFormField>
      <VFormField label="原因代码">
        <input v-model="moderationDialog.reason_code">
      </VFormField>
      <VFormField
        label="给用户的说明"
        hint="会展示给内容作者，不要包含调查细节。"
      >
        <textarea
          v-model="moderationDialog.user_message"
          rows="2"
        />
      </VFormField>
      <VFormField
        label="内部说明"
        hint="至少 10 个字符，供复核与申诉时还原判断依据。"
        required
      >
        <textarea
          v-model="moderationDialog.internal_note"
          rows="3"
        />
      </VFormField>
      <template #confirm>
        提交决定
      </template>
    </VModal>

    <VModal
      :open="appealDialog.open"
      title="申诉裁决"
      @close="appealDialog.open = false"
      @confirm="decideAppeal"
    >
      <VFormField
        label="裁决结果"
        required
      >
        <select v-model="appealDialog.outcome">
          <option
            v-for="option in APPEAL_OUTCOMES"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </option>
        </select>
      </VFormField>
      <VFormField
        label="给申诉人的结论"
        required
      >
        <textarea
          v-model="appealDialog.outcome_message"
          rows="3"
        />
      </VFormField>
      <VFormField
        label="内部复核记录"
        required
      >
        <textarea
          v-model="appealDialog.internal_review"
          rows="3"
        />
      </VFormField>
      <template #confirm>
        提交裁决
      </template>
    </VModal>

    <VModal
      :open="restrictionDialog.open"
      title="新建账号限制"
      dangerous
      @close="restrictionDialog.open = false"
      @confirm="createRestriction"
    >
      <p class="hint">
        永久停用、临时封禁与要求重新验证属于高影响限制，创建后需要另一位管理员批准才会生效。
      </p>
      <VFormField
        label="用户编号"
        required
      >
        <input v-model="restrictionDialog.user_id">
      </VFormField>
      <VFormField
        label="限制类型"
        required
      >
        <select v-model="restrictionDialog.restriction_type">
          <option
            v-for="type in RESTRICTION_TYPES"
            :key="type"
            :value="type"
          >
            {{ type }}
          </option>
        </select>
      </VFormField>
      <VFormField
        label="来源"
        required
      >
        <select v-model="restrictionDialog.source_type">
          <option value="manual">
            人工判断
          </option>
          <option value="case">
            安全案件
          </option>
          <option value="rule">
            规则触发
          </option>
          <option value="moderation">
            内容审核
          </option>
        </select>
      </VFormField>
      <VFormField
        label="原因代码"
        required
      >
        <input v-model="restrictionDialog.reason_code">
      </VFormField>
      <VFormField
        label="生效时间"
        required
      >
        <input
          v-model="restrictionDialog.starts_at"
          type="datetime-local"
        >
      </VFormField>
      <VFormField
        label="解除时间"
        hint="留空表示不自动解除；永久停用之外的限制建议给出期限。"
      >
        <input
          v-model="restrictionDialog.ends_at"
          type="datetime-local"
        >
      </VFormField>
      <VFormField label="给用户的说明">
        <textarea
          v-model="restrictionDialog.user_message"
          rows="2"
        />
      </VFormField>
      <VFormField label="内部理由">
        <textarea
          v-model="restrictionDialog.internal_reason"
          rows="3"
        />
      </VFormField>
      <VFormField label="允许申诉">
        <input
          v-model="restrictionDialog.appeal_allowed"
          type="checkbox"
        >
      </VFormField>
      <template #confirm>
        创建限制
      </template>
    </VModal>

    <VModal
      :open="liftDialog.open"
      title="解除账号限制"
      @close="liftDialog.open = false"
      @confirm="liftRestriction"
    >
      <VFormField
        label="解除理由"
        hint="至少 10 个字符，会写入安全审计。"
        required
      >
        <textarea
          v-model="liftDialog.reason"
          rows="3"
        />
      </VFormField>
      <template #confirm>
        解除限制
      </template>
    </VModal>
  </section>
</template>

<style scoped>
.safety-admin{display:grid;gap:1rem}header{display:flex;justify-content:space-between;gap:2rem;align-items:end}header>p{max-width:660px}.eyebrow{letter-spacing:.12em;color:var(--vav-color-danger)}nav{display:flex;gap:.55rem;flex-wrap:wrap}nav a{padding:.5rem .8rem;border-radius:999px;background:var(--vav-color-surface-soft);color:var(--vav-color-text);text-decoration:none}.panel{padding:1rem;border:1px solid var(--vav-color-border);border-radius:12px;background:var(--vav-color-surface-raised)}.panel-toolbar{display:flex;gap:.6rem;flex-wrap:wrap;margin-bottom:1rem}.hint{color:var(--vav-color-text-muted);margin:0 0 .75rem}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:.75rem;border-bottom:1px solid var(--vav-color-surface-sunken)}td button{margin-right:.4rem;margin-bottom:.3rem}button{padding:.6rem .85rem;border:0;border-radius:999px;background:var(--vav-color-danger);color:white}input,select,textarea{padding:.6rem;border:1px solid var(--vav-color-border-strong);border-radius:8px}.alert{padding:.8rem}.error{background:var(--vav-color-surface-danger)}.notice{background:var(--vav-color-surface-success)}@media(max-width:700px){header{align-items:start;flex-direction:column}table{display:block;overflow:auto}}
</style>
