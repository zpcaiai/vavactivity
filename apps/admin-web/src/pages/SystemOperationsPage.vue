<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { localizeAdminLabel, localizeAdminValue } from "@vav/ui-admin";

import { VFormField, VModal } from "@vav/ui-core";

import { systemAdminApi, type SystemAdminRow } from "@/features/system/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute();
const auth = useAdminAuthStore();
const section = computed(() => String(route.meta.systemSection ?? "status"));
const rows = ref<SystemAdminRow[]>([]);
const summary = ref<SystemAdminRow | null>(null);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const newFlagCode = ref("");

/**
 * Every operational write the backend accepts takes a reason_code, and it is
 * the only thing that ends up in the audit trail — so it has to come from the
 * operator, not from a constant. Maintenance mode used to send a fixed
 * "operator_confirmed_change" for every enable and disable.
 */
const reasonDialog = ref<{
  open: boolean;
  title: string;
  intent: string;
  reason_code: string;
  public_message: string;
  needsMessage: boolean;
  run?: (reasonCode: string, publicMessage: string) => Promise<void>;
}>({ open: false, title: "", intent: "", reason_code: "", public_message: "", needsMessage: false });

const canApproveRelease = computed(() => auth.hasPermission("system.releases.approve"));
const canRollbackRelease = computed(() => auth.hasPermission("system.releases.rollback"));
const canRetryJob = computed(() => auth.hasPermission("system.jobs.retry"));
const canCancelJob = computed(() => auth.hasPermission("system.jobs.cancel"));
const canReplayDeadLetter = computed(() => auth.hasPermission("system.dead_letters.replay"));

const actionSections = ["feature-flags", "releases", "jobs", "dead-letters"];
const showActionColumn = computed(() => actionSections.includes(section.value));

function askReason(
  title: string,
  intent: string,
  run: (reasonCode: string, publicMessage: string) => Promise<void>,
  needsMessage = false
) {
  error.value = "";
  notice.value = "";
  reasonDialog.value = { open: true, title, intent, reason_code: "", public_message: "", needsMessage, run };
}

async function confirmReason() {
  const { reason_code, public_message, run, title } = reasonDialog.value;
  if (!run) return;
  if (reason_code.trim().length < 3) {
    error.value = "请填写原因代码，它是这次操作在审计里的唯一说明。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await run(reason_code.trim(), public_message.trim());
    notice.value = `${title}已完成并追加审计。`;
    reasonDialog.value = { open: false, title: "", intent: "", reason_code: "", public_message: "", needsMessage: false };
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : `${title}失败`;
  } finally {
    busy.value = false;
  }
}

function approveRelease(row: SystemAdminRow) {
  if (!window.confirm("确认批准该发布？批准人必须与提交人不同。")) return;
  void (async () => {
    busy.value = true;
    error.value = "";
    try {
      await systemAdminApi.approveRelease(String(row.id));
      notice.value = "发布已批准并追加审计。";
      await load();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "发布批准失败";
    } finally {
      busy.value = false;
    }
  })();
}

function rollbackRelease(row: SystemAdminRow) {
  askReason(
    "发布回滚",
    "回滚会把线上切回上一个已部署版本，请写明触发回滚的故障代码或工单号。",
    async (reasonCode) => {
      await systemAdminApi.rollbackRelease(String(row.id), reasonCode);
    }
  );
}

function operateJob(row: SystemAdminRow, operation: "retry" | "cancel") {
  askReason(
    operation === "retry" ? "任务重试" : "任务取消",
    operation === "retry"
      ? "重试会从上次游标继续，不会重复已完成的记录。"
      : "取消后该任务不再推进，已处理的数据保持原样。",
    async (reasonCode) => {
      await systemAdminApi.operateJob(String(row.id), operation, reasonCode);
    }
  );
}

function replayDeadLetter(row: SystemAdminRow) {
  askReason("死信重放", "重放是幂等的：已经成功处理过的效果不会重复产生。", async (reasonCode) => {
    await systemAdminApi.replayDeadLetter(String(row.id), reasonCode);
  });
}
const sections = [
  ["status", "运行状态", "system.status.read"],
  ["releases", "发布记录", "system.releases.read"],
  ["jobs", "迁移与回填", "system.jobs.read"],
  ["integrations", "集成状态", "system.status.read"],
  ["dead-letters", "死信队列", "system.dead_letters.read"],
  ["feature-flags", "功能开关", "system.feature_flags.read"],
  ["maintenance", "维护模式", "system.maintenance.read"],
  ["backups", "备份", "system.backups.read"],
  ["restore-drills", "恢复演练", "system.restore_drills.read"],
  ["capacity", "容量基线", "system.capacity.read"]
] as const;
const visible = computed(() => sections.filter((item) => auth.hasPermission(item[2])));
const columns = computed(() => {
  const keys = new Set<string>();
  for (const row of rows.value.slice(0, 20)) {
    Object.keys(row).forEach((key) => {
      if (!/(secret|token|password|credential|evidence_manifest)/iu.test(key)) keys.add(key);
    });
  }
  return [...keys].slice(0, 8);
});

