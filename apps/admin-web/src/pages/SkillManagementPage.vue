<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { localizeAdminLabel, localizeAdminValue } from "@vav/ui-admin";

import { VFormField, VModal } from "@vav/ui-core";

import {
  SKILL_SECTIONS_WITHOUT_SOURCE,
  skillsAdminApi,
  type SkillRow
} from "@/features/skills/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute();
const auth = useAdminAuthStore();
const section = computed(() => String(route.meta.skillSection ?? "dashboard"));
const rows = ref<SkillRow[]>([]);
const busy = ref(false);
const error = ref("");
const notice = ref("");

const sections = [
  ["dashboard", "概览", "skills.analytics.read"],
  ["catalog", "技能目录", "skills.registry.read"],
  ["installations", "安装", "skills.installations.read"],
  ["executions", "执行", "skills.executions.read"],
  ["dependencies", "依赖", "skills.registry.read"],
  ["permissions", "权限", "skills.permissions.read"],
  ["configurations", "配置", "skills.installations.read"],
  ["publishers", "发布者", "skills.publishers.read"],
  ["reviews", "审核", "skills.marketplace.review"],
  ["marketplace", "技能市场", "skills.marketplace.read"],
  ["incidents", "安全事件", "skills.incidents.read"],
  ["audit", "审计", "skills.audit.read"]
] as const;
const visibleSections = computed(() => sections.filter((item) => auth.hasPermission(item[2])));
const columns = computed(() => {
  const keys = new Set<string>();
  for (const row of rows.value.slice(0, 30)) {
    Object.keys(row).forEach((key) => {
      if (!/(encrypted|secret|credential|input|output|configuration)/iu.test(key)) keys.add(key);
    });
  }
  return [...keys].slice(0, 9);
});
const metrics = computed(() => ({
  registered: rows.value.filter((row) => row.skill_name).length,
  active: rows.value.filter((row) => row.status === "active").length,
  quarantined: rows.value.filter((row) => row.status === "quarantined").length,
  failed: rows.value.filter((row) => row.status === "failed").length
}));

