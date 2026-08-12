<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { AdminDataTable } from "@vav/ui-admin";
import { VAlert, VButton, VFormField, VModal, VPageState, VStatusBadge } from "@vav/ui-core";

import {
  processApi,
  type ProcessInstanceDetail,
  type ProcessRow
} from "@/features/process-governance/api";
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

const canResolveIntervention = computed(() => auth.hasPermission("process.interventions.execute"));
const canReadInstance = computed(() => auth.hasPermission("process.instances.read"));
const canCancel = computed(() => auth.hasPermission("process.instances.cancel"));
const canCompensate = computed(() => auth.hasPermission("process.compensations.execute"));
const canCertify = computed(() => auth.hasPermission("process.certifications.certify"));
const canSimulate = computed(() => auth.hasPermission("process.simulations.run"));

/** Sections whose rows carry a per-row action, so the table shows the column. */
const actionableSections = ["instances", "sagas", "timeouts", "stuck", "interventions", "certifications", "release"];
const showRowActions = computed(() => actionableSections.includes(section.value));

const interventionModal = ref<{ open: boolean; task?: ProcessRow; command: string; note: string }>({
  open: false,
  command: "",
  note: ""
});
const instanceModal = ref<{ open: boolean; detail?: ProcessInstanceDetail }>({ open: false });
const cancelModal = ref({ open: false, request_type: "admin_technical", reason_code: "" });
const compensationModal = ref({ open: false, step_execution_id: "", compensation_code: "" });
const certificationModal = ref<{ open: boolean; row?: ProcessRow; decision: "certified" | "rejected"; reason: string }>({
  open: false,
  decision: "certified",
  reason: ""
});
const simulationModal = ref({ open: false, scenario_code: "", synthetic_seed: 1 });

const CANCEL_REQUEST_TYPES = [
  { value: "admin_technical", label: "管理员技术性取消" },
  { value: "user", label: "用户请求" },
  { value: "system", label: "系统触发" },
  { value: "safety", label: "安全冻结" },
  { value: "provider", label: "外部供应商" }
];

function allowedCommands(task?: ProcessRow) {
  const commands = task?.allowed_resolution_commands;
  return Array.isArray(commands) ? commands.map(String) : [];
}

async function load() {
  busy.value = true;
  error.value = "";
  try {
    if (section.value === "dashboard") {
      dashboard.value = await processApi.dashboard();
      rows.value = [];
    } else {
      rows.value = await processApi.list(section.value);
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "流程治理数据加载失败";
  } finally {
    busy.value = false;
  }
}

async function verifyMachines() {
  busy.value = true;
  try {
    const result = await processApi.verifyMachines();
    notice.value = `状态机验证：${result.status.toUpperCase()}，共 ${result.results.length} 个。`;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "验证失败";
  } finally {
    busy.value = false;
  }
}

async function scanStuck() {
  busy.value = true;
  try {
    const result = await processApi.scanStuck();
    notice.value = `已创建 ${result.created} 个新卡死流程干预任务。`;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "扫描失败";
  } finally {
    busy.value = false;
  }
}

function openRow(row: ProcessRow) {
  error.value = "";
  notice.value = "";
  if (section.value === "interventions") {
    interventionModal.value = {
      open: true,
      task: row,
      command: allowedCommands(row)[0] ?? "",
      note: ""
    };
    return;
  }
  if (["certifications", "release"].includes(section.value)) {
    certificationModal.value = { open: true, row, decision: "certified", reason: "" };
    return;
  }
  void openInstance(row);
}

async function openInstance(row: ProcessRow) {
  const instanceId = String(row.id ?? "");
  if (!instanceId || !canReadInstance.value) return;
  busy.value = true;
  try {
    instanceModal.value = { open: true, detail: await processApi.instance(instanceId) };
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "流程实例详情加载失败";
  } finally {
    busy.value = false;
  }
}

async function refreshInstance() {
  const instanceId = String(instanceModal.value.detail?.instance.id ?? "");
  if (!instanceId) return;
  instanceModal.value.detail = await processApi.instance(instanceId);
}

async function resolveIntervention() {
  const { task, command, note } = interventionModal.value;
  if (!task?.id) return;
  if (!command) {
    error.value = "请选择一个已登记的处置命令；控制面不接受未登记的临时修复。";
    return;
  }
  if (note.trim().length < 10) {
    error.value = "请填写至少 10 个字符的处置回执，回执会写入干预任务记录。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await processApi.resolveIntervention(String(task.id), command, note.trim());
    notice.value = "人工干预任务已处置。";
    interventionModal.value = { open: false, command: "", note: "" };
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "干预处置失败";
  } finally {
    busy.value = false;
  }
}

async function cancelInstance() {
  const instance = instanceModal.value.detail?.instance;
  if (!instance?.id) return;
  if (cancelModal.value.reason_code.trim().length < 2) {
    error.value = "请填写取消原因码。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await processApi.cancelInstance(String(instance.id), {
      request_type: cancelModal.value.request_type,
      reason_code: cancelModal.value.reason_code.trim(),
      // Optimistic lock: the backend rejects the request if the instance moved
      // on since this detail view was loaded.
      expected_lock_version: Number(instance.lock_version ?? 0)
    });
    notice.value = "取消请求已受理。";
    cancelModal.value = { open: false, request_type: "admin_technical", reason_code: "" };
    await refreshInstance();
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "取消失败";
  } finally {
    busy.value = false;
  }
}

