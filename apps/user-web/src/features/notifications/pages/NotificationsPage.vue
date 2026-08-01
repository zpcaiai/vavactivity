<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import {
  notificationApi,
  type NotificationPreference,
  type UserNotification
} from "../api";

const route = useRoute();
const notifications = ref<UserNotification[]>([]);
const preferences = ref<NotificationPreference[]>([]);
const category = ref("");
const onlyUnread = ref(false);
const marketingConsent = ref(false);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const mode = computed(() => (String(route.name).includes("preferences") ? "preferences" : "list"));
const locale = computed(() => String(route.params.locale ?? "zh-CN"));
const copy = computed(() => {
  if (locale.value === "en") return { title: "Notifications", prefs: "Notification preferences", all: "All", unread: "Unread only", markAll: "Mark all read", empty: "No notifications", save: "Save preferences", marketing: "Marketing email opt-in", mandatory: "Required for account security or paid service delivery and cannot be fully disabled.", archive: "Archive", open: "Open" };
  if (locale.value === "zh-TW") return { title: "通知中心", prefs: "通知偏好", all: "全部", unread: "只看未讀", markAll: "全部標為已讀", empty: "暫無通知", save: "儲存偏好", marketing: "同意接收行銷電郵", mandatory: "此通知用於帳戶安全或已購服務交付，不能完全關閉。", archive: "封存", open: "查看" };
  return { title: "通知中心", prefs: "通知偏好", all: "全部", unread: "只看未读", markAll: "全部标为已读", empty: "暂无通知", save: "保存偏好", marketing: "同意接收营销邮件", mandatory: "该通知用于账户安全或已购买服务交付，不能完全关闭。", archive: "归档", open: "查看" };
});
const categories = ["", "security", "order", "activity", "course", "counseling", "ai_assistant", "platform"];
const mandatory = new Set(["security", "order", "payment"]);

async function loadNotifications() {
  const params = new URLSearchParams();
  if (category.value) params.set("category", category.value);
  if (onlyUnread.value) params.set("status", "unread");
  const result = await notificationApi.list(params.size ? `?${params.toString()}` : "");
  notifications.value = result.items;
}

async function loadPreferences() {
  const [preferenceResult, consentResult] = await Promise.all([
    notificationApi.preferences(),
    notificationApi.consents()
  ]);
  preferences.value = preferenceResult.items;
  marketingConsent.value = consentResult.items.some(
    (item) => item.consent_type === "marketing_email" && item.status === "granted"
  );
  if (!preferences.value.length) {
    preferences.value = ["security", "order", "activity", "course", "counseling", "ai_assistant", "marketing"].flatMap(
      (value) => ["in_app", "email"].map((channel) => ({
        category: value,
        channel: channel as "in_app" | "email",
        enabled: mandatory.has(value) || value !== "marketing",
        frequency: "immediate" as const,
        quiet_hours_enabled: false,
        quiet_hours_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai"
      }))
    );
  }
}

async function load() {
  busy.value = true;
  error.value = "";
  try {
    if (mode.value === "list") await loadNotifications();
    else await loadPreferences();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "Unable to load notifications";
  } finally {
    busy.value = false;
  }
}

async function markRead(item: UserNotification) {
  if (!item.read_at) await notificationApi.read(item.id);
  window.dispatchEvent(new Event("vav:notifications-updated"));
  await loadNotifications();
}
async function archive(item: UserNotification) {
  await notificationApi.archive(item.id);
  window.dispatchEvent(new Event("vav:notifications-updated"));
  await loadNotifications();
}
async function markAll() {
  await notificationApi.markAllRead();
  window.dispatchEvent(new Event("vav:notifications-updated"));
  await loadNotifications();
}
async function savePreferences() {
  busy.value = true;
  error.value = "";
  try {
    await notificationApi.updatePreferences(preferences.value);
    await notificationApi.setMarketingConsent(marketingConsent.value);
    notice.value = locale.value === "en" ? "Preferences saved." : "通知偏好已保存。";
    await loadPreferences();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "Unable to save preferences";
  } finally {
    busy.value = false;
  }
}