async function load() {
  busy.value = true;
  error.value = "";
  try {
    await auth.bootstrap();
    // Each section now reads its own resource. Sections the backend does not
    // expose stay empty and say so, instead of borrowing another domain's rows.
    if (SKILL_SECTIONS_WITHOUT_SOURCE.includes(section.value)) {
      rows.value = [];
    } else if (section.value === "catalog") {
      rows.value = await skillsAdminApi.catalog();
    } else if (section.value === "permissions") {
      rows.value = await skillsAdminApi.installations();
    } else if (section.value === "executions") {
      rows.value = await skillsAdminApi.executions();
    } else if (section.value === "incidents") {
      rows.value = await skillsAdminApi.incidents();
    } else if (section.value === "publishers") {
      rows.value = await skillsAdminApi.publishers();
    } else if (section.value === "marketplace" || section.value === "reviews") {
      rows.value = await skillsAdminApi.marketplace();
    } else if (section.value === "dashboard") {
      const [catalog, installations, executions, marketplace] = await Promise.all([
        skillsAdminApi.catalog(),
        skillsAdminApi.installations(),
        skillsAdminApi.executions(),
        skillsAdminApi.marketplace()
      ]);
      rows.value = [...catalog, ...installations, ...executions, ...marketplace];
    } else {
      rows.value = await skillsAdminApi.installations();
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "Skill 控制面加载失败";
  } finally {
    busy.value = false;
  }
}

const versionsDrawer = ref(false);
const versionsSkill = ref("");
const versions = ref<SkillRow[]>([]);

/**
 * Reason codes on this platform are SCREAMING_SNAKE (backend pattern
 * ^[A-Z][A-Z0-9_]{2,127}$), and they used to be hard-coded — every disabled
 * installation carried "OPERATOR_CONFIRMED" and every marketplace review shipped
 * an empty findings list.
 */
const reasonDialog = ref<{
  open: boolean;
  title: string;
  intent: string;
  reason_code: string;
  detail: string;
  detailLabel: string;
  run?: (reasonCode: string, detail: string) => Promise<void>;
}>({ open: false, title: "", intent: "", reason_code: "", detail: "", detailLabel: "" });

const securityDialog = ref({
  open: false,
  version_id: "",
  decision: "passed" as "passed" | "passed_with_warnings" | "failed",
  compatible: true,
  reason_code: "",
  notes: ""
});
const revocationDialog = ref({
  open: false,
  publisher_id: "",
  key_id: "",
  package_checksum: "",
  reason_code: "",
  reason: ""
});

function askReason(
  title: string,
  intent: string,
  run: (reasonCode: string, detail: string) => Promise<void>,
  detailLabel = ""
) {
  error.value = "";
  notice.value = "";
  reasonDialog.value = { open: true, title, intent, reason_code: "", detail: "", detailLabel, run };
}

async function confirmReason() {
  const { reason_code, detail, run, title } = reasonDialog.value;
  if (!run) return;
  if (!/^[A-Z][A-Z0-9_]{2,127}$/u.test(reason_code.trim())) {
    error.value = "原因代码需为大写字母、数字与下划线，例如 SECURITY_REGRESSION。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await run(reason_code.trim(), detail.trim());
    notice.value = `${title}已完成并记录审计。`;
    reasonDialog.value = { open: false, title: "", intent: "", reason_code: "", detail: "", detailLabel: "" };
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : `${title}失败`;
  } finally {
    busy.value = false;
  }
}

async function installationAction(
  row: SkillRow,
  action: "approve" | "activate" | "disable" | "rollback" | "uninstall"
) {
  if (!row.id) return;
  if (action === "approve" || action === "activate") {
    if (!window.confirm("该操作会改变 Skill 运行状态，确认继续？")) return;
    busy.value = true;
    error.value = "";
    try {
      if (action === "approve") await skillsAdminApi.approveInstallation(String(row.id));
      else await skillsAdminApi.activateInstallation(String(row.id));
      notice.value = "状态已更新；签名、安全、兼容和职责分离门禁仍由服务端强制执行。";
      await load();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "操作失败";
    } finally {
      busy.value = false;
    }
    return;
  }
  const label = { disable: "停用安装", rollback: "回滚安装", uninstall: "卸载" }[action];
  askReason(label, "该操作会立即改变这个 Skill 对业务的可用性。", async (reasonCode) => {
    if (action === "disable") await skillsAdminApi.disableInstallation(String(row.id), reasonCode);
    if (action === "rollback") await skillsAdminApi.rollbackInstallation(String(row.id), reasonCode);
    if (action === "uninstall") await skillsAdminApi.uninstallInstallation(String(row.id), reasonCode);
  });
}

async function listingAction(row: SkillRow, action: "approve" | "changes" | "publish") {
  if (!row.id) return;
  if (action === "publish") {
    if (!window.confirm("发布会让该 Skill 对外可见，确认继续？")) return;
    busy.value = true;
    try {
      await skillsAdminApi.publishListing(String(row.id));
      notice.value = "Marketplace 上架状态已更新并记录审计。";
      await load();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "发布失败";
    } finally {
      busy.value = false;
    }
    return;
  }
  askReason(
    action === "approve" ? "通过上架审核" : "要求修改",
    "审核意见会返回给发布者；要求修改时请逐条写明问题，否则发布者无从下手。",
    async (reasonCode, detail) => {
      const findings = detail.split(/\n+/u).map((item) => item.trim()).filter(Boolean);
      if (action === "changes" && !findings.length) {
        throw new Error("要求修改必须至少写一条具体问题。");
      }
      await skillsAdminApi.reviewListing(
        String(row.id),
        action === "approve" ? "approved" : "changes_required",
        reasonCode,
        findings
      );
    },
    "审核意见（每行一条）"
  );
}

function publisherAction(row: SkillRow, decision: "verified" | "rejected") {
  askReason(
    decision === "verified" ? "核验发布者" : "驳回发布者",
    "核验通过的发布者才能提交签名包；驳回后其提交会被拒绝。",
    async (reasonCode) => {
      await skillsAdminApi.verifyPublisher(String(row.id), decision, reasonCode);
    }
  );
}

async function openVersions(row: SkillRow) {
  const name = String(row.skill_name ?? "");
  if (!name) return;
  error.value = "";
  try {
    versions.value = await skillsAdminApi.versions(name);
    versionsSkill.value = name;
    versionsDrawer.value = true;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "版本列表加载失败";
  }
}

function openSecurityReview(version: SkillRow) {
  error.value = "";
  securityDialog.value = {
    open: true,
    version_id: String(version.id ?? ""),
    decision: "passed",
    compatible: true,
    reason_code: "",
    notes: ""
  };
}

async function submitSecurityReview() {
  const form = securityDialog.value;
  if (!/^[A-Z][A-Z0-9_]{2,127}$/u.test(form.reason_code.trim())) {
    error.value = "原因代码需为大写字母、数字与下划线，例如 SBOM_CLEAN。";
    return;
  }
  if (form.notes.trim().length < 10) {
    error.value = "请填写至少 10 个字符的评审说明，它会随报告一起留存。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await skillsAdminApi.securityReview(form.version_id, {
      decision: form.decision,
      compatible: form.compatible,
      reason_code: form.reason_code.trim(),
      report: { notes: form.notes.trim(), reviewed_via: "admin_console" }
    });
    notice.value = "安全评审结论已记录。";
    form.open = false;
    if (versionsSkill.value) versions.value = await skillsAdminApi.versions(versionsSkill.value);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "安全评审失败";
  } finally {
    busy.value = false;
  }
}

