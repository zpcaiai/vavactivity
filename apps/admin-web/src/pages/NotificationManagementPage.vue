<script lang="ts">
export type TemplateReleaseStatus =
  | "draft"
  | "in_review"
  | "approved"
  | "active"
  | "superseded"
  | "revoked";

export type TemplateReleaseAction =
  | "submit-review"
  | "approve"
  | "activate"
  | "rollback"
  | "revoke"
  | "preview"
  | "test-send";

type TemplateReleaseActionPolicy = {
  action: TemplateReleaseAction;
  label: string;
  statuses: readonly TemplateReleaseStatus[] | "all";
  permission?: string;
  type?: "success" | "danger";
};

export const TEMPLATE_RELEASE_ACTION_POLICY: readonly TemplateReleaseActionPolicy[] = [
  {
    action: "submit-review",
    label: "送审",
    statuses: ["draft"],
    permission: "notifications.templates.update"
  },
  {
    action: "approve",
    label: "批准",
    statuses: ["in_review"],
    permission: "notifications.templates.approve"
  },
  {
    action: "activate",
    label: "激活",
    statuses: ["approved"],
    permission: "notifications.templates.activate",
    type: "success"
  },
  {
    action: "rollback",
    label: "回滚",
    statuses: ["approved", "superseded"],
    permission: "notifications.templates.rollback",
    type: "danger"
  },
  {
    action: "revoke",
    label: "撤销",
    statuses: ["active", "superseded"],
    permission: "notifications.templates.rollback"
  },
  { action: "preview", label: "预览", statuses: "all" },
  {
    action: "test-send",
    label: "测试发送",
    statuses: "all",
    permission: "notifications.templates.test_send"
  }
];

export function getTemplateReleaseActions(
  status: string,
  hasPermission: (permission: string) => boolean
) {
  return TEMPLATE_RELEASE_ACTION_POLICY.filter((policy) =>
    (policy.statuses === "all" || policy.statuses.includes(status as TemplateReleaseStatus))
    && (!policy.permission || hasPermission(policy.permission))
  );
}
</script>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { formatAdminTableCell } from "@vav/ui-admin";

import { catalogApi } from "@/features/catalog/api";
import { useAdminAuthStore } from "@/stores/admin-auth";

type Dashboard = {
  deliveries: Record<string, number>;
  in_app_unread: number;
  dead_letters_open: number;
  active_suppressions: number;
  campaigns: Record<string, number>;
  provider_status: string;
};
type Template = { id: string; template_code: string; internal_name: string; category: string; purpose: string; status?: string; release_count: number; active_count: number };
type TemplateRelease = { id: string; semantic_version: string; locale: string; channel: string; status: TemplateReleaseStatus; checksum_sha256?: string; created_at: string; approved_at?: string | null; activated_at?: string | null };
type TemplateDetail = { definition: Record<string, unknown>; releases: TemplateRelease[] };
type RenderedPreview = Record<string, unknown>;
type Subscription = { id: string; subscription_code: string; source_event_type: string; source_event_version: number; template_code: string; recipient_resolver_code: string; status: string };
type Delivery = { id: string; notification_type: string; user_anonymous_id: string; channel: string; locale: string; status: string; provider?: string; attempt_count: number; created_at: string };
type DeadLetter = { id: string; source_type: string; failure_stage: string; error_code: string; status: string; created_at: string };
type Reminder = { id: string; reminder_type: string; subject_type: string; category: string; trigger_at: string; status: string };
type Campaign = { id: string; campaign_code: string; internal_name: string; campaign_type: string; category: string; status: string; created_by: string; approved_by?: string | null };
type Suppression = { id: string; destination_anonymous_hash: string; channel: string; suppression_reason: string; source: string; status: string; created_at: string };
type ProviderEvent = { id: string; provider: string; provider_event_id: string; event_type: string; signature_verified: boolean; processing_status: string; received_at: string };
type AuditEvent = { id: string; event_type: string; subject_type: string; reason?: string | null; created_at: string };

const dashboard = ref<Dashboard>();
const route = useRoute();
const auth = useAdminAuthStore();
const templates = ref<Template[]>([]);
const subscriptions = ref<Subscription[]>([]);
const deliveries = ref<Delivery[]>([]);
const deadLetters = ref<DeadLetter[]>([]);
const reminders = ref<Reminder[]>([]);
const campaigns = ref<Campaign[]>([]);
const suppressions = ref<Suppression[]>([]);
const providerEvents = ref<ProviderEvent[]>([]);
const audits = ref<AuditEvent[]>([]);
const activeTab = ref("dashboard");

