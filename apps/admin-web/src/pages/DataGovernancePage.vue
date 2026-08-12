<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { AdminDataTable } from "@vav/ui-admin";
import { VAlert, VButton, VFormField, VModal, VPageState, VStatusBadge } from "@vav/ui-core";
import {
  dataGovernanceApi,
  type BackfillAction,
  type DataGovernanceRow
} from "@/features/data-governance/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute(); const auth = useAdminAuthStore();
const section = computed(() => String(route.meta.dataGovernanceSection ?? "dashboard"));
const rows = ref<DataGovernanceRow[]>([]); const dashboard = ref<DataGovernanceRow>({}); const busy = ref(false); const error = ref(""); const notice = ref("");
const sections = [
  ["dashboard", "概览", "data.dashboard.read"], ["assets", "数据资产", "data.assets.read"], ["contracts", "数据契约", "data.contracts.read"], ["lineage", "数据血缘", "data.lineage.read"], ["events", "事件", "data.events.read"], ["event-gaps", "事件缺口", "data.events.read"], ["dead-letters", "死信", "data.dead_letters.read"], ["quality", "数据质量", "data.quality.read"], ["reconciliations", "对账", "data.reconciliations.read"], ["differences", "差异", "data.reconciliations.read"], ["backfills", "Backfill", "data.backfills.read"], ["repairs", "修复", "data.repairs.read"], ["projections", "投影重建", "data.projections.read"], ["erasures", "删除传播", "data.erasures.read"], ["certifications", "完整性认证", "data.certifications.read"], ["release", "发布", "data.release.read"]
] as const;
const visibleSections = computed(() => sections.filter((item) => auth.hasPermission(item[2])));
const tableRows = computed(() => rows.value.map((row) => ({ ...row, identifier: row.asset_code ?? row.contract_code ?? row.gap_code ?? row.reconciliation_code ?? row.backfill_code ?? row.repair_code ?? row.event_type ?? row.business_domain ?? row.id ?? "-", kind: row.asset_type ?? row.contract_type ?? row.dimension ?? row.category ?? "-", record_state: row.status ?? row.lifecycle_status ?? row.technical_status ?? "-" })));

const canManageBackfills = computed(() => auth.hasPermission("data.backfills.manage"));
const canRebuildProjection = computed(() => auth.hasPermission("data.projections.rebuild"));
const canRepair = computed(() => auth.hasPermission("data.repairs.execute"));
const canPlanErasure = computed(() => auth.hasPermission("data.erasures.plan"));
const canCertifyErasure = computed(() => auth.hasPermission("data.erasures.certify"));
const canCertifyIntegrity = computed(() => auth.hasPermission("data.certifications.certify"));
const canManageAssets = computed(() => auth.hasPermission("data.assets.manage"));

/** Backfill transitions the operator may drive, keyed by the run's own status. */
const BACKFILL_ACTIONS: Record<string, Array<{ action: BackfillAction; label: string }>> = {
  planned: [{ action: "approve", label: "批准" }, { action: "cancel", label: "取消" }],
  approved: [{ action: "start", label: "启动" }, { action: "cancel", label: "取消" }],
  running: [{ action: "pause", label: "暂停" }, { action: "complete", label: "标记完成" }, { action: "fail", label: "标记失败" }],
  paused: [{ action: "resume", label: "继续" }, { action: "cancel", label: "取消" }]
};

function backfillActions(row: DataGovernanceRow) {
  return canManageBackfills.value && section.value === "backfills"
    ? BACKFILL_ACTIONS[String(row.status ?? "")] ?? []
    : [];
}

const rowActionSections = ["backfills", "differences", "repairs", "erasures", "certifications", "release"];
const showRowActions = computed(() => rowActionSections.includes(section.value));

const projectionModal = ref({ open: false, asset_code: "", scope: "entity" as "entity" | "partition" | "full", scope_key: "", source_checkpoint: "{}", shadow_build: true });
const repairModal = ref({ open: false, repair_code: "", difference_id: "", input_mapping: "{}" });
const erasureModal = ref({ open: false, privacy_request_id: "", subject_user_id: "", lineage_release_version: "" });
const identifierModal = ref({ open: false, entity_type: "", canonical_entity_id: "", provider_code: "", external_identifier: "" });
const certificationModal = ref<{ open: boolean; row?: DataGovernanceRow; decision: "certified" | "rejected"; reason: string }>({ open: false, decision: "certified", reason: "" });

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
  busy.value = true; error.value = "";
  try {
    if (section.value === "dashboard") { dashboard.value = await dataGovernanceApi.dashboard(); rows.value = []; }
    else rows.value = await dataGovernanceApi.list(section.value);
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "数据治理加载失败"; }
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