function quarantineVersion(version: SkillRow) {
  askReason(
    "隔离版本",
    "隔离会立即阻断该版本的新安装与执行。",
    async (reasonCode) => {
      await skillsAdminApi.quarantineVersion(String(version.id), reasonCode);
      if (versionsSkill.value) versions.value = await skillsAdminApi.versions(versionsSkill.value);
    }
  );
}

async function revokeSignature() {
  const form = revocationDialog.value;
  if (!form.publisher_id.trim() || !form.key_id.trim()) {
    error.value = "请填写发布者编号与签名密钥标识。";
    return;
  }
  if (!/^[A-Z][A-Z0-9_]{2,127}$/u.test(form.reason_code.trim())) {
    error.value = "原因代码需为大写字母、数字与下划线，例如 KEY_COMPROMISE。";
    return;
  }
  if (form.reason.trim().length < 10) {
    error.value = "请填写至少 10 个字符的吊销说明。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await skillsAdminApi.revokeSignature({
      publisher_id: form.publisher_id.trim(),
      key_id: form.key_id.trim(),
      package_checksum: form.package_checksum.trim() || null,
      reason_code: form.reason_code.trim(),
      reason: form.reason.trim()
    });
    notice.value = "签名吊销已登记；使用该密钥签名的包将不再被接受。";
    form.open = false;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "签名吊销失败";
  } finally {
    busy.value = false;
  }
}

watch(() => route.fullPath, load);
onMounted(load);
</script>