async function requestCompensation() {
  const instance = instanceModal.value.detail?.instance;
  if (!instance?.id) return;
  const { step_execution_id, compensation_code } = compensationModal.value;
  if (!step_execution_id || compensation_code.trim().length < 3) {
    error.value = "请选择要补偿的步骤并填写补偿命令码。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await processApi.requestCompensation(String(instance.id), step_execution_id, compensation_code.trim());
    notice.value = "补偿已登记，由领域模块执行并回执。";
    compensationModal.value = { open: false, step_execution_id: "", compensation_code: "" };
    await refreshInstance();
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "补偿登记失败";
  } finally {
    busy.value = false;
  }
}

async function decideCertification() {
  const { row, decision, reason } = certificationModal.value;
  if (!row?.id) return;
  if (reason.trim().length < 10) {
    error.value = "请填写至少 10 个字符的认证结论理由。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await processApi.decideCertification(String(row.id), decision, reason.trim());
    notice.value = decision === "certified" ? "业务域已认证。" : "业务域认证已驳回。";
    certificationModal.value = { open: false, decision: "certified", reason: "" };
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "认证决定失败";
  } finally {
    busy.value = false;
  }
}

async function runSimulation() {
  if (simulationModal.value.scenario_code.trim().length < 3) {
    error.value = "请填写要运行的场景码。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await processApi.runSimulation(
      simulationModal.value.scenario_code.trim(),
      Number(simulationModal.value.synthetic_seed) || 1
    );
    notice.value = "模拟已运行，结果写入模拟记录。";
    simulationModal.value = { open: false, scenario_code: "", synthetic_seed: 1 };
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "模拟运行失败";
  } finally {
    busy.value = false;
  }
}

