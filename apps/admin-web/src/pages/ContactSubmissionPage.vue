<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { formatAdminTableCell, localizeAdminValue } from "@vav/ui-admin";

import { resolveApiBaseUrl } from "@/config/api";
import { catalogApi } from "@/features/catalog/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

type ContactSummary = {
  id: string;
  submission_type: string;
  name: string;
  email: string;
  region?: string | null;
  subject?: string | null;
  message: string;
  status: string;
  locale: string;
  privacy_consent_version: string;
  created_at: string;
};

type ContactDetail = ContactSummary & {
  assigned_to?: string | null;
  privacy_consented_at: string;
  source_page?: string | null;
  resolved_at?: string | null;
};

type AdminOption = { id: string; email: string; status: string };

const CONTACT_STATUSES = [
  { value: "new", label: "待处理" },
  { value: "in_progress", label: "处理中" },
  { value: "waiting_external", label: "等待对方回复" },
  { value: "resolved", label: "已结案" },
  { value: "spam", label: "垃圾信息" },
  { value: "archived", label: "已归档" }
];

const auth = useAdminAuthStore();
const submissions = ref<ContactSummary[]>([]);
const admins = ref<AdminOption[]>([]);
const selected = ref<ContactDetail>();
const drawerOpen = ref(false);
const loading = ref(false);
const saving = ref(false);
const exporting = ref(false);
const error = ref("");
const notice = ref("");
const statusFilter = ref("");
const typeFilter = ref("");
const keyword = ref("");
const statusForm = ref({ status: "", reason: "" });
const assignForm = ref({ assigned_to: "", reason: "" });
const resolveForm = ref({ resolution: "" });

const canAssign = computed(() => auth.hasPermission("contact.submissions.assign"));
const canResolve = computed(() => auth.hasPermission("contact.submissions.resolve"));
const canExport = computed(() => auth.hasPermission("contact.submissions.export"));
const canReadAdmins = computed(() => auth.hasPermission("admins.read"));

const submissionTypes = computed(() =>
  [...new Set(submissions.value.map((item) => item.submission_type))].sort()
);

const visibleSubmissions = computed(() => {
  const query = keyword.value.trim().toLocaleLowerCase();
  return submissions.value.filter((item) => {
    if (statusFilter.value && item.status !== statusFilter.value) return false;
    if (typeFilter.value && item.submission_type !== typeFilter.value) return false;
    if (!query) return true;
    return [item.name, item.email, item.subject ?? "", item.region ?? "", item.message]
      .join(" ")
      .toLocaleLowerCase()
      .includes(query);
  });
});

const pendingCount = computed(
  () => submissions.value.filter((item) => item.status === "new").length
);

function assigneeLabel(id?: string | null) {
  if (!id) return "未指派";
  return admins.value.find((item) => item.id === id)?.email ?? id;
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    await auth.bootstrap();
    const [list, adminList] = await Promise.all([
      catalogApi<{ items: ContactSummary[] }>("/admin/contact-submissions"),
      canReadAdmins.value
        ? catalogApi<{ items: AdminOption[] }>("/admin/admins?page_size=100")
        : Promise.resolve({ items: [] as AdminOption[] })
    ]);
    submissions.value = list.items;
    admins.value = adminList.items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "合作联系记录加载失败";
  } finally {
    loading.value = false;
  }
}

async function openSubmission(row: ContactSummary) {
  error.value = "";
  try {
    const detail = await catalogApi<ContactDetail>(`/admin/contact-submissions/${row.id}`);
    selected.value = detail;
    statusForm.value = { status: detail.status, reason: "" };
    assignForm.value = { assigned_to: detail.assigned_to ?? "", reason: "" };
    resolveForm.value = { resolution: "" };
    drawerOpen.value = true;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "联系记录详情加载失败";
  }
}

function validReason(value: string, field = "操作原因") {
  if (value.trim().length >= 10) return true;
  error.value = `请填写至少 10 个字符的${field}，内容会写入不可变的安全审计记录。`;
  return false;
}

async function refreshSelected() {
  if (!selected.value) return;
  const detail = await catalogApi<ContactDetail>(`/admin/contact-submissions/${selected.value.id}`);
  selected.value = detail;
  statusForm.value = { status: detail.status, reason: "" };
  assignForm.value = { assigned_to: detail.assigned_to ?? "", reason: "" };
  resolveForm.value = { resolution: "" };
}

