<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { formatAdminDate, formatAdminTableCell, localizeAdminValue } from "@vav/ui-admin";

import { catalogApi } from "@/features/catalog/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

type SettingValue = Record<string, unknown> | unknown[] | string | boolean | null;
type Setting = {
  setting_key: string;
  value: SettingValue;
  value_type: "string" | "nullable_string" | "boolean" | "array" | "object" | "decision_status";
  is_public: boolean;
  group: string;
  updated_by: string;
  updated_at: string;
};
type Draft = { text: string; booleanValue: boolean; is_public: boolean; reason: string };
type Revision = {
  id: string;
  event_type: string;
  actor_user_id?: string | null;
  reason?: string | null;
  before_state?: Record<string, unknown> | null;
  after_state?: Record<string, unknown> | null;
  occurred_at: string;
  can_rollback: boolean;
};

const auth = useAdminAuthStore();
const settings = ref<Setting[]>([]);
const drafts = ref<Record<string, Draft>>({});
const loading = ref(false);
const savingKey = ref("");
const error = ref("");
const notice = ref("");
const historyOpen = ref(false);
const historySetting = ref<Setting>();
const revisions = ref<Revision[]>([]);
const rollbackReason = ref("");

const canManage = computed(() => auth.hasPermission("content.settings.manage"));
const groups = computed(() => {
  const values = new Map<string, Setting[]>();
  for (const setting of settings.value) {
    const group = setting.group || "other";
    values.set(group, [...(values.get(group) ?? []), setting]);
  }
  return [...values.entries()];
});

const settingLabels: Record<string, string> = {
  "site.name": "网站名称",
  "site.default_locale": "默认语言",
  "site.supported_locales": "支持的语言",
  "site.contact_email": "联系邮箱",
  "site.registration_enabled": "允许用户注册",
  "site.maintenance_mode": "维护模式",
  "site.launch_language_decision": "首发语言决策状态",
};
const groupLabels: Record<string, string> = { site: "站点基础设置", other: "其他设置" };
const typeLabels: Record<Setting["value_type"], string> = {
  string: "文本",
  nullable_string: "可留空文本",
  boolean: "开关",
  array: "列表（JSON）",
  object: "对象（JSON）",
  decision_status: "决策状态",
};

function makeDraft(setting: Setting): Draft {
  return {
    text: typeof setting.value === "string" || setting.value === null
      ? (setting.value ?? "") as string
      : JSON.stringify(setting.value, null, 2),
    booleanValue: setting.value === true,
    is_public: setting.is_public,
    reason: "",
  };
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const result = await catalogApi<{ items: Setting[] }>("/admin/site-settings");
    settings.value = result.items;
    drafts.value = Object.fromEntries(result.items.map((item) => [item.setting_key, makeDraft(item)]));
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "网站设置加载失败";
  } finally {
    loading.value = false;
  }
}

function parseValue(setting: Setting): SettingValue {
  const draft = drafts.value[setting.setting_key];
  if (!draft) throw new Error("设置草稿不存在，请刷新后重试。 ");
  if (setting.value_type === "boolean") return draft.booleanValue;
  if (setting.value_type === "nullable_string") return draft.text.trim() || null;
  if (setting.value_type === "string" || setting.value_type === "decision_status") {
    if (!draft.text.trim()) throw new Error("该设置不能为空。 ");
    return draft.text.trim();
  }
  let value: unknown;
  try {
    value = JSON.parse(draft.text);
  } catch {
    throw new Error("JSON 格式无效，请检查逗号、引号和括号。 ");
  }
  if (setting.value_type === "array" && !Array.isArray(value)) throw new Error("该设置必须是 JSON 列表。 ");
  if (setting.value_type === "object" && (!value || Array.isArray(value) || typeof value !== "object")) {
    throw new Error("该设置必须是 JSON 对象。 ");
  }
  return value as SettingValue;
}

