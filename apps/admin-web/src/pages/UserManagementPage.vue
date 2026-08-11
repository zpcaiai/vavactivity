<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { formatAdminTableCell, localizeAdminValue } from "@vav/ui-admin";

import PaginationBar from "@/components/PaginationBar.vue";
import { catalogApi } from "@/features/catalog/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

type UserSummary = {
  id: string;
  email: string;
  status: string;
  email_verified: boolean;
  preferred_locale: string;
  timezone: string;
  last_login_at?: string | null;
  updated_at: string;
  created_at: string;
  version: number;
};

type UserRole = { code: string; name: string; granted_at: string; expires_at?: string | null };
type UserDetail = UserSummary & {
  failed_login_count: number;
  locked_until?: string | null;
  password_changed_at?: string | null;
  deletion_requested_at?: string | null;
  deleted_at?: string | null;
  active_sessions: number;
  roles: UserRole[];
};

type HistoryEvent = {
  id: string;
  event_type: string;
  severity: string;
  actor_type: string;
  actor_user_id?: string | null;
  reason?: string | null;
  before_state?: Record<string, unknown> | null;
  after_state?: Record<string, unknown> | null;
  metadata?: Record<string, unknown>;
  occurred_at: string;
};

const auth = useAdminAuthStore();
const users = ref<UserSummary[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const search = ref("");
const statusFilter = ref("");
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const notice = ref("");
const selected = ref<UserDetail>();
const history = ref<HistoryEvent[]>([]);
const drawerOpen = ref(false);
const form = ref({ email: "", preferred_locale: "zh-CN", timezone: "Asia/Shanghai", reason: "" });

const canUpdate = computed(() => auth.hasPermission("users.update"));
const canSuspend = computed(() => auth.hasPermission("users.suspend"));
const canRestore = computed(() => auth.hasPermission("users.restore"));
const canRevokeSessions = computed(() => auth.hasPermission("users.sessions.revoke"));

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const params = new URLSearchParams({ page: String(page.value), page_size: String(pageSize.value) });
    if (search.value.trim()) params.set("search", search.value.trim());
    if (statusFilter.value) params.set("status", statusFilter.value);
    const result = await catalogApi<{ items: UserSummary[]; total: number }>(
      `/admin/users?${params.toString()}`,
    );
    users.value = result.items;
    total.value = result.total;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "用户列表加载失败";
  } finally {
    loading.value = false;
  }
}

async function openUser(user: UserSummary) {
  loading.value = true;
  error.value = "";
  try {
    const [detail, events] = await Promise.all([
      catalogApi<UserDetail>(`/admin/users/${user.id}`),
      catalogApi<{ items: HistoryEvent[] }>(`/admin/users/${user.id}/history?page_size=100`),
    ]);
    selected.value = detail;
    history.value = events.items;
    form.value = {
      email: detail.email,
      preferred_locale: detail.preferred_locale,
      timezone: detail.timezone,
      reason: "",
    };
    drawerOpen.value = true;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "用户详情加载失败";
  } finally {
    loading.value = false;
  }
}

function requireReason() {
  if (form.value.reason.trim().length >= 10) return true;
  error.value = "请填写至少 10 个字符的操作原因，原因将写入不可变审计记录。";
  return false;
}

async function refreshSelected() {
  if (!selected.value) return;
  await openUser(selected.value);
}