onMounted(load);
watch(section, load);
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
      title="操作失败"
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
        </VButton><VButton
          v-if="section === 'simulations' && canSimulate"
          :disabled="busy"
          @click="simulationModal.open = true"
        >
          运行模拟场景
        </VButton>
      </div>
      <p
        v-if="showRowActions"
        class="hint"
      >
        流程实例可查看步骤与补偿并执行取消，人工干预任务可提交处置回执，业务认证可作出最终决定。
      </p>
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
      >
        <template
          v-if="showRowActions"
          #actions="{ row }"
        >
          <VButton
            v-if="section === 'interventions' && canResolveIntervention && ['open', 'assigned'].includes(String(row.status))"
            variant="secondary"
            @click="openRow(row)"
          >
            处置
          </VButton>
          <VButton
            v-else-if="['certifications', 'release'].includes(section) && canCertify"
            variant="secondary"
            @click="openRow(row)"
          >
            认证决定
          </VButton>
          <VButton
            v-else-if="canReadInstance && ['instances', 'sagas', 'timeouts'].includes(section)"
            variant="secondary"
            @click="openRow(row)"
          >
            诊断
          </VButton>
        </template>
      </AdminDataTable>
    </div>

    <VModal
      :open="interventionModal.open"
      title="处置人工干预任务"
      @close="interventionModal.open = false"
      @confirm="resolveIntervention"
    >
      <p class="hint">
        只能执行该任务已登记的处置命令；控制面拒绝未登记的临时修复，以免绕过领域模块的权威状态。
      </p>
      <VFormField
        label="处置命令"
        required
      >
        <select v-model="interventionModal.command">
          <option
            v-for="command in allowedCommands(interventionModal.task)"
            :key="command"
            :value="command"
          >
            {{ command }}
          </option>
        </select>
      </VFormField>
      <VFormField
        label="处置回执"
        hint="至少 10 个字符，写明实际执行的动作与验证结果。"
        required
      >
        <textarea
          v-model="interventionModal.note"
          rows="3"
        />
      </VFormField>
      <template #confirm>
        提交处置
      </template>
    </VModal>

    <VModal
      :open="instanceModal.open"
      title="流程实例诊断"
      @close="instanceModal.open = false"
      @confirm="instanceModal.open = false"
    >
      <template v-if="instanceModal.detail">
        <dl class="instance-summary">
          <div><dt>流程编号</dt><dd>{{ instanceModal.detail.instance.process_number }}</dd></div>
          <div><dt>状态</dt><dd>{{ instanceModal.detail.instance.status }}</dd></div>
          <div><dt>当前步骤</dt><dd>{{ instanceModal.detail.instance.current_step_code ?? "-" }}</dd></div>
          <div><dt>等待对象</dt><dd>{{ instanceModal.detail.instance.waiting_for ?? "-" }}</dd></div>
          <div><dt>失败码</dt><dd>{{ instanceModal.detail.instance.failure_code ?? "-" }}</dd></div>
          <div><dt>锁版本</dt><dd>{{ instanceModal.detail.instance.lock_version }}</dd></div>
        </dl>

        <h3>步骤执行</h3>
        <AdminDataTable
          caption="步骤执行记录"
          :columns="[{ key: 'execution_number', label: '序号', priority: 'primary' }, { key: 'status', label: '状态' }, { key: 'attempt_count', label: '尝试次数' }, { key: 'error_detail', label: '错误' }]"
          :rows="instanceModal.detail.steps"
          row-key="id"
        />

        <h3>补偿执行</h3>
        <AdminDataTable
          caption="补偿执行记录"
          :columns="[{ key: 'compensation_code', label: '补偿命令', priority: 'primary' }, { key: 'status', label: '状态' }]"
          :rows="instanceModal.detail.compensations"
          row-key="id"
        />

        <div class="actions">
          <VButton
            v-if="canCompensate"
            variant="secondary"
            @click="compensationModal.open = true"
          >
            发起补偿
          </VButton>
          <VButton
            v-if="canCancel"
            variant="danger"
            @click="cancelModal.open = true"
          >
            取消该流程
          </VButton>
        </div>
      </template>
      <template #confirm>
        关闭
      </template>
    </VModal>

    <VModal
      :open="cancelModal.open"
      title="取消流程实例"
      dangerous
      @close="cancelModal.open = false"
      @confirm="cancelInstance"
    >
      <p class="hint">
        取消按乐观锁执行：若该实例在你打开面板后已经推进，请求会被拒绝，请刷新后重试。
      </p>
      <VFormField
        label="取消类型"
        required
      >
        <select v-model="cancelModal.request_type">
          <option
            v-for="option in CANCEL_REQUEST_TYPES"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </option>
        </select>
      </VFormField>
      <VFormField
        label="原因码"
        hint="例如 provider_outage、duplicate_order。"
        required
      >
        <input v-model="cancelModal.reason_code">
      </VFormField>
      <template #confirm>
        确认取消
      </template>
    </VModal>

    <VModal
      :open="compensationModal.open"
      title="发起补偿"
      @close="compensationModal.open = false"
      @confirm="requestCompensation"
    >
      <VFormField
        label="要补偿的步骤"
        required
      >
        <select v-model="compensationModal.step_execution_id">
          <option
            v-for="step in instanceModal.detail?.steps ?? []"
            :key="String(step.id)"
            :value="String(step.id)"
          >
            #{{ step.execution_number }} · {{ step.status }}
          </option>
        </select>
      </VFormField>
      <VFormField
        label="补偿命令码"
        hint="必须是领域模块已登记的补偿命令。"
        required
      >
        <input v-model="compensationModal.compensation_code">
      </VFormField>
      <template #confirm>
        登记补偿
      </template>
    </VModal>

    <VModal
      :open="certificationModal.open"
      title="业务域认证决定"
      @close="certificationModal.open = false"
      @confirm="decideCertification"
    >
      <p class="hint">
        认证证据由流水线评估生成；此处只作出人工的最终认证或驳回决定。
      </p>
      <VFormField
        label="决定"
        required
      >
        <select v-model="certificationModal.decision">
          <option value="certified">
            通过认证
          </option>
          <option value="rejected">
            驳回
          </option>
        </select>
      </VFormField>
      <VFormField
        label="理由"
        hint="至少 10 个字符，会写入认证记录。"
        required
      >
        <textarea
          v-model="certificationModal.reason"
          rows="3"
        />
      </VFormField>
      <template #confirm>
        提交决定
      </template>
    </VModal>

    <VModal
      :open="simulationModal.open"
      title="运行流程模拟"
      @close="simulationModal.open = false"
      @confirm="runSimulation"
    >
      <VFormField
        label="场景码"
        hint="来自 config/process/simulations.yaml 的已登记场景。"
        required
      >
        <input v-model="simulationModal.scenario_code">
      </VFormField>
      <VFormField
        label="合成数据种子"
        hint="固定种子保证模拟可复现。"
      >
        <input
          v-model.number="simulationModal.synthetic_seed"
          type="number"
          min="1"
        >
      </VFormField>
      <template #confirm>
        运行
      </template>
    </VModal>
  </section>