async function changeStatus() {
  if (!selected.value) return;
  if (!statusForm.value.status) {
    error.value = "请选择要流转到的状态。";
    return;
  }
  if (!validReason(statusForm.value.reason, "状态变更原因")) return;
  saving.value = true;
  error.value = "";
  try {
    await catalogApi(`/admin/contact-submissions/${selected.value.id}/status`, {
      method: "PATCH",
      body: JSON.stringify({
        status: statusForm.value.status,
        reason: statusForm.value.reason.trim()
      })
    });
    notice.value = "联系记录状态已更新。";
    await Promise.all([load(), refreshSelected()]);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "状态更新失败";
  } finally {
    saving.value = false;
  }
}

async function assign() {
  if (!selected.value) return;
  if (!assignForm.value.assigned_to.trim()) {
    error.value = "请选择或填写处理人。";
    return;
  }
  if (!validReason(assignForm.value.reason, "指派原因")) return;
  saving.value = true;
  error.value = "";
  try {
    await catalogApi(`/admin/contact-submissions/${selected.value.id}/assign`, {
      method: "POST",
      body: JSON.stringify({
        assigned_to: assignForm.value.assigned_to.trim(),
        reason: assignForm.value.reason.trim()
      })
    });
    notice.value = "已指派处理人；待处理的记录会自动转为处理中。";
    await Promise.all([load(), refreshSelected()]);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "指派失败";
  } finally {
    saving.value = false;
  }
}

async function resolve() {
  if (!selected.value) return;
  if (!validReason(resolveForm.value.resolution, "结案说明")) return;
  if (!window.confirm("确认将该联系记录标记为已结案？结案说明会写入审计记录。")) return;
  saving.value = true;
  error.value = "";
  try {
    await catalogApi(`/admin/contact-submissions/${selected.value.id}/resolve`, {
      method: "POST",
      body: JSON.stringify({ resolution: resolveForm.value.resolution.trim() })
    });
    notice.value = "联系记录已结案。";
    await Promise.all([load(), refreshSelected()]);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "结案失败";
  } finally {
    saving.value = false;
  }
}