function display(value: unknown, field = "") {
  return localizeAdminValue(value, field);
}

async function load() {
  busy.value = true;
  error.value = "";
  rows.value = [];
  summary.value = null;
  try {
    await auth.bootstrap();
    const payload = await systemAdminApi.view(section.value);
    if (Array.isArray(payload)) rows.value = payload;
    else summary.value = payload;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "系统运维视图加载失败";
  } finally {
    busy.value = false;
  }
}

async function createFlag() {
  const code = newFlagCode.value.trim();
  if (!code) return;
  await systemAdminApi.createFlag({
    flag_code: code,
    default_value: { enabled: false },
    targeting_policy: {},
    description: "由系统运维中心创建；启用前需要另一位管理员审批。"
  });
  newFlagCode.value = "";
  notice.value = "草稿已创建；创建人不能自我审批。";
  await load();
}

async function flagAction(row: SystemAdminRow) {
  const id = String(row.id);
  if (row.status === "draft") await systemAdminApi.approveFlag(id);
  else if (row.status === "approved") await systemAdminApi.activateFlag(id);
  notice.value = "状态已更新并追加审计记录。";
  await load();
}

function maintenance(enabled: boolean) {
  askReason(
    enabled ? "启用维护模式" : "停用维护模式",
    enabled
      ? "启用后写入将被关闭，用户会看到你填写的公告文案。生产环境仍要求独立审批人。"
      : "停用会恢复写入可用性，请写明故障已确认解除的依据。",
    async (reasonCode, publicMessage) => {
      await systemAdminApi.changeMaintenance(enabled, {
        reason_code: reasonCode,
        public_message: enabled ? publicMessage || "系统正在维护，请稍后重试。" : null,
        write_scope: enabled ? { all: false } : {}
      });
    },
    enabled
  );
}

watch(() => route.fullPath, load);
onMounted(load);
</script>