<template>
  <section class="skills-console">
    <header>
      <div>
        <p class="eyebrow">
          第 20 批 · 受控技能平台
        </p><h1>技能控制台</h1>
      </div>
      <p>第三方代码不进入 API 主进程；高风险权限、签名、SBOM、兼容性和 Marketplace 人工审核均为服务端 fail-closed 门禁。</p>
    </header>
    <nav>
      <RouterLink
        v-for="item in visibleSections"
        :key="item[0]"
        :to="`/admin/skills/${item[0]}`"
      >
        {{ item[1] }}
      </RouterLink>
    </nav>
    <p
      v-if="busy"
      role="status"
    >
      正在读取 Skill 控制面…
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
      v-if="section === 'dashboard'"
      class="metrics"
    >
      <div
        v-for="(value, key) in metrics"
        :key="key"
      >
        <strong>{{ localizeAdminLabel(key) }}</strong><span>{{ localizeAdminValue(value, key) }}</span>
      </div>
    </article>
    <article class="panel">
      <p
        v-if="section === 'permissions'"
        class="warning"
      >
        高风险权限不会隐藏：任何新增权限都要求重新生成安装计划并重新审批。这里按安装列出实际已授予的权限。
      </p>
      <p
        v-if="SKILL_SECTIONS_WITHOUT_SOURCE.includes(section)"
        class="warning"
      >
        后端尚未提供该视图的数据源。此前这里显示的是技能目录或执行记录，与标签名不符，已改为空视图而不是展示别处的数据。
      </p>
      <div
        v-if="section === 'catalog' && auth.hasPermission('skills.security.revoke_signature')"
        class="panel-toolbar"
      >
        <button @click="revocationDialog.open = true">
          吊销签名密钥
        </button>
      </div>
      <table v-if="rows.length">
        <thead>
          <tr>
            <th
              v-for="column in columns"
              :key="column"
            >
              {{ localizeAdminLabel(column) }}
            </th><th>受控操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="String(row.id ?? row.skill_name ?? JSON.stringify(row))"
          >
            <td
              v-for="column in columns"
              :key="column"
            >
              {{ localizeAdminValue(row[column], column) }}
            </td>
            <td class="actions">
              <template v-if="section === 'installations'">
                <button
                  v-if="row.status === 'approval_required'"
                  :disabled="!auth.hasPermission('skills.installations.approve')"
                  @click="installationAction(row, 'approve')"
                >
                  独立审批
                </button>
                <button
                  v-if="row.status === 'validating'"
                  :disabled="!auth.hasPermission('skills.installations.activate')"
                  @click="installationAction(row, 'activate')"
                >
                  激活
                </button>
                <button
                  v-if="row.status === 'active'"
                  :disabled="!auth.hasPermission('skills.installations.disable')"
                  @click="installationAction(row, 'disable')"
                >
                  停用
                </button>
                <button
                  v-if="['active', 'failed'].includes(String(row.status))"
                  :disabled="!auth.hasPermission('skills.installations.rollback')"
                  @click="installationAction(row, 'rollback')"
                >
                  回滚
                </button>
                <button
                  v-if="row.status !== 'uninstalled'"
                  :disabled="!auth.hasPermission('skills.installations.uninstall')"
                  @click="installationAction(row, 'uninstall')"
                >
                  卸载
                </button>
              </template>
              <template v-else-if="section === 'catalog'">
                <button
                  :disabled="!auth.hasPermission('skills.registry.read')"
                  @click="openVersions(row)"
                >
                  版本与安全门禁
                </button>
              </template>
              <template v-else-if="section === 'publishers'">
                <button
                  v-if="row.status !== 'verified'"
                  :disabled="!auth.hasPermission('skills.publishers.verify')"
                  @click="publisherAction(row, 'verified')"
                >
                  核验通过
                </button>
                <button
                  v-if="row.status !== 'rejected'"
                  :disabled="!auth.hasPermission('skills.publishers.verify')"
                  @click="publisherAction(row, 'rejected')"
                >
                  驳回
                </button>
              </template>
              <template v-else-if="section === 'reviews' || section === 'marketplace'">
                <button
                  v-if="row.listing_status === 'human_review'"
                  :disabled="!auth.hasPermission('skills.marketplace.review')"
                  @click="listingAction(row, 'approve')"
                >
                  批准
                </button>
                <button
                  v-if="row.listing_status === 'human_review'"
                  :disabled="!auth.hasPermission('skills.marketplace.review')"
                  @click="listingAction(row, 'changes')"
                >
                  要求修改
                </button>
                <button
                  v-if="row.listing_status === 'approved'"
                  :disabled="!auth.hasPermission('skills.marketplace.approve')"
                  @click="listingAction(row, 'publish')"
                >
                  发布
                </button>
              </template>
              <span v-else>只读</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="!busy">
        暂无记录。
      </p>
    </article>

    <el-drawer
      v-model="versionsDrawer"
      :title="`${versionsSkill} · 版本与安全门禁`"
      size="720px"
    >
      <p class="warning">
        安全评审与隔离作用于具体版本：隔离会立刻阻断该版本的新安装与执行，已在运行的安装需要单独回滚。
      </p>
      <table v-if="versions.length">
        <thead><tr><th>版本</th><th>签名</th><th>安全</th><th>兼容</th><th>操作</th></tr></thead>
        <tbody>
          <tr
            v-for="version in versions"
            :key="String(version.id)"
          >
            <td>{{ version.semantic_version }}</td>
            <td>{{ localizeAdminValue(version.signature_status, "signature_status") }}</td>
            <td>{{ localizeAdminValue(version.security_status, "security_status") }}</td>
            <td>{{ localizeAdminValue(version.compatibility_status, "compatibility_status") }}</td>
            <td class="actions">
              <button
                :disabled="!auth.hasPermission('skills.security.read')"
                @click="openSecurityReview(version)"
              >
                安全评审
              </button>
              <button
                v-if="version.security_status !== 'quarantined'"
                :disabled="!auth.hasPermission('skills.security.quarantine')"
                @click="quarantineVersion(version)"
              >
                隔离
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else>
        该 Skill 暂无已登记版本。
      </p>
    </el-drawer>

    <VModal
      :open="reasonDialog.open"
      title="确认受控操作"
      dangerous
      @close="reasonDialog.open = false"
      @confirm="confirmReason"
    >
      <p class="hint">
        {{ reasonDialog.intent }}
      </p>
      <VFormField
        label="原因代码"
        hint="大写字母、数字与下划线，例如 SECURITY_REGRESSION。"
        required
      >
        <input v-model="reasonDialog.reason_code">
      </VFormField>
      <VFormField
        v-if="reasonDialog.detailLabel"
        :label="reasonDialog.detailLabel"
      >
        <textarea
          v-model="reasonDialog.detail"
          rows="4"
        />
      </VFormField>
      <template #confirm>
        {{ reasonDialog.title }}
      </template>
    </VModal>

    <VModal
      :open="securityDialog.open"
      title="登记安全评审结论"
      @close="securityDialog.open = false"
      @confirm="submitSecurityReview"
    >
      <VFormField
        label="评审结论"
        required
      >
        <select v-model="securityDialog.decision">
          <option value="passed">
            通过
          </option>
          <option value="passed_with_warnings">
            通过但有告警
          </option>
          <option value="failed">
            不通过
          </option>
        </select>
      </VFormField>
      <VFormField label="兼容当前运行时">
        <input
          v-model="securityDialog.compatible"
          type="checkbox"
        >
      </VFormField>
      <VFormField
        label="原因代码"
        required
      >
        <input v-model="securityDialog.reason_code">
      </VFormField>
      <VFormField
        label="评审说明"
        hint="至少 10 个字符，会随报告留存，供后续复核。"
        required
      >
        <textarea
          v-model="securityDialog.notes"
          rows="4"
        />
      </VFormField>
      <template #confirm>
        提交结论
      </template>
    </VModal>

    <VModal
      :open="revocationDialog.open"
      title="吊销签名密钥"
      dangerous
      @close="revocationDialog.open = false"
      @confirm="revokeSignature"
    >
      <p class="hint">
        吊销后使用该密钥签名的包将一律不被接受。留空包校验和表示吊销整把密钥，填写则只吊销单个包。
      </p>
      <VFormField
        label="发布者编号"
        required
      >
        <input v-model="revocationDialog.publisher_id">
      </VFormField>
      <VFormField
        label="密钥标识"
        required
      >
        <input v-model="revocationDialog.key_id">
      </VFormField>
      <VFormField label="包校验和（SHA-256，可选）">
        <input v-model="revocationDialog.package_checksum">
      </VFormField>
      <VFormField
        label="原因代码"
        required
      >
        <input v-model="revocationDialog.reason_code">
      </VFormField>
      <VFormField
        label="吊销说明"
        required
      >
        <textarea
          v-model="revocationDialog.reason"
          rows="3"
        />
      </VFormField>
      <template #confirm>
        确认吊销
      </template>
    </VModal>
  </section>
