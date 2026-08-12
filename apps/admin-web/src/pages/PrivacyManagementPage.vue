<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { formatAdminTableCell, localizeAdminValue } from "@vav/ui-admin";

import { catalogApi } from "@/features/catalog/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

type Dashboard = { requests: Array<{ request_type: string; status: string; count: number }>; blocked_erasures: number; active_holds: number; break_glass_pending: number; retention_due: number };
type Row = Record<string, unknown> & { id?: string; status?: string };

const route = useRoute();
const auth = useAdminAuthStore();
const section = ref(String(route.meta.privacySection ?? "dashboard"));
const dashboard = ref<Dashboard>();
const rows = ref<Row[]>([]);
const busy = ref(false);
const error = ref("");
const notice = ref("");
/**
 * Starts empty on purpose. It used to be pre-filled with a canned sentence that
 * satisfied the backend's minimum length, so every privacy action in the audit
 * trail carried the same manufactured justification.
 */
const reason = ref("");
const userMessage = ref("");

const sections = [
  ["dashboard", "总览", "privacy.requests.read"],
  ["requests", "数据权利请求", "privacy.requests.read"],
  ["exports", "加密导出", "privacy.exports.read"],
  ["consents", "同意注册表", "privacy.consents.read"],
  ["consent-releases", "同意版本", "privacy.consents.read"],
  ["inventory", "数据清单", "privacy.inventory.read"],
  ["processing", "处理活动", "privacy.inventory.read"],
  ["classifications", "敏感分类", "privacy.classifications.read"],
  ["corrections", "更正", "privacy.corrections.read"],
  ["erasures", "删除计划", "privacy.erasures.read"],
  ["retention", "保留策略", "privacy.retention.read"],
  ["retention-instances", "保留实例", "privacy.retention.read"],
  ["holds", "法律与调查留置", "privacy.holds.read"],
  ["break-glass", "紧急访问", "privacy.break_glass.read"],
  ["access-events", "敏感访问", "privacy.sensitive_access.read"],
  ["incidents", "隐私信号", "privacy.incidents.read"],
  ["audit", "隐私审计", "privacy.audit.read"]
] as const;

const endpointBySection: Record<string, string> = {
  requests: "/admin/privacy/requests",
  exports: "/admin/privacy/exports",
  consents: "/admin/privacy/consents",
  "consent-releases": "/admin/privacy/consent-releases",
  inventory: "/admin/privacy/data-inventory",
  processing: "/admin/privacy/processing-activities",
  classifications: "/admin/privacy/classifications",
  corrections: "/admin/privacy/corrections",
  erasures: "/admin/privacy/erasures",
  retention: "/admin/privacy/retention-policies",
  "retention-instances": "/admin/privacy/retention-instances",
  holds: "/admin/privacy/legal-holds",
  "break-glass": "/admin/privacy/break-glass",
  "access-events": "/admin/privacy/access-events",
  incidents: "/admin/privacy/incidents",
  audit: "/admin/privacy/audit"
};

const HOLD_TYPES = [
  { value: "legal", label: "法律留置" },
  { value: "security_investigation", label: "安全调查" },
  { value: "fraud_investigation", label: "欺诈调查" },
  { value: "safety_case", label: "安全个案" },
  { value: "payment_dispute", label: "支付争议" }
];

const BREAK_GLASS_PURPOSES = [
  { value: "security_incident", label: "安全事件" },
  { value: "approved_safety_referral", label: "已批准的安全转介" },
  { value: "account_takeover_investigation", label: "账号盗用调查" },
  { value: "payment_fraud_investigation", label: "支付欺诈调查" }
];

const canVerifyIdentity = computed(() => auth.hasPermission("privacy.requests.verify_identity"));
const canGenerateExport = computed(() => auth.hasPermission("privacy.exports.generate"));
const canCreateHold = computed(() => auth.hasPermission("privacy.holds.create"));
const canReleaseHold = computed(() => auth.hasPermission("privacy.holds.release"));
const canRequestBreakGlass = computed(() => auth.hasPermission("privacy.break_glass.request"));

