<script setup lang="ts">
import {
  DataAnalysis,
  Document,
  Goods,
  House,
  Lock,
  Setting,
  User
} from "@element-plus/icons-vue";
import { computed, ref, watchEffect } from "vue";
import { useRoute } from "vue-router";

import { adminLocales, type AdminLocale, useAdminLocale } from "@/i18n";
import { useAdminAuthStore } from "@/stores/admin-auth";

const route = useRoute();
const auth = useAdminAuthStore();
const { locale, setLocale, t } = useAdminLocale();
const collapsed = ref(false);
const pageTitle = computed(() => String(route.meta.title ?? "工作台"));

const menu = [
  { path: "/admin/dashboard", labelKey: "menu.dashboard", icon: House },
  { path: "/admin/users", labelKey: "menu.users", icon: User },
  { path: "/admin/content/pages", labelKey: "menu.pages", icon: Document },
  { path: "/admin/content/media", labelKey: "menu.media", icon: Document },
  { path: "/admin/content/navigation", labelKey: "menu.navigation", icon: Document },
  { path: "/admin/catalog/products", labelKey: "menu.catalog", icon: Goods },
  { path: "/admin/commerce/orders", labelKey: "menu.commerce", icon: Goods },
  { path: "/admin/activities", labelKey: "menu.activities", icon: Goods },
  { path: "/admin/courses", labelKey: "menu.courses", icon: Document },
  { path: "/admin/counseling", labelKey: "menu.counseling", icon: User },
  { path: "/admin/knowledge", labelKey: "menu.knowledge", icon: Document },
  { path: "/admin/ai", labelKey: "menu.ai", icon: DataAnalysis },
  { path: "/admin/notifications/dashboard", labelKey: "menu.notifications", icon: Document },
  { path: "/admin/privacy/dashboard", labelKey: "menu.privacy", icon: Lock },
  { path: "/admin/matchmaking-interactions/dashboard", labelKey: "menu.interactions", icon: User },
  { path: "/admin/relationships/dashboard", labelKey: "menu.relationships", icon: User },
  { path: "/admin/system/status", labelKey: "menu.system", icon: Setting },
  { path: "/admin/content/settings", labelKey: "menu.settings", icon: Setting },
  { path: "/admin/access/admins", labelKey: "menu.admins", icon: Lock },
  { path: "/admin/audit/auth", labelKey: "menu.audit", icon: DataAnalysis }
];
const visibleMenu = computed(() => {
  const notificationLanding = [
    ["notifications.analytics.read", "dashboard"],
    ["notifications.templates.read", "templates"],
    ["notifications.deliveries.read", "deliveries"],
    ["notifications.campaigns.read", "campaigns"],
    ["notifications.reminders.read", "reminders"],
    ["notifications.providers.read", "providers"],
    ["notifications.audit.read", "audit"]
  ].find(([permission]) => auth.hasPermission(permission))?.[1];
  return menu.map((item) => item.path === "/admin/notifications/dashboard" && notificationLanding
    ? { ...item, path: `/admin/notifications/${notificationLanding}` }
    : item).filter((item) => {
    const permissionByPath: Record<string, string> = {
      "/admin/users": "users.read",
      "/admin/content/pages": "content.pages.read",
      "/admin/content/media": "content.media.read",
      "/admin/content/navigation": "content.navigation.read",
      "/admin/catalog/products": "catalog.products.read",
      "/admin/commerce/orders": "commerce.orders.read",
      "/admin/activities": "activities.read",
      "/admin/courses": "courses.read",
      "/admin/counseling": "counseling.appointments.read",
      "/admin/knowledge": "knowledge.spaces.read",
      "/admin/ai": "ai.conversations.read",
      "/admin/notifications/dashboard": "notifications.analytics.read",
      "/admin/privacy/dashboard": "privacy.requests.read",
      "/admin/matchmaking-interactions/dashboard": "matchmaking.analytics.read",
      "/admin/relationships/dashboard": "relationships.analytics.read",
      "/admin/system/status": "system.status.read",
      "/admin/content/settings": "content.settings.read",
      "/admin/access/admins": "admins.read",
      "/admin/audit/auth": "audit.read"
    };
    if (item.labelKey === "menu.notifications") {
      return Boolean(notificationLanding);
    }
    const required = permissionByPath[item.path];
    return !required || auth.hasPermission(required);
  });
});

function changeLocale(value: string) {
  if (adminLocales.includes(value as AdminLocale)) {
    setLocale(value as AdminLocale);
  }
}

watchEffect(() => {
  document.documentElement.lang = locale.value;
});
</script>

<template>
  <div class="admin-shell">
    <aside :class="['admin-sidebar', { collapsed }]">
      <div class="admin-brand">
        <span
          class="brand-mark"
          aria-hidden="true"
        >V</span>
        <div v-if="!collapsed">
          <strong>VAV</strong>
          <small>{{ t("shell.workspace") }}</small>
        </div>
      </div>
      <el-menu
        :default-active="route.path"
        router
        :collapse="collapsed"
      >
        <el-menu-item
          v-for="item in visibleMenu"
          :key="item.path"
          :index="item.path"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>
            {{ t(item.labelKey) }}
          </template>
        </el-menu-item>
      </el-menu>
      <button
        class="collapse-button"
        type="button"
        @click="collapsed = !collapsed"
      >
        {{ collapsed ? t("shell.expand") : t("shell.collapse") }}
      </button>
    </aside>

    <section class="admin-content">
      <header class="admin-header">
        <div>
          <p class="admin-kicker">
            {{ t("shell.operations") }}
          </p>
          <h1>{{ pageTitle }}</h1>
        </div>
        <div class="operator-actions">
          <label class="admin-locale-select">
            <span>{{ t("shell.language") }}</span>
            <el-select
              data-testid="admin-locale-select"
              :model-value="locale"
              size="small"
              @change="changeLocale"
            >
              <el-option
                label="简体中文"
                value="zh-CN"
              />
              <el-option
                label="繁體中文"
                value="zh-TW"
              />
              <el-option
                label="English"
                value="en"
              />
            </el-select>
          </label>
          <div class="operator-chip">
            <span class="status-dot" />
            <div>
              <strong>{{ auth.user?.email }}</strong>
              <small>{{ t("shell.authorizedSession") }}</small>
            </div>
          </div>
        </div>
      </header>
      <main class="admin-main">
        <RouterView />
      </main>
    </section>
  </div>
</template>