</template>

<style scoped>.process-console{display:grid;gap:var(--vav-density-page-gap)}header{display:flex;justify-content:space-between;align-items:end;gap:var(--vav-space-6)}header p{max-width:var(--vav-layout-content-reading)}.eyebrow{color:var(--vav-color-action-primary);font-weight:700;letter-spacing:.1em}nav{display:flex;flex-wrap:wrap;gap:var(--vav-space-2)}nav a{padding:var(--vav-space-2) var(--vav-space-3);border-radius:var(--vav-radius-pill);background:var(--vav-color-surface-soft);color:var(--vav-color-text);text-decoration:none}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:var(--vav-space-4)}.metrics article,.table-panel{padding:var(--vav-component-card-padding);border:1px solid var(--vav-color-border);border-radius:var(--vav-component-card-radius);background:var(--vav-color-surface-raised)}.metrics article{display:grid;gap:var(--vav-space-2)}.metrics strong{font-size:var(--vav-font-size-xl)}.actions{display:flex;justify-content:flex-end;gap:var(--vav-space-2);margin-bottom:var(--vav-space-3)}.hint{color:var(--vav-color-text-muted);margin:0 0 var(--vav-space-3)}.instance-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--vav-space-3)}.instance-summary dt{color:var(--vav-color-text-muted);font-size:var(--vav-font-size-sm)}.instance-summary dd{margin:0;overflow-wrap:anywhere}h3{margin-top:var(--vav-space-5)}@media(max-width:48rem){header{align-items:start;flex-direction:column}.instance-summary{grid-template-columns:1fr}}</style>