function validateBusinessRule(setting: Setting, value: SettingValue) {
  if (setting.setting_key === "site.contact_email" && typeof value === "string") {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/u.test(value)) throw new Error("联系邮箱格式不正确。 ");
  }
  if (setting.setting_key === "site.supported_locales") {
    if (!Array.isArray(value) || value.length === 0 || value.some((item) => typeof item !== "string")) {
      throw new Error("支持的语言必须是至少包含一项的字符串列表。 ");
    }
  }
  if (setting.setting_key === "site.default_locale") {
    const supported = settings.value.find((item) => item.setting_key === "site.supported_locales");
    const supportedValue = supported ? parseValue(supported) : [];
    if (!Array.isArray(supportedValue) || !supportedValue.includes(value)) {
      throw new Error("默认语言必须包含在“支持的语言”列表中。 ");
    }
  }
}

async function save(setting: Setting) {
  const draft = drafts.value[setting.setting_key];
  if (!draft || draft.reason.trim().length < 10) {
    error.value = "请填写至少 10 个字符的保存原因，供审计和回滚使用。";
    return;
  }
  try {
    const value = parseValue(setting);
    validateBusinessRule(setting, value);
    savingKey.value = setting.setting_key;
    error.value = "";
    await catalogApi(`/admin/site-settings/${encodeURIComponent(setting.setting_key)}`, {
      method: "PUT",
      body: JSON.stringify({
        value,
        value_type: setting.value_type,
        is_public: draft.is_public,
        expected_updated_at: setting.updated_at,
        reason: draft.reason.trim(),
      }),
    });
    notice.value = `${settingLabels[setting.setting_key] ?? setting.setting_key}已保存，并生成可回滚审计版本。`;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "网站设置保存失败";
  } finally {
    savingKey.value = "";
  }
}

async function openHistory(setting: Setting) {
  historySetting.value = setting;
  rollbackReason.value = "";
  try {
    const result = await catalogApi<{ items: Revision[] }>(
      `/admin/site-settings/${encodeURIComponent(setting.setting_key)}/history`,
    );
    revisions.value = result.items;
    historyOpen.value = true;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "设置历史加载失败";
  }
}

async function rollback(revision: Revision) {
  const setting = historySetting.value;
  if (!setting || rollbackReason.value.trim().length < 10) {
    error.value = "请填写至少 10 个字符的回滚原因。";
    return;
  }
  if (!window.confirm("确认回滚到该次变更之前的值？当前值仍会保留在审计历史中。")) return;
  savingKey.value = setting.setting_key;
  try {
    await catalogApi(`/admin/site-settings/${encodeURIComponent(setting.setting_key)}/rollback`, {
      method: "POST",
      body: JSON.stringify({
        audit_event_id: revision.id,
        expected_updated_at: setting.updated_at,
        reason: rollbackReason.value.trim(),
      }),
    });
    historyOpen.value = false;
    notice.value = "设置已回滚，并记录新的审计事件。";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "设置回滚失败";
  } finally {
    savingKey.value = "";
  }
}

onMounted(() => void load());
</script>

