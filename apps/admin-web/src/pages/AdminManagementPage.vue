<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { formatAdminTableCell, localizeAdminValue } from "@vav/ui-admin";

import { catalogApi } from "@/features/catalog/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

type Role = { id: string; code: string; name: string; is_system: boolean; is_active: boolean };
type UserRole = { code: string; name: string; granted_at: string; expires_at?: string | null };
type Admin = {
  id: string;
  email: string;
  status: string;
  preferred_locale: string;
  timezone: string;
  active_sessions: number;
  roles: UserRole[];
  last_login_at?: string | null;
  updated_at: string;
  version: number;
};
type Invitation = {
  id: string;
  email: string;
  role_codes: string[];
  status: string;
  reason: string;
  created_at: string;
  expires_at: string;
  accepted_at?: string | null;
  revoked_at?: string | null;
};
type AuditEvent = {
  id: string;
  event_type: string;
  reason?: string | null;
  actor_user_id?: string | null;
  occurred_at: string;
};

const auth = useAdminAuthStore();
const route = useRoute();
const admins = ref<Admin[]>([]);
const roles = ref<Role[]>([]);
const invitations = ref<Invitation[]>([]);
const selected = ref<Admin>();
const history = ref<AuditEvent[]>([]);
const drawerOpen = ref(false);
const inviteOpen = ref(false);
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const notice = ref("");
const tab = ref(route.name === "admin-access-invitations" ? "invitations" : "admins");
const actionReason = ref("");
const selectedRole = ref("");
const profileForm = ref({ email: "", preferred_locale: "zh-CN", timezone: "Asia/Shanghai" });
const inviteForm = ref({ email: "", role_codes: [] as string[], reason: "" });

const canInvite = computed(() => auth.hasPermission("admins.invite"));
const canReadRoles = computed(() => auth.hasPermission("roles.read"));
const canReadUsers = computed(() => auth.hasPermission("users.read"));
const canDisable = computed(() => auth.hasPermission("admins.disable"));
const canRestore = computed(() => auth.hasPermission("admins.restore"));
const canAssignRole = computed(() => auth.hasPermission("roles.assign"));
const canRevokeRole = computed(() => auth.hasPermission("roles.revoke"));
const canUpdateProfile = computed(() => auth.hasPermission("users.update"));
const availableRoles = computed(() => roles.value.filter((role) => role.is_active));

async function load() {
  loading.value = true;
  error.value = "";
  try {
    await auth.bootstrap();
    const [adminResult, roleResult, invitationResult] = await Promise.all([
      catalogApi<{ items: Admin[] }>("/admin/admins?page_size=100"),
      canReadRoles.value
        ? catalogApi<{ items: Role[] }>("/admin/roles")
        : Promise.resolve({ items: [] as Role[] }),
      catalogApi<{ items: Invitation[] }>("/admin/admins/invitations?page_size=100"),
    ]);
    admins.value = adminResult.items;
    roles.value = roleResult.items;
    invitations.value = invitationResult.items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "管理员数据加载失败";
  } finally {
    loading.value = false;
  }
}

async function openAdmin(admin: Admin) {
  try {
    const [detail, events] = await Promise.all([
      canReadUsers.value ? catalogApi<Admin>(`/admin/users/${admin.id}`) : Promise.resolve(admin),
      canReadUsers.value
        ? catalogApi<{ items: AuditEvent[] }>(`/admin/users/${admin.id}/history?page_size=100`)
        : Promise.resolve({ items: [] as AuditEvent[] }),
    ]);
    selected.value = detail;
    history.value = events.items;
    selectedRole.value = "";
    actionReason.value = "";
    profileForm.value = {
      email: detail.email,
      preferred_locale: detail.preferred_locale,
      timezone: detail.timezone,
    };
    drawerOpen.value = true;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "管理员详情加载失败";
  }
}

function validReason(value = actionReason.value) {
  if (value.trim().length >= 10) return true;
  error.value = "请填写至少 10 个字符的操作原因，原因会写入安全审计。";
  return false;
}

async function refreshSelected() {
  const current = selected.value;
  await load();
  const latest = admins.value.find((item) => item.id === current?.id);
  if (latest) await openAdmin(latest);
  else drawerOpen.value = false;
}