async function actOnBackfill(row: DataGovernanceRow, action: BackfillAction, label: string) {
  await run(`Backfill ${label}`, () => dataGovernanceApi.actOnBackfill(String(row.id), action));
}

async function rebuildProjection() {
  const checkpoint = parseJson(projectionModal.value.source_checkpoint, "来源检查点");
  if (!checkpoint) return;
  if (projectionModal.value.asset_code.trim().length < 3) {
    error.value = "请填写要重建的资产编码。";
    return;
  }
  const ok = await run("投影重建", () => dataGovernanceApi.rebuildProjection({
    asset_code: projectionModal.value.asset_code.trim(),
    scope: projectionModal.value.scope,
    scope_key: projectionModal.value.scope_key.trim() || null,
    source_checkpoint: checkpoint,
    shadow_build: projectionModal.value.shadow_build
  }));
  if (ok) projectionModal.value.open = false;
}

function openRepair(row?: DataGovernanceRow) {
  error.value = "";
  repairModal.value = {
    open: true,
    repair_code: String(row?.repair_code ?? ""),
    // A repair raised from a reconciliation difference stays linked to it, so
    // the fix is auditable against the discrepancy that justified it.
    difference_id: section.value === "differences" ? String(row?.id ?? "") : "",
    input_mapping: "{}"
  };
}

async function requestRepair() {
  const mapping = parseJson(repairModal.value.input_mapping, "输入映射");
  if (!mapping) return;
  if (repairModal.value.repair_code.trim().length < 3) {
    error.value = "请填写已登记的修复命令码。";
    return;
  }
  const ok = await run("修复登记", () => dataGovernanceApi.requestRepair({
    repair_code: repairModal.value.repair_code.trim(),
    reconciliation_difference_id: repairModal.value.difference_id.trim() || null,
    input_mapping: mapping
  }));
  if (ok) repairModal.value.open = false;
}

async function createErasurePlan() {
  const form = erasureModal.value;
  if (!form.privacy_request_id.trim() || !form.subject_user_id.trim()) {
    error.value = "请填写隐私请求编号与主体用户编号。";
    return;
  }
  if (!form.lineage_release_version.trim()) {
    error.value = "请填写血缘发布版本；删除计划必须绑定一个已发布的血缘版本，才能保证覆盖到全部下游资产。";
    return;
  }
  const ok = await run("删除计划创建", () => dataGovernanceApi.createErasurePlan({
    privacy_request_id: form.privacy_request_id.trim(),
    subject_user_id: form.subject_user_id.trim(),
    lineage_release_version: form.lineage_release_version.trim()
  }));
  if (ok) form.open = false;
}

async function issueCertificate(row: DataGovernanceRow) {
  if (!window.confirm("确认为该删除计划签发证书？签发要求计划下所有删除任务已完成或已合法留置。")) return;
  await run("删除证书签发", () => dataGovernanceApi.issueErasureCertificate(String(row.id)));
}

async function registerIdentifier() {
  const form = identifierModal.value;
  if (!form.entity_type.trim() || !form.canonical_entity_id.trim() || !form.provider_code.trim() || !form.external_identifier.trim()) {
    error.value = "请完整填写实体类型、规范实体编号、提供方代码与外部标识。";
    return;
  }
  const ok = await run("外部标识登记", () => dataGovernanceApi.registerExternalIdentifier({
    entity_type: form.entity_type.trim(),
    canonical_entity_id: form.canonical_entity_id.trim(),
    provider_code: form.provider_code.trim(),
    external_identifier: form.external_identifier.trim()
  }));
  if (ok) form.open = false;
}

function openCertification(row: DataGovernanceRow) {
  error.value = "";
  certificationModal.value = { open: true, row, decision: "certified", reason: "" };
}

async function decideCertification() {
  const { row, decision, reason } = certificationModal.value;
  if (!row?.id) return;
  if (reason.trim().length < 10) {
    error.value = "请填写至少 10 个字符的认证结论理由。";
    return;
  }
  const ok = await run("完整性认证决定", () => dataGovernanceApi.decideCertification(String(row.id), decision, reason.trim()));
  if (ok) certificationModal.value = { open: false, decision: "certified", reason: "" };
}

