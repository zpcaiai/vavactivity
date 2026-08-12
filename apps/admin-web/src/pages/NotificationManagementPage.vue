<script setup lang="ts">
import { onMounted, ref } from "vue";
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
type Template = { id: string; template_code: string; internal_name: string; category: string; purpose: string; release_count: number; active_count: number };
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
          />
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
</style>