</template>

<style scoped>
.skills-console{display:grid;gap:1rem}header{display:flex;justify-content:space-between;gap:2rem;align-items:end}header>p{max-width:680px}.eyebrow{letter-spacing:.12em;color:var(--vav-color-focus)}nav{display:flex;gap:.5rem;flex-wrap:wrap}nav a{padding:.5rem .8rem;border-radius:999px;background:var(--vav-color-surface-info);color:var(--vav-color-text);text-decoration:none}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1rem}.metrics div,.panel{padding:1rem;border:1px solid var(--vav-color-border);border-radius:12px;background:var(--vav-color-surface-raised)}.metrics div{display:grid;gap:.35rem}.metrics span{font-size:1.7rem}.panel{overflow:auto}.warning{padding:.8rem;background:var(--vav-color-surface-warning);border-left:4px solid var(--vav-color-warning)}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:.65rem;border-bottom:1px solid var(--vav-color-surface-soft);max-width:250px;overflow-wrap:anywhere}.actions{display:flex;gap:.4rem;flex-wrap:wrap}.panel-toolbar{display:flex;gap:.6rem;margin-bottom:1rem}.hint{color:var(--vav-color-text-muted);margin:0 0 .75rem}input,select,textarea{padding:.6rem;border:1px solid var(--vav-color-border-strong);border-radius:8px}button{padding:.5rem .75rem;border:0;border-radius:999px;background:var(--vav-color-focus);color:var(--vav-color-surface-raised)}button:disabled{opacity:.45}.alert{padding:.8rem}.error{background:var(--vav-color-surface-danger)}.notice{background:var(--vav-color-surface-success)}@media(max-width:700px){header{align-items:start;flex-direction:column}}
</style>