const holdDialog = ref({
  open: false,
  hold_type: "legal",
  subject_user_id: "",
  module_codes: "",
  reason: "",
  authorized_by: "",
  ends_at: ""
});
const breakGlassDialog = ref({
  open: false,
  subject_user_id: "",
  data_scope: "",
  purpose: "security_incident",
  reason: ""
});

function splitCodes(value: string) {
  return value
    .split(/[,，\s]+/u)
    .map((item) => item.trim())
    .filter(Boolean);
}

/** The backend floor is 8 characters; 10 keeps the trail readable. */
function requireReason(minimum = 10) {
  if (reason.value.trim().length >= minimum) return true;
  error.value = `请先在上方填写至少 ${minimum} 个字符的操作原因，原因会写入隐私审计。`;
  return false;
}

function requireUserMessage() {
  if (userMessage.value.trim().length >= 3) return true;
  error.value = "请填写给用户看的说明；该文案会直接展示给数据主体。";
  return false;
}

async function load() {
  busy.value = true;
  error.value = "";
  rows.value = [];
  try {
    await auth.bootstrap();
    if (section.value === "dashboard") {
      dashboard.value = await catalogApi<Dashboard>("/admin/privacy/dashboard");
    } else {
      const result = await catalogApi<{ items: Row[] }>(endpointBySection[section.value]);
      rows.value = result.items;
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "隐私运营中心加载失败";
  } finally {
    busy.value = false;
  }
}

async function switchSection(value: string) {
  section.value = value;
  notice.value = "";
  error.value = "";
  await load();
}

async function perform(label: string, action: () => Promise<unknown>) {
  busy.value = true;
  error.value = "";
  try {
    await action();
    notice.value = `${label}已完成。`;
    await load();
    return true;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : `${label}失败`;
    return false;
  } finally {
    busy.value = false;
  }
}

async function requestAction(row: Row, action: "verify-identity" | "approve" | "reject") {
  if (!requireReason() || !requireUserMessage()) return;
  const label = { "verify-identity": "身份核验", approve: "请求批准", reject: "请求拒绝" }[action];
  await perform(label, () =>
    catalogApi(`/admin/privacy/requests/${row.id}/${action}`, {
      method: "POST",
      body: JSON.stringify({
        reason: reason.value.trim(),
        user_visible_message: userMessage.value.trim()
      })
    })
  );
}

async function correctionAction(row: Row, action: "approve" | "reject") {
  if (!requireReason() || !requireUserMessage()) return;
  await perform(action === "approve" ? "更正批准" : "更正拒绝", () =>
    catalogApi(`/admin/privacy/corrections/${row.id}/${action}`, {
      method: "POST",
      body: JSON.stringify({
        reason: reason.value.trim(),
        user_visible_message: userMessage.value.trim()
      })
    })
  );
}

async function processExport(row: Row) {
  await perform("加密导出生成", () =>
    catalogApi(`/admin/privacy/exports/${row.id}/process`, { method: "POST" })
  );
}

async function erasureAction(row: Row, action: "replan" | "approve" | "execute") {
  if (action === "approve" && !requireReason(8)) return;
  if (action === "execute" && !window.confirm("确认执行该删除计划？删除会在各模块真实生效，且不可撤销。")) return;
  const label = { replan: "删除计划重新规划", approve: "删除计划批准", execute: "删除执行" }[action];
  await perform(label, () =>
    catalogApi(`/admin/privacy/erasures/${row.id}/${action}`, {
      method: "POST",
      // The execute and replan endpoints accept no body at all; only approve
      // carries a reason. See the note under the erasure table.
      body: action === "approve" ? JSON.stringify({ reason: reason.value.trim() }) : undefined
    })
  );
}

async function retentionRun() {
  await perform("到期保留评估", async () => {
    const result = await catalogApi<{ items: Row[] }>("/admin/privacy/workers/retention/run", { method: "POST" });
    notice.value = `已评估 ${result.items.length} 个到期实例；有效留置不会被绕过。`;
  });
}

async function breakGlassAction(row: Row, action: "approve" | "use") {
  if (action === "approve" && !requireReason(8)) return;
  if (action === "use" && !window.confirm("确认使用该紧急访问授权？每一次读取都会逐资产写入敏感访问审计。")) return;
  await perform(action === "approve" ? "紧急访问批准" : "紧急访问使用", () =>
    catalogApi(`/admin/privacy/break-glass/${row.id}/${action}`, {
      method: "POST",
      body: action === "approve" ? JSON.stringify({ reason: reason.value.trim() }) : undefined
    })
  );
}

async function createHold() {
  const form = holdDialog.value;
  const modules = splitCodes(form.module_codes);
  if (!form.subject_user_id.trim() || !form.authorized_by.trim()) {
    error.value = "请填写留置对象用户编号与授权人用户编号。";
    return;
  }
  if (!modules.length) {
    error.value = "请至少填写一个受留置的模块代码。";
    return;
  }
  if (form.reason.trim().length < 12) {
    error.value = "请填写至少 12 个字符的留置理由；留置会阻断该用户的删除权利，理由必须可复核。";
    return;
  }
  if (!form.ends_at) {
    error.value = "请填写留置结束时间；留置不得无限期。";
    return;
  }
  const ok = await perform("留置创建", () =>
    catalogApi("/admin/privacy/legal-holds", {
      method: "POST",
      body: JSON.stringify({
        hold_type: form.hold_type,
        subject_user_id: form.subject_user_id.trim(),
        module_codes: modules,
        reason: form.reason.trim(),
        authorized_by: form.authorized_by.trim(),
        ends_at: form.ends_at
      })
    })
  );
  if (ok) form.open = false;
}

async function releaseHold(row: Row) {
  if (!requireReason(8)) return;
  await perform("留置释放", () =>
    catalogApi(`/admin/privacy/legal-holds/${row.id}/release`, {
      method: "POST",
      body: JSON.stringify({ reason: reason.value.trim() })
    })
  );
}

async function requestBreakGlass() {
  const form = breakGlassDialog.value;
  const scope = splitCodes(form.data_scope);
  if (!form.subject_user_id.trim()) {
    error.value = "请填写被访问用户的编号。";
    return;
  }
  if (!scope.length) {
    error.value = "请至少填写一个数据资产代码；紧急访问必须限定范围。";
    return;
  }
  if (form.reason.trim().length < 12) {
    error.value = "请填写至少 12 个字符的申请理由。";
    return;
  }
  const ok = await perform("紧急访问申请", () =>
    catalogApi("/admin/privacy/break-glass", {
      method: "POST",
      body: JSON.stringify({
        subject_user_id: form.subject_user_id.trim(),
        data_scope: scope,
        purpose: form.purpose,
        reason: form.reason.trim()
      })
    })
  );
  if (ok) form.open = false;
}

onMounted(() => void load());
</script>

<template>
  <section class="admin-page privacy-admin-page">
    <div class="page-heading">
      <div>
        <p class="admin-kicker">
          BATCH 12 · DATA RIGHTS & GOVERNANCE
        </p><h2>隐私运营中心</h2><p>统一处理数据权利、同意版本、数据清单、删除、保留、留置与敏感访问。</p>
      </div>
      <el-button
        :loading="busy"
        @click="load"
      >
        刷新
      </el-button>
    </div>
    <el-alert
      title="敏感字段值、导出令牌、留置原因和调查细节默认不显示；遮罩不替代授权。"
      type="warning"
      :closable="false"
    />
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
    />
    <el-alert
      v-if="notice"
      :title="notice"
      type="success"
      show-icon
    />
    <div class="operation-inputs">
      <label>
        <span>操作原因（至少 10 个字符，写入隐私审计）</span>
        <el-input
          v-model="reason"
          type="textarea"
          :rows="2"
          placeholder="写明依据的工单、法律条款或调查编号。"
        />
      </label>
      <label>
        <span>给用户的说明（会直接展示给数据主体）</span>
        <el-input
          v-model="userMessage"
          type="textarea"
          :rows="2"
          placeholder="用用户能读懂的语言说明处理结果，不要包含内部调查细节。"
        />
      </label>
    </div>
    <el-tabs
      :model-value="section"
      @update:model-value="switchSection(String($event))"
    >
      <el-tab-pane
        v-for="item in sections.filter((value) => auth.hasPermission(value[2]))"
        :key="item[0]"
        :name="item[0]"
        :label="item[1]"
      />
    </el-tabs>

    <div
      v-if="section === 'dashboard' && dashboard"
      class="metric-grid"
      aria-label="隐私总览"
    >
      <el-card><strong>{{ dashboard.blocked_erasures }}</strong><span>受阻删除</span></el-card>
      <el-card><strong>{{ dashboard.active_holds }}</strong><span>有效留置</span></el-card>
      <el-card><strong>{{ dashboard.break_glass_pending }}</strong><span>待批紧急访问</span></el-card>
      <el-card><strong>{{ dashboard.retention_due }}</strong><span>到期保留实例</span></el-card>
      <el-card
        v-for="item in dashboard.requests"
        :key="`${item.request_type}-${item.status}`"
      >
        <strong>{{ item.count }}</strong><span>{{ localizeAdminValue(item.request_type, "request_type") }} · {{ localizeAdminValue(item.status, "status") }}</span>
      </el-card>
    </div>

    <div v-else>
      <div class="section-actions">
        <el-button
          v-if="section === 'retention' && auth.hasPermission('privacy.retention.execute')"
          @click="retentionRun"
        >
          执行到期评估
        </el-button>
        <el-button
          v-if="section === 'holds' && canCreateHold"
          type="primary"
          @click="holdDialog.open = true"
        >
          创建留置
        </el-button>
        <el-button
          v-if="section === 'break-glass' && canRequestBreakGlass"
          type="primary"
          @click="breakGlassDialog.open = true"
        >
          申请紧急访问
        </el-button>
      </div>
      <p
        v-if="section === 'erasures' || section === 'break-glass'"
        class="boundary-note"
      >
        执行删除与使用紧急访问这两个动作，后端只接受操作者与时间戳，不接收理由字段；它们的可追溯性来自前一步的批准记录与逐资产访问审计。
      </p>
      <el-table
        :data="rows"
        empty-text="暂无记录"
      >
        <el-table-column
          prop="request_number"
          label="编号"
        />
        <el-table-column
          prop="consent_code"
          label="同意代码"
        />
        <el-table-column
          prop="asset_code"
          label="数据资产"
        />
        <el-table-column
          prop="policy_code"
          label="策略"
        />
        <el-table-column
          prop="event_type"
          label="事件"
        />
        <el-table-column
          prop="user_anonymous_id"
          label="匿名用户"
        />
        <el-table-column
          prop="request_type"
          label="类型"
        />
        <el-table-column
          prop="module_code"
          label="模块"
        />
        <el-table-column
          prop="sensitivity"
          label="敏感级别"
        />
        <el-table-column
          prop="status"
          :formatter="formatAdminTableCell"
          label="状态"
        />
        <el-table-column
          label="操作"
          min-width="300"
        >
          <template #default="scope">
            <template v-if="section === 'requests'">
              <el-button
                v-if="canVerifyIdentity && scope.row.status === 'received'"
                size="small"
                @click="requestAction(scope.row, 'verify-identity')"
              >
                核验身份
              </el-button>
              <template v-if="auth.hasPermission('privacy.requests.approve')">
                <el-button
                  size="small"
                  @click="requestAction(scope.row, 'approve')"
                >
                  批准
                </el-button><el-button
                  size="small"
                  @click="requestAction(scope.row, 'reject')"
                >
                  拒绝
                </el-button>
              </template>
            </template>
            <el-button
              v-if="section === 'exports' && canGenerateExport"
              size="small"
              type="primary"
              @click="processExport(scope.row)"
            >
              生成导出包
            </el-button>
            <template v-if="section === 'corrections' && auth.hasPermission('privacy.corrections.review') && scope.row.status === 'review_required'">
              <el-button
                size="small"
                @click="correctionAction(scope.row, 'approve')"
              >
                批准更正
              </el-button><el-button
                size="small"
                @click="correctionAction(scope.row, 'reject')"
              >
                拒绝
              </el-button>
            </template>
            <template v-if="section === 'erasures'">
              <el-button
                v-if="auth.hasPermission('privacy.erasures.plan')"
                size="small"
                @click="erasureAction(scope.row, 'replan')"
              >
                重新规划
              </el-button><el-button
                v-if="auth.hasPermission('privacy.erasures.approve')"
                size="small"
                @click="erasureAction(scope.row, 'approve')"
              >
                批准
              </el-button><el-button
                v-if="auth.hasPermission('privacy.erasures.execute')"
                size="small"
                type="danger"
                @click="erasureAction(scope.row, 'execute')"
              >
                执行
              </el-button>
            </template>
            <el-button
              v-if="section === 'holds' && canReleaseHold && !scope.row.released_at"
              size="small"
              type="warning"
              @click="releaseHold(scope.row)"
            >
              释放留置
            </el-button>
            <template v-if="section === 'break-glass'">
              <el-button
                v-if="auth.hasPermission('privacy.break_glass.approve') && scope.row.status === 'requested'"
                size="small"
                @click="breakGlassAction(scope.row, 'approve')"
              >
                独立批准
              </el-button><el-button
                v-if="auth.hasPermission('privacy.break_glass.use') && scope.row.status === 'approved'"
                size="small"
                type="danger"
                @click="breakGlassAction(scope.row, 'use')"
              >
                使用授权
              </el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="holdDialog.open"
      title="创建法律与调查留置"
      width="620px"
    >
      <p class="boundary-note">
        留置会阻断该用户在所选模块上的删除权利，因此必须有授权人、明确范围和结束时间。
      </p>
      <el-form label-position="top">
        <el-form-item label="留置类型">
          <el-select v-model="holdDialog.hold_type">
            <el-option
              v-for="option in HOLD_TYPES"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="留置对象用户编号">
          <el-input v-model="holdDialog.subject_user_id" />
        </el-form-item>
        <el-form-item label="受留置模块（多个用逗号分隔，1–20 个）">
          <el-input
            v-model="holdDialog.module_codes"
            placeholder="commerce, counseling"
          />
        </el-form-item>
        <el-form-item label="授权人用户编号">
          <el-input v-model="holdDialog.authorized_by" />
        </el-form-item>
        <el-form-item label="结束时间">
          <el-input
            v-model="holdDialog.ends_at"
            type="datetime-local"
          />
        </el-form-item>
        <el-form-item label="留置理由（至少 12 个字符）">
          <el-input
            v-model="holdDialog.reason"
            type="textarea"
            :rows="3"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="holdDialog.open = false">
          取消
        </el-button>
        <el-button
          type="primary"
          :loading="busy"
          @click="createHold"
        >
          创建留置
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="breakGlassDialog.open"
      title="申请紧急访问"
      width="620px"
    >
      <p class="boundary-note">
        紧急访问需要另一位管理员独立批准，授权是短时的，且使用时逐个数据资产写入敏感访问审计。
      </p>
      <el-form label-position="top">
        <el-form-item label="被访问用户编号">
          <el-input v-model="breakGlassDialog.subject_user_id" />
        </el-form-item>
        <el-form-item label="数据范围（资产代码，多个用逗号分隔，1–20 个）">
          <el-input
            v-model="breakGlassDialog.data_scope"
            placeholder="counseling_notes, payment_attempts"
          />
        </el-form-item>
        <el-form-item label="访问目的">
          <el-select v-model="breakGlassDialog.purpose">
            <el-option
              v-for="option in BREAK_GLASS_PURPOSES"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="申请理由（至少 12 个字符）">
          <el-input
            v-model="breakGlassDialog.reason"
            type="textarea"
            :rows="3"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="breakGlassDialog.open = false">
          取消
        </el-button>
        <el-button
          type="primary"
          :loading="busy"
          @click="requestBreakGlass"
        >
          提交申请
        </el-button>
      </template>
    </el-dialog>

    <p>基线策略已有限期，但司法辖区法律文本、正式保留期限和生产审批仍是外部门禁，当前不作认证声明。</p>
  </section>
</template>

<style scoped>
.operation-inputs { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1rem; margin: 1rem 0; }
.operation-inputs label { display: grid; gap: .4rem; }
.operation-inputs span { color: var(--el-text-color-secondary); font-size: .85rem; }
.section-actions { display: flex; gap: .75rem; flex-wrap: wrap; margin-bottom: .75rem; }
.boundary-note { color: var(--el-text-color-secondary); margin: 0 0 .75rem; }
.metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 1rem; }
.metric-grid :deep(.el-card__body) { display: grid; gap: .4rem; }
.metric-grid strong { font-size: 1.8rem; }
</style>