/** Navigation section key → the tab pane that actually renders it. */
const SECTION_TO_TAB: Record<string, string> = {
  "template-releases": "templates",
  "event-subscriptions": "subscriptions",
  "dead-letters": "deadletters",
  "provider-events": "providers",
  suppressions: "providers"
};
const reason = ref("Batch 11 governed notification operation.");
const busy = ref(false);
const error = ref("");
const notice = ref("");
const newCampaign = ref({
  campaign_code: "",
  internal_name: "",
  campaign_type: "educational_newsletter",
  category: "marketing",
  template_code: "marketing-newsletter",
  locale: "zh-CN"
});
const newSuppression = ref({ destination: "", reason: "admin_blocked" });

/**
 * Template publishing was the one thing this console could not do: the backend
 * has the whole definition -> release -> review -> activate -> rollback chain
 * plus preview and test-send, and none of it had a control. An active release
 * is immutable, so shipping a fix means cutting a new release, not editing.
 */
const NOTIFICATION_CATEGORIES = [
  "security", "account", "order", "payment", "subscription", "activity", "course",
  "counseling", "ai_assistant", "matchmaking", "moderation", "platform", "marketing"
];
const TEMPLATE_PURPOSES = [
  { value: "security", label: "安全" },
  { value: "transactional", label: "交易" },
  { value: "service", label: "服务" },
  { value: "marketing", label: "营销" }
];

const templateDrawer = ref(false);
const templateDetail = ref<TemplateDetail>();
const preview = ref<RenderedPreview>();
const templateDialog = ref({
  open: false,
  template_code: "",
  internal_name: "",
  category: "platform",
  purpose: "transactional",
  variable_schema: "{}",
  supported_channels: ["in_app"] as string[],
  required_channels: [] as string[]
});
const releaseDialog = ref({
  open: false,
  semantic_version: "",
  locale: "zh-CN",
  channel: "in_app",
  subject_template: "",
  title_template: "",
  body_text_template: "",
  body_html_template: "",
  action_label_template: "",
  action_url_template: ""
});
const previewDialog = ref({ open: false, release_id: "", variables: "{}", recipient: "", mode: "preview" as "preview" | "test-send" });

const canCreateTemplate = computed(() => auth.hasPermission("notifications.templates.create"));
const canUpdateTemplate = computed(() => auth.hasPermission("notifications.templates.update"));

function parseVariables(value: string, field: string) {
  try {
    const parsed = JSON.parse(value || "{}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
    throw new Error("not an object");
  } catch {
    error.value = `${field}必须是合法的 JSON 对象。`;
    return null;
  }
}

function requireTemplateReason() {
  if (reason.value.trim().length >= 8) return true;
  error.value = "请先在上方填写至少 8 个字符的操作原因。";
  return false;
}

async function openTemplate(row: Template) {
  error.value = "";
  preview.value = undefined;
  try {
    templateDetail.value = await catalogApi<TemplateDetail>(`/admin/notifications/templates/${row.id}`);
    templateDrawer.value = true;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "模板详情加载失败";
  }
}

async function refreshTemplate() {
  const id = String(templateDetail.value?.definition.id ?? "");
  if (!id) return;
  templateDetail.value = await catalogApi<TemplateDetail>(`/admin/notifications/templates/${id}`);
}

async function createTemplate() {
  const form = templateDialog.value;
  const schema = parseVariables(form.variable_schema, "变量结构");
  if (!schema) return;
  if (!form.template_code.trim() || form.internal_name.trim().length < 3) {
    error.value = "请填写模板代码与内部名称。";
    return;
  }
  if (!form.supported_channels.length) {
    error.value = "请至少选择一个支持的渠道。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await catalogApi("/admin/notifications/templates", {
      method: "POST",
      body: JSON.stringify({
        template_code: form.template_code.trim(),
        internal_name: form.internal_name.trim(),
        category: form.category,
        purpose: form.purpose,
        variable_schema: schema,
        supported_channels: form.supported_channels,
        required_channels: form.required_channels
      })
    });
    notice.value = "模板已创建；还需要新建版本并逐级审批后才会真正发信。";
    templateDialog.value.open = false;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "模板创建失败";
  } finally {
    busy.value = false;
  }
}