async function saveProfile() {
  if (!selected.value || !validReason()) return;
  saving.value = true;
  try {
    await catalogApi(`/admin/users/${selected.value.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        ...profileForm.value,
        expected_version: selected.value.version,
        reason: actionReason.value.trim(),
      }),
    });
    notice.value = "管理员基本资料已更新。";
    await refreshSelected();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "管理员资料更新失败";
  } finally {
    saving.value = false;
  }
}

async function changeAdminStatus(action: "disable" | "restore") {
  if (!selected.value || !validReason()) return;
  const label = action === "disable" ? "停用" : "恢复";
  if (!window.confirm(`确认${label}该管理员？现有登录会话将被撤销。`)) return;
  saving.value = true;
  try {
    await catalogApi(`/admin/admins/${selected.value.id}/${action}`, {
      method: "POST",
      body: JSON.stringify({ reason: actionReason.value.trim() }),
    });
    notice.value = `管理员已${label}。`;
    await refreshSelected();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : `管理员${label}失败`;
  } finally {
    saving.value = false;
  }
}

async function assignRole() {
  if (!selected.value || !selectedRole.value || !validReason()) return;
  saving.value = true;
  try {
    await catalogApi(`/admin/users/${selected.value.id}/roles`, {
      method: "POST",
      body: JSON.stringify({ role_code: selectedRole.value, reason: actionReason.value.trim() }),
    });
    notice.value = "角色已分配，并刷新管理员权限版本。";
    await refreshSelected();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "角色分配失败";
  } finally {
    saving.value = false;
  }
}

async function revokeRole(role: UserRole) {
  if (!selected.value || !validReason()) return;
  if (!window.confirm(`确认撤销角色“${role.name}”？最后一名超级管理员受后端保护。`)) return;
  saving.value = true;
  try {
    await catalogApi(`/admin/users/${selected.value.id}/roles/${encodeURIComponent(role.code)}`, {
      method: "DELETE",
      body: JSON.stringify({ reason: actionReason.value.trim() }),
    });
    notice.value = "角色已撤销，并记录权限审计。";
    await refreshSelected();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "角色撤销失败";
  } finally {
    saving.value = false;
  }
}

async function inviteAdmin() {
  if (inviteForm.value.reason.trim().length < 10 || !inviteForm.value.email || inviteForm.value.role_codes.length === 0) {
    error.value = "请填写邮箱、至少一个角色，以及不少于 10 个字符的邀请原因。";
    return;
  }
  saving.value = true;
  try {
    await catalogApi("/admin/admins/invitations", {
      method: "POST",
      body: JSON.stringify(inviteForm.value),
    });
    inviteOpen.value = false;
    notice.value = "管理员邀请已发送，有效期为 48 小时。";
    inviteForm.value = { email: "", role_codes: [], reason: "" };
    await load();
    tab.value = "invitations";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "管理员邀请失败";
  } finally {
    saving.value = false;
  }
}

async function revokeInvitation(invitation: Invitation) {
  if (!validReason() || !window.confirm("确认撤销该管理员邀请？原邀请链接将立即失效。")) return;
  saving.value = true;
  try {
    await catalogApi(`/admin/admins/invitations/${invitation.id}/revoke`, {
      method: "POST",
      body: JSON.stringify({ reason: actionReason.value.trim() }),
    });
    notice.value = "管理员邀请已撤销。";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "邀请撤销失败";
  } finally {
    saving.value = false;
  }
}

onMounted(() => void load());
</script>

<template>
  <section class="admin-module admin-accounts">
    <header class="module-heading">
      <div>
        <p class="admin-kicker">
          管理员访问控制闭环
        </p>
        <h2>管理员</h2>
        <p>通过邀请新增管理员，编辑基本资料与角色，支持停用、恢复及完整审计；不提供物理删除。</p>
      </div>
      <div>
        <el-button
          :loading="loading"
          @click="load"
        >
          刷新
        </el-button>
        <el-button
          v-if="canInvite"
          type="primary"
          @click="inviteOpen = true"
        >
          邀请管理员
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
    <el-input
      v-model="actionReason"
      placeholder="本次停用、恢复、角色变更或撤销邀请的原因（至少 10 个字符）"
    />

    <el-tabs v-model="tab">
      <el-tab-pane
        label="管理员账户"
        name="admins"
      >
        <el-table
          v-loading="loading"
          :data="admins"
          stripe
          empty-text="暂无管理员"
        >
          <el-table-column
            prop="email"
            label="管理员邮箱"
            min-width="230"
          />
          <el-table-column
            prop="status"
            label="账户状态"
            min-width="120"
          >
            <template #default="scope">
              {{ localizeAdminValue(scope.row.status, "status") }}
            </template>
          </el-table-column>
          <el-table-column
            label="当前角色"
            min-width="240"
          >
            <template #default="scope">
              {{ scope.row.roles.map((role: UserRole) => role.name).join("、") || "未分配" }}
            </template>
          </el-table-column>
          <el-table-column
            prop="active_sessions"
            label="有效会话数"
            width="120"
          />
          <el-table-column
            prop="last_login_at"
            label="最近登录时间（UTC+8）"
            min-width="210"
            :formatter="formatAdminTableCell"
          />
          <el-table-column
            label="操作"
            fixed="right"
            width="100"
          >
            <template #default="scope">
              <el-button
                type="primary"
                size="small"
                @click="openAdmin(scope.row)"
              >
                管理
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane
        label="邀请记录"
        name="invitations"
      >
        <el-table
          :data="invitations"
          stripe
          empty-text="暂无邀请记录"
        >
          <el-table-column
            prop="email"
            label="受邀邮箱"
            min-width="210"
          />
          <el-table-column
            label="拟分配角色"
            min-width="220"
          >
            <template #default="scope">
              {{ scope.row.role_codes.join("、") }}
            </template>
          </el-table-column>
          <el-table-column
            prop="status"
            label="邀请状态"
            min-width="120"
          >
            <template #default="scope">
              {{ localizeAdminValue(scope.row.status, "status") }}
            </template>
          </el-table-column>
          <el-table-column
            prop="expires_at"
            label="到期时间（UTC+8）"
            min-width="210"
            :formatter="formatAdminTableCell"
          />
          <el-table-column
            label="操作"
            width="100"
          >
            <template #default="scope">
              <el-button
                v-if="canInvite && scope.row.status === 'pending'"
                type="danger"
                size="small"
                @click="revokeInvitation(scope.row)"
              >
                撤销
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-drawer
      v-model="drawerOpen"
      title="管理员编辑与审计"
      size="820px"
    >
      <template v-if="selected">
        <el-form label-position="top">
          <div class="profile-grid">
            <el-form-item label="邮箱">
              <el-input
                v-model="profileForm.email"
                :disabled="!canUpdateProfile"
              />
            </el-form-item>
            <el-form-item label="界面语言">
              <el-select
                v-model="profileForm.preferred_locale"
                :disabled="!canUpdateProfile"
              >
                <el-option
                  label="简体中文"
                  value="zh-CN"
                />
                <el-option
                  label="繁体中文"
                  value="zh-TW"
                />
                <el-option
                  label="英文"
                  value="en"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="时区">
              <el-input
                v-model="profileForm.timezone"
                :disabled="!canUpdateProfile"
              />
            </el-form-item>
          </div>
          <el-button
            v-if="canUpdateProfile"
            type="primary"
            :loading="saving"
            @click="saveProfile"
          >
            保存基本资料
          </el-button>
        </el-form>

        <el-divider content-position="left">
          角色分配
        </el-divider>
        <div class="role-list">
          <el-tag
            v-for="role in selected.roles"
            :key="role.code"
            :closable="canRevokeRole"
            :disable-transitions="true"
            @close="canRevokeRole && revokeRole(role)"
          >
            {{ role.name }}
          </el-tag>
          <span v-if="selected.roles.length === 0">未分配角色</span>
        </div>
        <div
          v-if="canAssignRole"
          class="role-assign"
        >
          <el-select
            v-model="selectedRole"
            placeholder="选择要分配的角色"
          >
            <el-option
              v-for="role in availableRoles"
              :key="role.code"
              :label="role.name"
              :value="role.code"
            />
          </el-select>
          <el-button
            type="primary"
            :loading="saving"
            @click="assignRole"
          >
            分配角色
          </el-button>
        </div>

        <el-divider content-position="left">
          账户状态
        </el-divider>
        <el-button
          v-if="canDisable && selected.status === 'active'"
          type="danger"
          @click="changeAdminStatus('disable')"
        >
          停用管理员
        </el-button>
        <el-button
          v-if="canRestore && selected.status !== 'active'"
          type="success"
          @click="changeAdminStatus('restore')"
        >
          恢复管理员
        </el-button>
        <p class="safety-note">
          管理员不支持物理删除；停用会撤销其会话，并保留角色与审计证据。
        </p>

        <el-divider content-position="left">
          变更审计
        </el-divider>
        <el-table
          :data="history"
          empty-text="暂无审计记录"
          size="small"
        >
          <el-table-column
            prop="event_type"
            label="事件类型"
            min-width="200"
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
            prop="occurred_at"
            label="发生时间（UTC+8）"
            min-width="210"
            :formatter="formatAdminTableCell"
          />
        </el-table>
      </template>
    </el-drawer>

    <el-dialog
      v-model="inviteOpen"
      title="邀请管理员"
      width="620px"
    >
      <el-form label-position="top">
        <el-form-item label="管理员邮箱">
          <el-input v-model="inviteForm.email" />
        </el-form-item>
        <el-form-item label="初始角色">
          <el-select
            v-model="inviteForm.role_codes"
            multiple
            placeholder="至少选择一个角色"
          >
            <el-option
              v-for="role in availableRoles"
              :key="role.code"
              :label="role.name"
              :value="role.code"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="邀请原因（至少 10 个字符）">
          <el-input
            v-model="inviteForm.reason"
            type="textarea"
            :rows="3"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="inviteOpen = false">
          取消
        </el-button>
        <el-button
          type="primary"
          :loading="saving"
          @click="inviteAdmin"
        >
          发送邀请
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.admin-accounts { display: grid; gap: 18px; }
.module-heading, .role-assign { display: flex; justify-content: space-between; gap: 14px; align-items: flex-start; }
.module-heading h2 { margin: 0; }
.module-heading p { margin: 6px 0 0; color: var(--el-text-color-secondary); }
.admin-kicker { color: var(--el-color-primary) !important; font-weight: 700; }
.profile-grid { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 12px; }
.role-list { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.role-assign { justify-content: flex-start; }
.role-assign .el-select { width: 320px; }
.safety-note { color: var(--el-text-color-secondary); }
@media (max-width: 760px) { .module-heading, .role-assign { flex-direction: column; } .profile-grid { grid-template-columns: 1fr; } }
</style>