async function saveUser() {
  if (!selected.value || !requireReason()) return;
  saving.value = true;
  error.value = "";
  try {
    selected.value = await catalogApi<UserDetail>(`/admin/users/${selected.value.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        expected_version: selected.value.version,
        email: form.value.email,
        preferred_locale: form.value.preferred_locale,
        timezone: form.value.timezone,
        reason: form.value.reason.trim(),
      }),
    });
    notice.value = "用户资料已更新；如邮箱发生变化，原会话已撤销且邮箱需要重新验证。";
    await Promise.all([load(), refreshSelected()]);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "用户资料保存失败";
  } finally {
    saving.value = false;
  }
}

async function userAction(action: "suspend" | "restore" | "deactivate" | "sessions/revoke") {
  if (!selected.value || !requireReason()) return;
  const actionName = {
    suspend: "封禁用户",
    restore: "解封并恢复用户",
    deactivate: "注销用户账户",
    "sessions/revoke": "撤销全部登录会话",
  }[action];
  if (!window.confirm(`确认${actionName}？该操作会立即影响用户访问并写入审计。`)) return;
  saving.value = true;
  error.value = "";
  try {
    const body: Record<string, unknown> = { reason: form.value.reason.trim() };
    if (action === "deactivate") body.expected_version = selected.value.version;
    await catalogApi(`/admin/users/${selected.value.id}/${action}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    notice.value = `${actionName}操作已完成。`;
    await Promise.all([load(), refreshSelected()]);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : `${actionName}失败`;
  } finally {
    saving.value = false;
  }
}

function searchUsers() {
  page.value = 1;
  void load();
}

onMounted(() => void load());
</script>

<template>
  <section class="admin-module user-admin">
    <header class="module-heading">
      <div>
        <p class="admin-kicker">
          用户全生命周期
        </p>
        <h2>用户管理</h2>
        <p>查询、编辑、封禁、解封、注销、会话撤销和操作历史形成完整闭环。</p>
      </div>
      <el-button
        :loading="loading"
        @click="load"
      >
        刷新
      </el-button>
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
        v-model="search"
        clearable
        placeholder="按邮箱搜索"
        @keyup.enter="searchUsers"
      />
      <el-select
        v-model="statusFilter"
        clearable
        placeholder="全部状态"
      >
        <el-option
          label="待验证"
          value="pending_verification"
        />
        <el-option
          label="正常"
          value="active"
        />
        <el-option
          label="已锁定"
          value="locked"
        />
        <el-option
          label="已封禁"
          value="suspended"
        />
        <el-option
          label="注销处理中"
          value="deletion_pending"
        />
        <el-option
          label="已注销"
          value="deleted"
        />
      </el-select>
      <el-button
        type="primary"
        @click="searchUsers"
      >
        查询
      </el-button>
    </div>

    <el-table
      v-loading="loading"
      :data="users"
      stripe
      empty-text="暂无用户"
    >
      <el-table-column
        prop="email"
        label="邮箱"
        min-width="240"
      />
      <el-table-column
        prop="status"
        label="账户状态"
        min-width="130"
      >
        <template #default="scope">
          {{ localizeAdminValue(scope.row.status, "status") }}
        </template>
      </el-table-column>
      <el-table-column
        prop="email_verified"
        label="邮箱已验证"
        min-width="120"
      >
        <template #default="scope">
          {{ scope.row.email_verified ? "是" : "否" }}
        </template>
      </el-table-column>
      <el-table-column
        prop="preferred_locale"
        label="首选语言"
        min-width="120"
      >
        <template #default="scope">
          {{ localizeAdminValue(scope.row.preferred_locale, "locale") }}
        </template>
      </el-table-column>
      <el-table-column
        prop="timezone"
        label="用户时区"
        min-width="160"
      />
      <el-table-column
        prop="last_login_at"
        label="最近登录时间（UTC+8）"
        min-width="220"
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
            @click="openUser(scope.row)"
          >
            管理
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <PaginationBar
      v-model:page="page"
      v-model:page-size="pageSize"
      :total="total"
      @update:page="load"
      @update:page-size="load"
    />

    <el-drawer
      v-model="drawerOpen"
      title="用户管理详情"
      size="720px"
    >
      <template v-if="selected">
        <div class="summary-grid">
          <div><small>用户编号</small><strong>{{ selected.id }}</strong></div>
          <div><small>账户状态</small><strong>{{ localizeAdminValue(selected.status, "status") }}</strong></div>
          <div><small>活跃会话</small><strong>{{ selected.active_sessions }}</strong></div>
          <div><small>失败登录次数</small><strong>{{ selected.failed_login_count }}</strong></div>
        </div>

        <el-form
          label-position="top"
          class="edit-form"
        >
          <el-form-item label="邮箱">
            <el-input
              v-model="form.email"
              :disabled="!canUpdate"
            />
          </el-form-item>
          <el-form-item label="首选语言">
            <el-select
              v-model="form.preferred_locale"
              :disabled="!canUpdate"
            >
              <el-option
                label="简体中文"
                value="zh-CN"
              /><el-option
                label="繁体中文"
                value="zh-TW"
              /><el-option
                label="英文"
                value="en"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="用户时区">
            <el-input
              v-model="form.timezone"
              :disabled="!canUpdate"
              placeholder="Asia/Shanghai"
            />
          </el-form-item>
          <el-form-item label="操作原因（至少 10 个字符）">
            <el-input
              v-model="form.reason"
              type="textarea"
              :rows="3"
            />
          </el-form-item>
          <el-button
            v-if="canUpdate"
            type="primary"
            :loading="saving"
            @click="saveUser"
          >
            保存资料
          </el-button>
        </el-form>

        <div class="danger-actions">
          <el-button
            v-if="canSuspend && selected.status === 'active'"
            type="warning"
            @click="userAction('suspend')"
          >
            封禁
          </el-button>
          <el-button
            v-if="canRestore && ['suspended','locked','deletion_pending'].includes(selected.status)"
            type="success"
            @click="userAction('restore')"
          >
            解封/恢复
          </el-button>
          <el-button
            v-if="canRevokeSessions && selected.active_sessions"
            @click="userAction('sessions/revoke')"
          >
            撤销全部会话
          </el-button>
          <el-button
            v-if="canUpdate && !['deletion_pending','deleted'].includes(selected.status)"
            type="danger"
            @click="userAction('deactivate')"
          >
            注销账户
          </el-button>
        </div>
        <p class="boundary">
          注销采用软停用并进入隐私删除流程，不直接物理删除业务、支付或审计记录。
        </p>

        <h3>当前角色</h3>
        <el-tag
          v-for="role in selected.roles"
          :key="role.code"
        >
          {{ role.name }}（{{ role.code }}）
        </el-tag>

        <h3>操作历史</h3>
        <el-table
          :data="history"
          size="small"
          empty-text="暂无历史记录"
        >
          <el-table-column
            prop="event_type"
            label="事件类型"
            min-width="190"
          >
            <template #default="scope">
              {{ localizeAdminValue(scope.row.event_type, "event_type") }}
            </template>
          </el-table-column>
          <el-table-column
            prop="reason"
            label="操作原因"
            min-width="220"
          />
          <el-table-column
            prop="actor_type"
            label="操作者类型"
            min-width="120"
          >
            <template #default="scope">
              {{ localizeAdminValue(scope.row.actor_type, "actor_type") }}
            </template>
          </el-table-column>
          <el-table-column
            prop="occurred_at"
            label="发生时间（UTC+8）"
            min-width="220"
            :formatter="formatAdminTableCell"
          />
        </el-table>
      </template>
    </el-drawer>
  </section>
</template>

<style scoped>
.module-heading,.filters,.danger-actions{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}.filters{justify-content:flex-start;margin:18px 0}.filters .el-input{max-width:320px}.filters .el-select{width:180px}.summary-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-bottom:20px}.summary-grid div{display:grid;gap:5px;padding:14px;border:1px solid var(--el-border-color);border-radius:8px}.summary-grid strong{overflow-wrap:anywhere}.edit-form{margin:20px 0}.danger-actions{justify-content:flex-start;padding:16px 0;border-top:1px solid var(--el-border-color)}.boundary{color:var(--el-text-color-secondary)}h3{margin-top:24px}@media(max-width:720px){.summary-grid{grid-template-columns:1fr}}
</style>