async function createRelease() {
  const form = releaseDialog.value;
  const templateId = String(templateDetail.value?.definition.id ?? "");
  if (!templateId) return;
  if (!/^\d+\.\d+\.\d+$/u.test(form.semantic_version.trim())) {
    error.value = "版本号必须形如 1.0.0。";
    return;
  }
  if (!form.body_text_template.trim()) {
    error.value = "纯文本正文是必填项：它是所有渠道的兜底内容。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await catalogApi(`/admin/notifications/templates/${templateId}/releases`, {
      method: "POST",
      body: JSON.stringify({
        semantic_version: form.semantic_version.trim(),
        locale: form.locale,
        channel: form.channel,
        subject_template: form.subject_template.trim() || null,
        title_template: form.title_template.trim() || null,
        body_text_template: form.body_text_template,
        body_html_template: form.body_html_template.trim() || null,
        action_label_template: form.action_label_template.trim() || null,
        action_url_template: form.action_url_template.trim() || null
      })
    });
    notice.value = "版本草稿已创建。";
    releaseDialog.value.open = false;
    await refreshTemplate();
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "版本创建失败";
  } finally {
    busy.value = false;
  }
}

async function releaseAction(item: TemplateRelease, action: "submit-review" | "approve" | "activate" | "revoke" | "rollback") {
  if (action === "rollback" && !requireTemplateReason()) return;
  const label = { "submit-review": "送审", approve: "批准", activate: "激活", revoke: "撤销", rollback: "回滚" }[action];
  if (["activate", "rollback", "revoke"].includes(action)
    && !window.confirm(`确认${label}版本 ${item.semantic_version}？该操作会立刻改变线上发信内容。`)) return;
  busy.value = true;
  error.value = "";
  try {
    await catalogApi(`/admin/notifications/template-releases/${item.id}/${action}`, {
      method: "POST",
      body: action === "rollback" ? JSON.stringify({ reason: reason.value.trim() }) : undefined
    });
    notice.value = `版本${label}已完成。`;
    await refreshTemplate();
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : `版本${label}失败`;
  } finally {
    busy.value = false;
  }
}

function templateReleaseActions(status: TemplateReleaseStatus) {
  return getTemplateReleaseActions(status, (permission) => auth.hasPermission(permission));
}

function runTemplateReleaseAction(item: TemplateRelease, action: TemplateReleaseAction) {
  if (action === "preview" || action === "test-send") {
    openPreview(item, action);
    return;
  }
  void releaseAction(item, action);
}

function openPreview(item: TemplateRelease, mode: "preview" | "test-send") {
  error.value = "";
  preview.value = undefined;
  previewDialog.value = { open: true, release_id: item.id, variables: "{}", recipient: "", mode };
}