<template>
  <section class="admin-module settings-admin">
    <header class="module-heading">
      <div>
        <p class="admin-kicker">
          可验证配置工作台
        </p>
        <h2>网站设置</h2>
        <p>按业务分组编辑，保存前执行类型与业务校验；每次变更均可审计和回滚。</p>
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

    <el-collapse
      v-loading="loading"
      :model-value="groups.map(([group]) => group)"
    >
      <el-collapse-item
        v-for="[group, items] in groups"
        :key="group"
        :name="group"
        :title="groupLabels[group] ?? group"
      >
        <article
          v-for="setting in items"
          :key="setting.setting_key"
          class="setting-card"
        >
          <div class="setting-title">
            <div>
              <h3>{{ settingLabels[setting.setting_key] ?? setting.setting_key }}</h3>
              <p>{{ setting.setting_key }} · {{ typeLabels[setting.value_type] }}</p>
            </div>
            <el-tag :type="drafts[setting.setting_key]?.is_public ? 'success' : 'info'">
              {{ drafts[setting.setting_key]?.is_public ? "公开配置" : "内部配置" }}
            </el-tag>
          </div>

          <el-form label-position="top">
            <el-form-item label="设置值">
              <el-switch
                v-if="setting.value_type === 'boolean'"
                v-model="drafts[setting.setting_key].booleanValue"
                active-text="启用"
                inactive-text="停用"
                :disabled="!canManage"
              />
              <el-input
                v-else-if="['array','object'].includes(setting.value_type)"
                v-model="drafts[setting.setting_key].text"
                type="textarea"
                :rows="5"
                :disabled="!canManage"
              />
              <el-input
                v-else
                v-model="drafts[setting.setting_key].text"
                clearable
                :disabled="!canManage"
              />
            </el-form-item>
            <div class="setting-options">
              <el-checkbox
                v-model="drafts[setting.setting_key].is_public"
                :disabled="!canManage"
              >
                允许公开接口读取
              </el-checkbox>
              <span>上次更新：{{ formatAdminDate(setting.updated_at) }}</span>
            </div>
            <el-form-item
              v-if="canManage"
              label="保存原因（至少 10 个字符）"
            >
              <el-input
                v-model="drafts[setting.setting_key].reason"
                placeholder="说明本次修改目的、影响范围或关联工单"
              />
            </el-form-item>
            <div class="setting-actions">
              <el-button @click="openHistory(setting)">
                查看历史与回滚
              </el-button>
              <el-button
                v-if="canManage"
                type="primary"
                :loading="savingKey === setting.setting_key"
                @click="save(setting)"
              >
                校验并保存
              </el-button>
            </div>
          </el-form>
        </article>
      </el-collapse-item>
    </el-collapse>

    <el-drawer
      v-model="historyOpen"
      title="设置历史与回滚"
      size="760px"
    >
      <p v-if="historySetting">
        {{ settingLabels[historySetting.setting_key] ?? historySetting.setting_key }}
      </p>
      <el-input
        v-if="canManage"
        v-model="rollbackReason"
        class="rollback-reason"
        placeholder="回滚原因（至少 10 个字符）"
      />
      <el-table
        :data="revisions"
        empty-text="暂无可用历史"
      >
        <el-table-column
          prop="event_type"
          label="变更类型"
          min-width="160"
        >
          <template #default="scope">
            {{ localizeAdminValue(scope.row.event_type, "event_type") }}
          </template>
        </el-table-column>
        <el-table-column
          prop="reason"
          label="变更原因"
          min-width="220"
        />
        <el-table-column
          prop="occurred_at"
          label="发生时间（UTC+8）"
          min-width="210"
          :formatter="formatAdminTableCell"
        />
        <el-table-column
          label="操作"
          width="110"
        >
          <template #default="scope">
            <el-button
              v-if="canManage && scope.row.can_rollback"
              type="warning"
              size="small"
              @click="rollback(scope.row)"
            >
              回滚
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-drawer>
  </section>
</template>

<style scoped>
.settings-admin { display: grid; gap: 18px; }
.module-heading, .setting-title, .setting-options, .setting-actions { display: flex; justify-content: space-between; gap: 16px; }
.module-heading { align-items: flex-start; }
.module-heading h2, .setting-title h3 { margin: 0; }
.module-heading p, .setting-title p { margin: 6px 0 0; color: var(--el-text-color-secondary); }
.admin-kicker { color: var(--el-color-primary) !important; font-weight: 700; }
.setting-card { padding: 20px; margin-bottom: 14px; border: 1px solid var(--el-border-color-light); border-radius: 12px; background: var(--el-bg-color); }
.setting-title { align-items: flex-start; margin-bottom: 16px; }
.setting-options { align-items: center; margin-bottom: 14px; color: var(--el-text-color-secondary); font-size: 13px; }
.setting-actions { justify-content: flex-end; }
.rollback-reason { margin: 12px 0 18px; }
@media (max-width: 760px) { .module-heading, .setting-title, .setting-options { flex-direction: column; } }
</style>