onMounted(() => void load());
</script>

<template>
  <section class="notification-page page-section">
    <header class="notification-page-header">
      <div>
        <p class="eyebrow">
          VAV · ACCOUNT
        </p>
        <h1>{{ mode === "list" ? copy.title : copy.prefs }}</h1>
      </div>
      <nav class="notification-tabs">
        <RouterLink :to="`/${locale}/account/notifications`">
          {{ copy.title }}
        </RouterLink>
        <RouterLink :to="`/${locale}/account/notification-preferences`">
          {{ copy.prefs }}
        </RouterLink>
      </nav>
    </header>
    <p
      v-if="error"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>
    <p
      v-if="notice"
      class="form-success"
      role="status"
    >
      {{ notice }}
    </p>

    <template v-if="mode === 'list'">
      <div class="notification-toolbar">
        <label>
          <span class="sr-only">Category</span>
          <select
            v-model="category"
            @change="loadNotifications"
          >
            <option
              v-for="item in categories"
              :key="item"
              :value="item"
            >{{ item || copy.all }}</option>
          </select>
        </label>
        <label class="check-row"><input
          v-model="onlyUnread"
          type="checkbox"
          @change="loadNotifications"
        > {{ copy.unread }}</label>
        <button
          class="secondary-button"
          type="button"
          @click="markAll"
        >
          {{ copy.markAll }}
        </button>
      </div>
      <div
        v-if="!busy && !notifications.length"
        class="empty-state"
      >
        {{ copy.empty }}
      </div>
      <article
        v-for="item in notifications"
        :key="item.id"
        :class="['notification-item', { unread: !item.read_at, expired: item.expired }]"
      >
        <div>
          <div class="notification-meta">
            <span>{{ item.category }}</span><time>{{ new Date(item.created_at).toLocaleString(locale) }}</time>
          </div>
          <h2>{{ item.title }}</h2>
          <p>{{ item.body }}</p>
        </div>
        <div class="notification-actions">
          <RouterLink
            v-if="item.action_url && !item.expired"
            :to="`/${locale}${item.action_url}`"
            @click="markRead(item)"
          >
            {{ copy.open }}
          </RouterLink>
          <button
            type="button"
            @click="archive(item)"
          >
            {{ copy.archive }}
          </button>
        </div>
      </article>
    </template>

    <template v-else>
      <div class="preference-grid">
        <article
          v-for="item in preferences"
          :key="`${item.category}-${item.channel}`"
          class="preference-card"
        >
          <header><strong>{{ item.category }}</strong><span>{{ item.channel }}</span></header>
          <label class="check-row"><input
            v-model="item.enabled"
            type="checkbox"
            :disabled="mandatory.has(item.category)"
          > enabled</label>
          <select
            v-model="item.frequency"
            :disabled="mandatory.has(item.category)"
          >
            <option value="immediate">
              immediate
            </option><option value="daily_digest">
              daily digest
            </option><option value="weekly_digest">
              weekly digest
            </option><option value="disabled">
              disabled
            </option>
          </select>
          <label class="check-row"><input
            v-model="item.quiet_hours_enabled"
            type="checkbox"
            :disabled="mandatory.has(item.category)"
          > quiet hours</label>
          <div
            v-if="item.quiet_hours_enabled"
            class="quiet-hours"
          >
            <input
              v-model="item.quiet_hours_start"
              type="time"
            ><span>→</span><input
              v-model="item.quiet_hours_end"
              type="time"
            >
          </div>
          <small v-if="mandatory.has(item.category)">{{ copy.mandatory }}</small>
        </article>
      </div>
      <label class="marketing-consent"><input
        v-model="marketingConsent"
        type="checkbox"
      > {{ copy.marketing }}</label>
      <button
        class="primary-button"
        type="button"
        :disabled="busy"
        @click="savePreferences"
      >
        {{ copy.save }}
      </button>
    </template>
  </section>
</template>