async function exportCsv() {
  exporting.value = true;
  error.value = "";
  try {
    await auth.bootstrap();
    const response = await fetch(`${resolveApiBaseUrl()}/admin/contact-submissions/export`, {
      method: "POST",
      credentials: "include",
      headers: { Authorization: `Bearer ${auth.accessToken}` }
    });
    if (!response.ok) {
      throw new Error("导出失败，请确认已获得导出权限。");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "contact-submissions.csv";
    link.click();
    URL.revokeObjectURL(url);
    notice.value = "导出文件已生成；导出行为同样受权限约束并留痕。";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "导出失败";
  } finally {
    exporting.value = false;
  }
}

onMounted(() => void load());
</script>

<template>
  <section class="admin-module contact-admin">
    <header class="module-heading">
      <div>
        <p class="admin-kicker">
          合作与咨询受理
        </p>
        <h2>合作联系记录</h2>
        <p>受理、指派、状态流转、结案与导出构成完整闭环；每一次处置都写入安全审计。</p>
      </div>
      <div class="heading-actions">
        <el-tag
          v-if="pendingCount"
          type="warning"
          effect="plain"
        >
          待处理 {{ pendingCount }} 条
        </el-tag>
        <el-button
          v-if="canExport"
          :loading="exporting"
          @click="exportCsv"
        >
          导出 CSV
        </el-button>
        <el-button
          :loading="loading"
          @click="load"
        >
          刷新
        </el-button>
      </div>
    </header>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
    />
    <el-alert
      v-if="notice"
      :title="notice"
      type="success"
      :closable="false"
      show-icon
    />

    <div class="filters">
      <el-input
        v-model="keyword"
        clearable
        placeholder="按姓名、邮箱、主题或正文搜索"
      />
      <el-select
        v-model="statusFilter"
        clearable
        placeholder="全部状态"
      >
        <el-option
          v-for="option in CONTACT_STATUSES"
          :key="option.value"
          :label="option.label"
          :value="option.value"
        />
      </el-select>
      <el-select
        v-model="typeFilter"
        clearable
        placeholder="全部类型"
      >
        <el-option
          v-for="type in submissionTypes"
          :key="type"
          :label="localizeAdminValue(type, 'submission_type')"
          :value="type"
        />
      </el-select>
    </div>

    <el-table
      v-loading="loading"
      :data="visibleSubmissions"
      stripe
      empty-text="暂无联系记录"
    >
      <el-table-column
        prop="submission_type"
        label="提交类型"
        min-width="140"
      >
        <template #default="scope">
          {{ localizeAdminValue(scope.row.submission_type, "submission_type") }}
        </template>
      </el-table-column>
      <el-table-column
        prop="name"
        label="联系人"
        min-width="120"
      />
      <el-table-column
        prop="email"
        label="邮箱"
        min-width="220"
      />
      <el-table-column
        prop="subject"
        label="主题"
        min-width="200"
      />
      <el-table-column
        prop="region"
        label="地区"
        min-width="120"
      />
      <el-table-column
        prop="status"
        label="处理状态"
        min-width="130"
      >
        <template #default="scope">
          {{ localizeAdminValue(scope.row.status, "status") }}
        </template>
      </el-table-column>
      <el-table-column
        prop="created_at"
        label="提交时间（UTC+8）"
        min-width="200"
        :formatter="formatAdminTableCell"
      />
      <el-table-column
        label="操作"
        fixed="right"
        width="100"
      >
        <template #default="scope">
          <el-button
            link
            type="primary"
            @click="openSubmission(scope.row)"
          >
            处理
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer
      v-model="drawerOpen"
      title="联系记录处理"
      size="720px"
    >
      <template v-if="selected">
        <div class="summary-grid">
          <div><small>联系人</small><strong>{{ selected.name }}</strong></div>
          <div><small>邮箱</small><strong>{{ selected.email }}</strong></div>
          <div><small>处理状态</small><strong>{{ localizeAdminValue(selected.status, "status") }}</strong></div>
          <div><small>当前处理人</small><strong>{{ assigneeLabel(selected.assigned_to) }}</strong></div>
          <div><small>来源页面</small><strong>{{ selected.source_page || "未记录" }}</strong></div>
          <div><small>隐私同意版本</small><strong>{{ selected.privacy_consent_version }}</strong></div>
        </div>

        <h3>咨询正文</h3>
        <p class="message-body">
          {{ selected.message }}
        </p>

        <h3>指派处理人</h3>
        <el-form
          label-position="top"
          class="action-form"
        >
          <el-form-item label="处理人">
            <el-select
              v-if="canReadAdmins && admins.length"
              v-model="assignForm.assigned_to"
              filterable
              placeholder="选择管理员"
              :disabled="!canAssign"
            >
              <el-option
                v-for="admin in admins"
                :key="admin.id"
                :label="admin.email"
                :value="admin.id"
              />
            </el-select>
            <el-input
              v-else
              v-model="assignForm.assigned_to"
              :disabled="!canAssign"
              placeholder="填写处理人用户编号（UUID）"
            />
          </el-form-item>
          <el-form-item label="指派原因（至少 10 个字符）">
            <el-input
              v-model="assignForm.reason"
              type="textarea"
              :rows="2"
              :disabled="!canAssign"
            />
          </el-form-item>
          <el-button
            v-if="canAssign"
            type="primary"
            :loading="saving"
            @click="assign"
          >
            指派
          </el-button>
        </el-form>

        <h3>状态流转</h3>
        <el-form
          label-position="top"
          class="action-form"
        >
          <el-form-item label="目标状态">
            <el-select
              v-model="statusForm.status"
              :disabled="!canResolve"
            >
              <el-option
                v-for="option in CONTACT_STATUSES"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="状态变更原因（至少 10 个字符）">
            <el-input
              v-model="statusForm.reason"
              type="textarea"
              :rows="2"
              :disabled="!canResolve"
            />
          </el-form-item>
          <el-button
            v-if="canResolve"
            :loading="saving"
            @click="changeStatus"
          >
            更新状态
          </el-button>
        </el-form>

        <h3>结案</h3>
        <el-form
          label-position="top"
          class="action-form"
        >
          <el-form-item label="结案说明（至少 10 个字符）">
            <el-input
              v-model="resolveForm.resolution"
              type="textarea"
              :rows="3"
              :disabled="!canResolve"
              placeholder="写明与对方达成的结论、后续动作与负责人。"
            />
          </el-form-item>
          <el-button
            v-if="canResolve"
            type="success"
            :loading="saving"
            @click="resolve"
          >
            标记已结案
          </el-button>
        </el-form>

        <p class="boundary">
          结案时间由服务端记录，联系人正文不会被导出到审计事件中，仅记录处置理由。
        </p>
      </template>
    </el-drawer>
  </section>
</template>

<style scoped>
.module-heading,.heading-actions,.filters{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.module-heading{justify-content:space-between}.filters{margin:18px 0}.filters .el-input{max-width:320px}.filters .el-select{width:180px}.summary-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-bottom:20px}.summary-grid div{display:grid;gap:5px;padding:14px;border:1px solid var(--el-border-color);border-radius:8px}.summary-grid strong{overflow-wrap:anywhere}.message-body{padding:14px;border:1px solid var(--el-border-color);border-radius:8px;white-space:pre-wrap;overflow-wrap:anywhere}.action-form{margin:12px 0 20px}.boundary{color:var(--el-text-color-secondary);margin-top:20px}h3{margin-top:24px}@media(max-width:720px){.summary-grid{grid-template-columns:1fr}}
</style>