async function runPreview() {
  const form = previewDialog.value;
  const variables = parseVariables(form.variables, "变量取值");
  if (!variables) return;
  busy.value = true;
  error.value = "";
  try {
    if (form.mode === "preview") {
      preview.value = await catalogApi<RenderedPreview>(
        `/admin/notifications/template-releases/${form.release_id}/preview`,
        { method: "POST", body: JSON.stringify({ variables }) }
      );
      notice.value = "预览已渲染；渲染结果不会发给任何人。";
    } else {
      await catalogApi(`/admin/notifications/template-releases/${form.release_id}/test-send`, {
        method: "POST",
        body: JSON.stringify({ variables, recipient: form.recipient.trim() || null })
      });
      notice.value = "测试发送已提交；只发给指定的测试收件人。";
      form.open = false;
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : form.mode === "preview" ? "预览失败" : "测试发送失败";
  } finally {
    busy.value = false;
  }
}

async function load() {
  busy.value = true;
  error.value = "";
  try {
    await auth.bootstrap();
    const [dashboardValue, templateValue, subscriptionValue, deliveryValue, deadValue, reminderValue, campaignValue, suppressionValue, providerValue, auditValue] = await Promise.all([
      auth.hasPermission("notifications.analytics.read") ? catalogApi<Dashboard>("/admin/notifications/dashboard") : Promise.resolve(undefined),
      auth.hasPermission("notifications.templates.read") ? catalogApi<{ items: Template[] }>("/admin/notifications/templates") : Promise.resolve({ items: [] }),
      auth.hasPermission("notifications.subscriptions.read") ? catalogApi<{ items: Subscription[] }>("/admin/notifications/event-subscriptions") : Promise.resolve({ items: [] }),
      auth.hasPermission("notifications.deliveries.read") ? catalogApi<{ items: Delivery[] }>("/admin/notifications/deliveries") : Promise.resolve({ items: [] }),
      auth.hasPermission("notifications.dead_letters.read") ? catalogApi<{ items: DeadLetter[] }>("/admin/notifications/dead-letters") : Promise.resolve({ items: [] }),
      auth.hasPermission("notifications.reminders.read") ? catalogApi<{ items: Reminder[] }>("/admin/notifications/reminders") : Promise.resolve({ items: [] }),
      auth.hasPermission("notifications.campaigns.read") ? catalogApi<{ items: Campaign[] }>("/admin/notifications/campaigns") : Promise.resolve({ items: [] }),
      auth.hasPermission("notifications.suppressions.read") ? catalogApi<{ items: Suppression[] }>("/admin/notifications/suppressions") : Promise.resolve({ items: [] }),
      auth.hasPermission("notifications.providers.read") ? catalogApi<{ items: ProviderEvent[] }>("/admin/notifications/provider-events") : Promise.resolve({ items: [] }),
      auth.hasPermission("notifications.audit.read") ? catalogApi<{ items: AuditEvent[] }>("/admin/notifications/audit") : Promise.resolve({ items: [] })
    ]);
    dashboard.value = dashboardValue;
    templates.value = templateValue.items;
    subscriptions.value = subscriptionValue.items;
    deliveries.value = deliveryValue.items;
    deadLetters.value = deadValue.items;
    reminders.value = reminderValue.items;
    campaigns.value = campaignValue.items;
    suppressions.value = suppressionValue.items;
    providerEvents.value = providerValue.items;
    audits.value = auditValue.items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "通知运营中心加载失败";
  } finally {
    busy.value = false;
  }
}

async function setSubscription(item: Subscription) {
  await catalogApi(`/admin/notifications/event-subscriptions/${item.id}`, {
    method: "PATCH",
    body: JSON.stringify({ status: item.status === "active" ? "disabled" : "active", reason: reason.value })
  });
  notice.value = "事件订阅状态已更新并记录审计。";
  await load();
}
async function retryDelivery(item: Delivery) {
  await catalogApi(`/admin/notifications/deliveries/${item.id}/retry`, { method: "POST", body: JSON.stringify({ reason: reason.value }) });
  notice.value = "Delivery 已进入重新校验队列。";
  await load();
}
async function resolveDeadLetter(item: DeadLetter) {
  await catalogApi(`/admin/notifications/dead-letters/${item.id}/resolve`, { method: "POST", body: JSON.stringify({ reason: reason.value }) });
  await load();
}
async function cancelReminder(item: Reminder) {
  await catalogApi(`/admin/notifications/reminders/${item.id}/cancel`, { method: "POST", body: JSON.stringify({ reason: reason.value }) });
  await load();
}
async function createCampaign() {
  await catalogApi("/admin/notifications/campaigns", {
    method: "POST",
    body: JSON.stringify({
      ...newCampaign.value,
      audience_definition: { locale: newCampaign.value.locale, marketing_consent: true },
      channel_policy: { required: ["in_app"], optional: ["email"] },
      rate_limit_per_minute: 500,
      batch_size: 100
    })
  });
  notice.value = "Campaign 草稿已创建；发送前仍需测试发送、独立审批和不可变受众快照。";
  await load();
}
async function campaignAction(item: Campaign, action: "test-send" | "submit-review" | "approve" | "audience" | "start" | "pause" | "cancel") {
  const body = action === "audience" ? undefined : JSON.stringify({ reason: reason.value, confirmation_code: ["start", "cancel"].includes(action) ? item.campaign_code : undefined });
  await catalogApi(`/admin/notifications/campaigns/${item.id}/${action}`, { method: "POST", body });
  await load();
}
async function createSuppression() {
  await catalogApi("/admin/notifications/suppressions", {
    method: "POST",
    body: JSON.stringify({ destination: newSuppression.value.destination, channel: "email", reason: newSuppression.value.reason, explanation: reason.value })
  });
  newSuppression.value.destination = "";
  await load();
}
async function liftSuppression(item: Suppression) {
  await catalogApi(`/admin/notifications/suppressions/${item.id}/lift`, { method: "POST", body: JSON.stringify({ reason: reason.value }) });
  await load();
}

onMounted(() => {
  if (typeof route.meta.notificationSection === "string") {
    // Several sections share a pane. Without this map the tab component gets a
    // name no pane declares and renders nothing, so those nav links opened a
    // blank page.
    activeTab.value = SECTION_TO_TAB[route.meta.notificationSection] ?? route.meta.notificationSection;
  }
  void load();
});
</script>

<template>
  <section class="admin-page notification-admin-page">
    <div class="page-heading">
      <div>
        <p class="admin-kicker">
          BATCH 11 · GOVERNED DELIVERY
        </p>
        <h2>通知运营中心</h2>
        <p>模板、事件订阅、发送、重试、提醒、群发、Provider 回执与抑制的统一审计视图。</p>
      </div>
      <el-button
        :loading="busy"
        @click="load"
      >
        刷新
      </el-button>
    </div>
    <el-alert
      title="默认不展示完整邮件正文；敏感正文查看需要独立权限和访问理由。营销群发不能绕过同意或抑制。"
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
    <el-input
      v-model="reason"
      class="operation-reason"
      aria-label="操作原因"
      placeholder="高风险操作原因（至少 8 个字符）"
    />

    <el-tabs v-model="activeTab">
      <el-tab-pane
        v-if="auth.hasPermission('notifications.analytics.read')"
        label="Dashboard"
        name="dashboard"
      >
        <div
          v-if="dashboard"
          class="metric-grid"
        >
          <el-card><strong>{{ dashboard.deliveries.pending ?? 0 }}</strong><span>待发送</span></el-card>
          <el-card><strong>{{ dashboard.deliveries.sent ?? 0 }}</strong><span>已发送</span></el-card>
          <el-card><strong>{{ dashboard.deliveries.delivered ?? 0 }}</strong><span>已送达</span></el-card>
          <el-card><strong>{{ dashboard.dead_letters_open }}</strong><span>Dead Letter</span></el-card>
          <el-card><strong>{{ dashboard.in_app_unread }}</strong><span>站内未读</span></el-card>
          <el-card><strong>{{ dashboard.active_suppressions }}</strong><span>有效抑制</span></el-card>
        </div>
        <p>Provider：{{ dashboard?.provider_status }}。本地统计是执行证据，不代表送达 SLA 或服务结果。</p>
      </el-tab-pane>
      <el-tab-pane
        v-if="auth.hasPermission('notifications.templates.read')"
        label="模板中心"
        name="templates"
      >
        <div class="inline-operation-form">
          <el-button
            v-if="canCreateTemplate"
            type="primary"
            @click="templateDialog.open = true"
          >
            新建模板
          </el-button>
        </div>
        <el-table :data="templates">
          <el-table-column
            prop="template_code"
            label="Template Code"
          /><el-table-column
            prop="category"
            label="分类"
          /><el-table-column
            prop="purpose"
            label="用途"
          /><el-table-column
            prop="active_count"
            label="Active Releases"
          /><el-table-column
            prop="release_count"
            label="版本数"
          /><el-table-column
            label="操作"
            width="140"
          >
            <template #default="scope">
              <el-button
                size="small"
                type="primary"
                link
                @click="openTemplate(scope.row)"
              >
                版本与发布
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <p>Release 激活后不可原地修改；支持 zh-CN、zh-TW、en、HTML 与 Plain Text 双正文。</p>
      </el-tab-pane>
      <el-tab-pane
        v-if="auth.hasPermission('notifications.subscriptions.read')"
        label="事件订阅"
        name="subscriptions"
      >
        <el-table :data="subscriptions">
          <el-table-column
            prop="source_event_type"
            label="事件"
          /><el-table-column
            prop="source_event_version"
            label="版本"
            width="80"
          /><el-table-column
            prop="recipient_resolver_code"
            label="收件人解析"
          /><el-table-column
            prop="template_code"
            label="模板"
          /><el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          /><el-table-column label="操作">
            <template #default="scope">
              <el-button
                size="small"
                @click="setSubscription(scope.row)"
              >
                {{ scope.row.status === 'active' ? '停用' : '启用' }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane
        v-if="auth.hasPermission('notifications.deliveries.read')"
        label="Delivery"
        name="deliveries"
      >
        <el-table :data="deliveries">
          <el-table-column
            prop="notification_type"
            label="通知类型"
          /><el-table-column
            prop="user_anonymous_id"
            label="匿名用户"
          /><el-table-column
            prop="channel"
            label="渠道"
          /><el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          /><el-table-column
            prop="provider"
            label="Provider"
          /><el-table-column
            prop="attempt_count"
            label="尝试"
          /><el-table-column label="操作">
            <template #default="scope">
              <el-button
                v-if="['failed_final','failed_retryable','deferred'].includes(scope.row.status)"
                size="small"
                @click="retryDelivery(scope.row)"
              >
                重新校验并重试
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane
        v-if="auth.hasPermission('notifications.dead_letters.read')"
        label="Dead Letter"
        name="deadletters"
      >
        <el-table :data="deadLetters">
          <el-table-column
            prop="source_type"
            label="来源"
          /><el-table-column
            prop="failure_stage"
            label="阶段"
          /><el-table-column
            prop="error_code"
            label="安全错误码"
          /><el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          /><el-table-column label="操作">
            <template #default="scope">
              <el-button
                v-if="scope.row.status === 'open'"
                size="small"
                @click="resolveDeadLetter(scope.row)"
              >
                关闭
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane
        v-if="auth.hasPermission('notifications.reminders.read')"
        label="提醒与摘要"
        name="reminders"
      >
        <el-table :data="reminders">
          <el-table-column
            prop="reminder_type"
            label="提醒"
          /><el-table-column
            prop="subject_type"
            label="业务对象"
          /><el-table-column
            prop="trigger_at"
            :formatter="formatAdminTableCell"
            label="触发时间（UTC+8）"
          /><el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          /><el-table-column label="操作">
            <template #default="scope">
              <el-button
                v-if="['planned','scheduled'].includes(scope.row.status)"
                size="small"
                @click="cancelReminder(scope.row)"
              >
                取消
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane
        v-if="auth.hasPermission('notifications.campaigns.read')"
        label="Campaign"
        name="campaigns"
      >
        <el-form
          class="inline-operation-form"
          label-position="top"
        >
          <el-form-item label="Campaign Code">
            <el-input
              v-model="newCampaign.campaign_code"
              placeholder="NEWSLETTER_2026_08"
            />
          </el-form-item><el-form-item label="内部名称">
            <el-input v-model="newCampaign.internal_name" />
          </el-form-item><el-form-item label="语言">
            <el-select v-model="newCampaign.locale">
              <el-option
                label="简体中文"
                value="zh-CN"
              /><el-option
                label="繁體中文"
                value="zh-TW"
              /><el-option
                label="English"
                value="en"
              />
            </el-select>
          </el-form-item><el-button
            type="primary"
            @click="createCampaign"
          >
            创建草稿
          </el-button>
        </el-form>
        <el-table :data="campaigns">
          <el-table-column
            prop="campaign_code"
            label="Code"
          /><el-table-column
            prop="internal_name"
            label="名称"
          /><el-table-column
            prop="category"
            label="分类"
          /><el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          /><el-table-column
            label="受控流程"
            min-width="320"
          >
            <template #default="scope">
              <el-button
                v-if="scope.row.status === 'draft'"
                size="small"
                @click="campaignAction(scope.row,'test-send')"
              >
                测试发送
              </el-button><el-button
                v-if="scope.row.status === 'draft'"
                size="small"
                @click="campaignAction(scope.row,'submit-review')"
              >
                提交审批
              </el-button><el-button
                v-if="scope.row.status === 'in_review'"
                size="small"
                @click="campaignAction(scope.row,'approve')"
              >
                独立审批
              </el-button><el-button
                v-if="scope.row.status === 'approved'"
                size="small"
                @click="campaignAction(scope.row,'audience')"
              >
                冻结受众
              </el-button><el-button
                v-if="['ready','paused'].includes(scope.row.status)"
                size="small"
                @click="campaignAction(scope.row,'start')"
              >
                启动
              </el-button><el-button
                v-if="scope.row.status === 'sending'"
                size="small"
                @click="campaignAction(scope.row,'pause')"
              >
                暂停
              </el-button><el-button
                v-if="!['completed','cancelled'].includes(scope.row.status)"
                size="small"
                type="danger"
                @click="campaignAction(scope.row,'cancel')"
              >
                取消
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <p>创建者不能自行批准正式群发；暂停/取消只停止新发送，不能撤回已进入邮箱的邮件。</p>
      </el-tab-pane>
      <el-tab-pane
        v-if="auth.hasPermission('notifications.providers.read') || auth.hasPermission('notifications.suppressions.read')"
        label="Provider 与抑制"
        name="providers"
      >
        <el-form
          class="inline-operation-form"
          label-position="top"
        >
          <el-form-item label="邮箱">
            <el-input v-model="newSuppression.destination" />
          </el-form-item><el-form-item label="原因">
            <el-select v-model="newSuppression.reason">
              <el-option
                label="管理员阻止"
                value="admin_blocked"
              /><el-option
                label="安全 Hold"
                value="security_hold"
              /><el-option
                label="无效地址"
                value="invalid_address"
              />
            </el-select>
          </el-form-item><el-button @click="createSuppression">
            新增抑制
          </el-button>
        </el-form>
        <el-table :data="suppressions">
          <el-table-column
            prop="destination_anonymous_hash"
            label="地址 Hash"
          /><el-table-column
            prop="suppression_reason"
            label="原因"
          /><el-table-column
            prop="source"
            label="来源"
          /><el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
          /><el-table-column label="操作">
            <template #default="scope">
              <el-button
                v-if="scope.row.status === 'active'"
                size="small"
                @click="liftSuppression(scope.row)"
              >
                有理由解除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-table :data="providerEvents">
          <el-table-column
            prop="provider_event_id"
            label="Provider Event"
          /><el-table-column
            prop="event_type"
            label="类型"
          /><el-table-column
            prop="signature_verified"
            label="验签"
          /><el-table-column
            prop="processing_status"
            label="处理状态"
          />
        </el-table>
      </el-tab-pane>
      <el-tab-pane
        v-if="auth.hasPermission('notifications.audit.read')"
        label="审计"
        name="audit"
      >
        <el-table :data="audits">
          <el-table-column
            prop="event_type"
            label="事件"
          /><el-table-column
            prop="subject_type"
            label="对象"
          /><el-table-column
            prop="reason"
            label="理由"
          /><el-table-column
            prop="created_at"
            :formatter="formatAdminTableCell"
            label="时间（UTC+8）"
          />
        </el-table><p>审计不保存完整正文、辅导内容、AI 对话、密码重置 Token 或退订 Token。</p>
      </el-tab-pane>
    </el-tabs>

    <el-drawer
      v-model="templateDrawer"
      title="模板版本与发布"
      size="820px"
    >
      <template v-if="templateDetail">
        <h3>{{ templateDetail.definition.template_code }} · {{ templateDetail.definition.internal_name }}</h3>
        <p class="admin-hint">
          已激活的版本不可原地修改。要改文案就新建版本，走「送审 → 批准 → 激活」；出问题用回滚切回上一个已激活版本。
        </p>
        <el-button
          v-if="canUpdateTemplate"
          type="primary"
          @click="releaseDialog.open = true"
        >
          新建版本
        </el-button>
        <el-table
          :data="templateDetail.releases"
          size="small"
          empty-text="暂无版本"
        >
          <el-table-column
            prop="semantic_version"
            label="版本"
            width="100"
          /><el-table-column
            prop="locale"
            label="语言"
            width="90"
          /><el-table-column
            prop="channel"
            label="渠道"
            width="90"
          /><el-table-column
            prop="status"
            :formatter="formatAdminTableCell"
            label="状态"
            width="120"
          /><el-table-column
            label="操作"
            min-width="360"
          >
            <template #default="scope">
              <el-button
                v-for="actionDefinition in templateReleaseActions(scope.row.status)"
                :key="actionDefinition.action"
                size="small"
                :type="actionDefinition.type"
                @click="runTemplateReleaseAction(scope.row, actionDefinition.action)"
              >
                {{ actionDefinition.label }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-descriptions
          v-if="preview"
          title="渲染预览"
          :column="1"
          border
        >
          <el-descriptions-item
            v-for="(value, key) in preview"
            :key="key"
            :label="String(key)"
          >
            <pre class="preview-value">{{ value }}</pre>
          </el-descriptions-item>
        </el-descriptions>
      </template>
    </el-drawer>

    <el-dialog
      v-model="templateDialog.open"
      title="新建通知模板"
      width="620px"
    >
      <el-form label-position="top">
        <el-form-item label="模板代码（小写字母、数字与连字符）">
          <el-input
            v-model="templateDialog.template_code"
            placeholder="order-paid-receipt"
          />
        </el-form-item>
        <el-form-item label="内部名称">
          <el-input v-model="templateDialog.internal_name" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="templateDialog.category">
            <el-option
              v-for="item in NOTIFICATION_CATEGORIES"
              :key="item"
              :label="item"
              :value="item"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="用途">
          <el-select v-model="templateDialog.purpose">
            <el-option
              v-for="item in TEMPLATE_PURPOSES"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="支持渠道">
          <el-checkbox-group v-model="templateDialog.supported_channels">
            <el-checkbox value="in_app">
              站内
            </el-checkbox>
            <el-checkbox value="email">
              邮件
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="必达渠道（勾选后该渠道失败会进入死信）">
          <el-checkbox-group v-model="templateDialog.required_channels">
            <el-checkbox value="in_app">
              站内
            </el-checkbox>
            <el-checkbox value="email">
              邮件
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="变量结构（JSON 对象）">
          <el-input
            v-model="templateDialog.variable_schema"
            type="textarea"
            :rows="4"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="templateDialog.open = false">
          取消
        </el-button>
        <el-button
          type="primary"
          :loading="busy"
          @click="createTemplate"
        >
          创建模板
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="releaseDialog.open"
      title="新建模板版本"
      width="720px"
    >
      <el-form label-position="top">
        <el-form-item label="语义化版本">
          <el-input
            v-model="releaseDialog.semantic_version"
            placeholder="1.0.0"
          />
        </el-form-item>
        <el-form-item label="语言">
          <el-select v-model="releaseDialog.locale">
            <el-option
              label="简体中文"
              value="zh-CN"
            /><el-option
              label="繁體中文"
              value="zh-TW"
            /><el-option
              label="英文"
              value="en"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="渠道">
          <el-select v-model="releaseDialog.channel">
            <el-option
              label="站内"
              value="in_app"
            /><el-option
              label="邮件"
              value="email"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="邮件主题模板">
          <el-input v-model="releaseDialog.subject_template" />
        </el-form-item>
        <el-form-item label="标题模板">
          <el-input v-model="releaseDialog.title_template" />
        </el-form-item>
        <el-form-item label="纯文本正文（必填，所有渠道的兜底内容）">
          <el-input
            v-model="releaseDialog.body_text_template"
            type="textarea"
            :rows="5"
          />
        </el-form-item>
        <el-form-item label="HTML 正文">
          <el-input
            v-model="releaseDialog.body_html_template"
            type="textarea"
            :rows="5"
          />
        </el-form-item>
        <el-form-item label="操作按钮文案">
          <el-input v-model="releaseDialog.action_label_template" />
        </el-form-item>
        <el-form-item label="操作链接模板">
          <el-input v-model="releaseDialog.action_url_template" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="releaseDialog.open = false">
          取消
        </el-button>
        <el-button
          type="primary"
          :loading="busy"
          @click="createRelease"
        >
          创建版本
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="previewDialog.open"
      :title="previewDialog.mode === 'preview' ? '渲染预览' : '测试发送'"
      width="560px"
    >
      <p class="admin-hint">
        {{ previewDialog.mode === "preview"
          ? "预览只在服务端渲染，不会发给任何人。"
          : "测试发送会真实投递到指定收件人，请使用团队测试账号。" }}
      </p>
      <el-form label-position="top">
        <el-form-item label="变量取值（JSON 对象）">
          <el-input
            v-model="previewDialog.variables"
            type="textarea"
            :rows="5"
          />
        </el-form-item>
        <el-form-item
          v-if="previewDialog.mode === 'test-send'"
          label="测试收件人（留空则发给当前管理员）"
        >
          <el-input v-model="previewDialog.recipient" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="previewDialog.open = false">
          关闭
        </el-button>
        <el-button
          type="primary"
          :loading="busy"
          @click="runPreview"
        >
          {{ previewDialog.mode === "preview" ? "渲染" : "发送" }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.notification-admin-page { display: grid; gap: 1rem; }
.page-heading { align-items: flex-start; display: flex; justify-content: space-between; }
.metric-grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); }
.metric-grid :deep(.el-card__body) { display: grid; gap: .25rem; }
.metric-grid strong { font-size: 1.8rem; }
.operation-reason { max-width: 40rem; }
.inline-operation-form { align-items: end; display: grid; gap: 1rem; grid-template-columns: repeat(4, minmax(10rem, 1fr)); margin: 1rem 0; }
@media (max-width: 900px) { .inline-operation-form { grid-template-columns: 1fr; } }
.preview-value { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; font-size: .85rem; }
.admin-hint { color: var(--el-text-color-secondary); }
</style>