onMounted(load); watch(section, load);
</script>

<template>
  <section class="data-console">
    <header>
      <div>
        <p class="eyebrow">
          BATCH 25 · DATA INTEGRITY
        </p><h1>数据治理与完整性中心</h1><p>权威数据由领域模块持有；本中心验证契约、血缘、事件、对账、Backfill 与删除传播，不直接改写业务事实。</p>
      </div><VStatusBadge
        status="warning"
        label="NOT CERTIFIED"
      />
    </header>
    <nav aria-label="数据治理分区">
      <RouterLink
        v-for="item in visibleSections"
        :key="item[0]"
        :to="`/admin/data-governance/${item[0]}`"
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
    </VAlert>
    <VAlert
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
      <article><strong>{{ dashboard.active_assets ?? 0 }}</strong><span>活跃资产</span></article><article><strong>{{ dashboard.active_contracts ?? 0 }}</strong><span>活跃契约</span></article><article><strong>{{ dashboard.open_event_gaps ?? 0 }}</strong><span>事件缺口</span></article><article><strong>{{ dashboard.open_dead_letters ?? 0 }}</strong><span>死信</span></article><article><strong>{{ dashboard.open_differences ?? 0 }}</strong><span>对账差异</span></article><article><strong>{{ dashboard.erasure_failures ?? 0 }}</strong><span>删除失败</span></article>
    </div>
    <div
      v-else
      class="table-panel"
    >
      <div class="actions">
        <VButton
          v-if="section === 'assets' && canManageAssets"
          variant="secondary"
          :disabled="busy"
          @click="identifierModal.open = true"
        >
          登记外部标识
        </VButton>
        <VButton
          v-if="section === 'projections' && canRebuildProjection"
          :disabled="busy"
          @click="projectionModal.open = true"
        >
          发起投影重建
        </VButton>
        <VButton
          v-if="section === 'repairs' && canRepair"
          :disabled="busy"
          @click="openRepair()"
        >
          发起修复
        </VButton>
        <VButton
          v-if="section === 'erasures' && canPlanErasure"
          :disabled="busy"
          @click="erasureModal.open = true"
        >
          创建删除计划
        </VButton>
      </div>
      <p
        v-if="section === 'erasures'"
        class="hint"
      >
        删除计划按血缘展开为逐资产任务。任务的逐条完成回执目前只能由执行方通过 API 回写——后端尚未提供任务列表端点，控制台无法枚举 task_id。
      </p>
      <VPageState
        v-if="busy && rows.length === 0"
        state="loading"
        title="正在读取数据完整性状态"
        message="请稍候。"
      /><AdminDataTable
        v-else
        caption="数据治理记录"
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
            v-for="item in backfillActions(row)"
            :key="item.action"
            variant="secondary"
            :disabled="busy"
            @click="actOnBackfill(row, item.action, item.label)"
          >
            {{ item.label }}
          </VButton>
          <VButton
            v-if="canRepair && ['differences', 'repairs'].includes(section)"
            variant="secondary"
            :disabled="busy"
            @click="openRepair(row)"
          >
            发起修复
          </VButton>
          <VButton
            v-if="section === 'erasures' && canCertifyErasure"
            variant="secondary"
            :disabled="busy"
            @click="issueCertificate(row)"
          >
            签发证书
          </VButton>
          <VButton
            v-if="['certifications', 'release'].includes(section) && canCertifyIntegrity"
            variant="secondary"
            :disabled="busy"
            @click="openCertification(row)"
          >
            认证决定
          </VButton>
        </template>
      </AdminDataTable>
    </div>

    <VModal
      :open="projectionModal.open"
      title="发起投影重建"
      @close="projectionModal.open = false"
      @confirm="rebuildProjection"
    >
      <p class="hint">
        默认走影子构建：先在旁路重建再切换，避免读模型在重建过程中对外暴露半成品。
      </p>
      <VFormField
        label="资产编码"
        required
      >
        <input v-model="projectionModal.asset_code">
      </VFormField>
      <VFormField
        label="重建范围"
        required
      >
        <select v-model="projectionModal.scope">
          <option value="entity">
            单个实体
          </option>
          <option value="partition">
            分区
          </option>
          <option value="full">
            全量
          </option>
        </select>
      </VFormField>
      <VFormField
        label="范围键"
        hint="实体或分区的标识；全量重建可留空。"
      >
        <input v-model="projectionModal.scope_key">
      </VFormField>
      <VFormField
        label="来源检查点"
        hint="JSON 对象，来自事件流的检查点位置。"
        required
      >
        <textarea
          v-model="projectionModal.source_checkpoint"
          rows="3"
        />
      </VFormField>
      <VFormField label="影子构建">
        <input
          v-model="projectionModal.shadow_build"
          type="checkbox"
        >
      </VFormField>
      <template #confirm>
        开始重建
      </template>
    </VModal>

    <VModal
      :open="repairModal.open"
      title="发起数据修复"
      @close="repairModal.open = false"
      @confirm="requestRepair"
    >
      <p class="hint">
        只能执行已登记的修复命令；修复由领域模块执行并回执，本中心不直接改写业务事实。
      </p>
      <VFormField
        label="修复命令码"
        required
      >
        <input v-model="repairModal.repair_code">
      </VFormField>
      <VFormField
        label="关联对账差异"
        hint="从差异列表发起时自动带入，用于把修复与它的依据绑定。"
      >
        <input v-model="repairModal.difference_id">
      </VFormField>
      <VFormField
        label="输入映射"
        hint="JSON 对象，修复命令所需的参数。"
        required
      >
        <textarea
          v-model="repairModal.input_mapping"
          rows="3"
        />
      </VFormField>
      <template #confirm>
        登记修复
      </template>
    </VModal>

    <VModal
      :open="erasureModal.open"
      title="创建删除传播计划"
      dangerous
      @close="erasureModal.open = false"
      @confirm="createErasurePlan"
    >
      <p class="hint">
        计划会按血缘展开到全部受限与高受限资产，逐个生成删除任务；同一隐私请求与血缘版本只会生成一份计划。
      </p>
      <VFormField
        label="隐私请求编号"
        required
      >
        <input v-model="erasureModal.privacy_request_id">
      </VFormField>
      <VFormField
        label="主体用户编号"
        required
      >
        <input v-model="erasureModal.subject_user_id">
      </VFormField>
      <VFormField
        label="血缘发布版本"
        hint="绑定已发布的血缘版本，保证覆盖范围可复核。"
        required
      >
        <input v-model="erasureModal.lineage_release_version">
      </VFormField>
      <template #confirm>
        创建计划
      </template>
    </VModal>

    <VModal
      :open="identifierModal.open"
      title="登记外部标识"
      @close="identifierModal.open = false"
      @confirm="registerIdentifier"
    >
      <VFormField
        label="实体类型"
        required
      >
        <input v-model="identifierModal.entity_type">
      </VFormField>
      <VFormField
        label="规范实体编号"
        required
      >
        <input v-model="identifierModal.canonical_entity_id">
      </VFormField>
      <VFormField
        label="提供方代码"
        required
      >
        <input v-model="identifierModal.provider_code">
      </VFormField>
      <VFormField
        label="外部标识"
        required
      >
        <input v-model="identifierModal.external_identifier">
      </VFormField>
      <template #confirm>
        登记
      </template>
    </VModal>

    <VModal
      :open="certificationModal.open"
      title="完整性认证决定"
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
  </section>
</template>

<style scoped>.data-console{display:grid;gap:var(--vav-density-page-gap)}header{display:flex;justify-content:space-between;align-items:end;gap:var(--vav-space-6)}header p{max-width:var(--vav-layout-content-reading)}.eyebrow{color:var(--vav-color-action-primary);font-weight:700;letter-spacing:.1em}nav{display:flex;flex-wrap:wrap;gap:var(--vav-space-2)}nav a{padding:var(--vav-space-2) var(--vav-space-3);border-radius:var(--vav-radius-pill);background:var(--vav-color-surface-soft);color:var(--vav-color-text);text-decoration:none}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:var(--vav-space-4)}.metrics article,.table-panel{padding:var(--vav-component-card-padding);border:1px solid var(--vav-color-border);border-radius:var(--vav-component-card-radius);background:var(--vav-color-surface-raised)}.metrics article{display:grid;gap:var(--vav-space-2)}.metrics strong{font-size:var(--vav-font-size-xl)}.actions{display:flex;justify-content:flex-end;gap:var(--vav-space-2);margin-bottom:var(--vav-space-3)}.hint{color:var(--vav-color-text-muted);margin:0 0 var(--vav-space-3)}@media(max-width:48rem){header{align-items:start;flex-direction:column}}</style>