<template>
  <section class="system-operations">
    <header>
      <div>
        <p class="eyebrow">
          第 19 批 · 生产运维
        </p><h1>系统运维中心</h1>
      </div>
      <p>仅展示脱敏运行信息。发布使用不可变镜像摘要；生产维护、功能开关激活和恢复操作都保留独立审批与审计边界。</p>
    </header>
    <nav>
      <RouterLink
        v-for="item in visible"
        :key="item[0]"
        :to="`/admin/system/${item[0]}`"
      >
        {{ item[1] }}
      </RouterLink>
    </nav>
    <p
      v-if="busy"
      role="status"
    >
      正在读取运行控制面…
    </p>
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

    <article
      v-if="section === 'status' && summary"
      class="panel summary"
    >
      <div
        v-for="(value, key) in summary"
        :key="key"
      >
        <strong>{{ localizeAdminLabel(key) }}</strong><span>{{ display(value, key) }}</span>
      </div>
    </article>
    <article
      v-if="section === 'feature-flags'"
      class="panel controls"
    >
      <h2>创建受控功能开关</h2>
      <input
        v-model="newFlagCode"
        aria-label="功能开关代码"
        placeholder="experience.new_onboarding"
      >
      <button
        :disabled="!auth.hasPermission('system.feature_flags.manage')"
        @click="createFlag"
      >
        创建禁用草稿
      </button>
      <p>启用前需要另一位管理员审批；创建人不能自我审批。</p>
      <p>安全、隐私、支付、授权及加密强制控制不能被功能开关绕过。</p>
    </article>
    <article
      v-if="section === 'maintenance'"
      class="panel controls"
    >
      <h2>维护模式</h2>
      <button
        :disabled="!auth.hasPermission('system.maintenance.enable')"
        @click="maintenance(true)"
      >
        启用维护模式
      </button>
      <button
        :disabled="!auth.hasPermission('system.maintenance.disable')"
        @click="maintenance(false)"
      >
        停用维护模式
      </button>
    </article>
    <p
      v-if="['backups', 'restore-drills', 'capacity'].includes(section)"
      class="boundary-note"
    >
      备份、恢复演练与容量基线是流水线回执：登记它们需要校验和清单与验证证据，由执行方写入，控制台不提供手填入口。
    </p>
    <p
      v-if="section === 'releases'"
      class="boundary-note"
    >
      发布记录与部署回执由 CI 写入（镜像摘要、契约校验和、构件 SHA-256）。控制台负责的是批准与回滚这两个人工决定。
    </p>
    <article
      v-if="section !== 'status'"
      class="panel table-wrap"
    >
      <table>
        <thead>
          <tr>
            <th
              v-for="column in columns"
              :key="column"
            >
              {{ localizeAdminLabel(column) }}
            </th><th v-if="showActionColumn">
              受控操作
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="String(row.id ?? JSON.stringify(row))"
          >
            <td
              v-for="column in columns"
              :key="column"
            >
              {{ display(row[column], column) }}
            </td>
            <td v-if="showActionColumn">
              <template v-if="section === 'feature-flags'">
                <button
                  v-if="row.status === 'draft'"
                  :disabled="!auth.hasPermission('system.feature_flags.approve')"
                  @click="flagAction(row)"
                >
                  独立审批
                </button>
                <button
                  v-else-if="row.status === 'approved'"
                  :disabled="!auth.hasPermission('system.feature_flags.manage')"
                  @click="flagAction(row)"
                >
                  激活
                </button>
                <span v-else>只读</span>
              </template>
              <template v-else-if="section === 'releases'">
                <button
                  v-if="canApproveRelease && row.status === 'pending_approval'"
                  @click="approveRelease(row)"
                >
                  批准发布
                </button>
                <button
                  v-if="canRollbackRelease && ['deployed', 'active'].includes(String(row.status))"
                  @click="rollbackRelease(row)"
                >
                  回滚
                </button>
                <span v-if="!canApproveRelease && !canRollbackRelease">只读</span>
              </template>
              <template v-else-if="section === 'jobs'">
                <button
                  v-if="canRetryJob && ['failed', 'paused'].includes(String(row.status))"
                  @click="operateJob(row, 'retry')"
                >
                  重试
                </button>
                <button
                  v-if="canCancelJob && ['running', 'paused', 'failed'].includes(String(row.status))"
                  @click="operateJob(row, 'cancel')"
                >
                  取消
                </button>
                <span v-if="!canRetryJob && !canCancelJob">只读</span>
              </template>
              <template v-else-if="section === 'dead-letters'">
                <button
                  v-if="canReplayDeadLetter && row.status !== 'replayed'"
                  @click="replayDeadLetter(row)"
                >
                  重放
                </button>
                <span v-else>只读</span>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="!rows.length && !busy">
        暂无记录。
      </p>
    </article>

    <VModal
      :open="reasonDialog.open"
      title="确认运维操作"
      dangerous
      @close="reasonDialog.open = false"
      @confirm="confirmReason"
    >
      <p class="boundary-note">
        {{ reasonDialog.intent }}
      </p>
      <VFormField
        label="原因代码"
        hint="例如 incident-2431、provider_outage。它是这次操作在审计里的唯一说明。"
        required
      >
        <input v-model="reasonDialog.reason_code">
      </VFormField>
      <VFormField
        v-if="reasonDialog.needsMessage"
        label="对外公告文案"
        hint="维护期间展示给用户，留空则使用默认文案。"
      >
        <textarea
          v-model="reasonDialog.public_message"
          rows="2"
        />
      </VFormField>
      <template #confirm>
        {{ reasonDialog.title }}
      </template>
    </VModal>
</section>
</template>

<style scoped>
.system-operations{display:grid;gap:1rem}header{display:flex;justify-content:space-between;gap:2rem;align-items:end}header>p{max-width:680px}.eyebrow{letter-spacing:.12em;color:var(--vav-color-focus)}nav{display:flex;gap:.55rem;flex-wrap:wrap}nav a{padding:.5rem .8rem;border-radius:999px;background:var(--vav-color-surface-info);color:var(--vav-color-text);text-decoration:none}.panel{padding:1rem;border:1px solid var(--vav-color-border);border-radius:12px;background:var(--vav-color-surface-raised)}.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem}.summary div{display:grid;gap:.4rem}.summary span{overflow-wrap:anywhere}.controls{display:flex;gap:.8rem;align-items:center;flex-wrap:wrap}.controls h2,.controls p{flex-basis:100%;margin:.2rem 0}.controls input{min-width:260px;padding:.65rem}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:.7rem;border-bottom:1px solid var(--vav-color-surface-soft);max-width:260px;overflow-wrap:anywhere}button{padding:.6rem .85rem;border:0;border-radius:999px;background:var(--vav-color-focus);color:white}button:disabled{opacity:.45}.alert{padding:.8rem}.error{background:var(--vav-color-surface-danger)}.notice{background:var(--vav-color-surface-success)}.table-wrap{overflow:auto}.boundary-note{color:var(--vav-color-text-muted);margin:0}td button{margin-right:.4rem;margin-bottom:.3rem}input,textarea{padding:.6rem;border:1px solid var(--vav-color-border-strong);border-radius:8px}@media(max-width:700px){header{align-items:start;flex-direction:column}}
</style>
