<script setup lang="ts">
import {
  Calendar,
  Collection,
  CreditCard,
  DataAnalysis,
  Document,
  Goods,
  House,
  List,
  Lock,
  MagicStick,
  Setting,
  User,
  UserFilled
} from "@element-plus/icons-vue";
import { computed, ref } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();
const collapsed = ref(false);
const pageTitle = computed(() => String(route.meta.title ?? "工作台"));

const menu = [
  { path: "/admin/dashboard", label: "工作台", icon: House },
  { path: "/admin/users", label: "用户", icon: User },
  { path: "/admin/content", label: "内容", icon: Document },
  { path: "/admin/activities", label: "活动", icon: Calendar },
  { path: "/admin/courses", label: "课程", icon: Collection },
  { path: "/admin/counseling", label: "辅导", icon: UserFilled },
  { path: "/admin/catalog", label: "服务目录", icon: Goods },
  { path: "/admin/orders", label: "订单", icon: List },
  { path: "/admin/payments", label: "支付", icon: CreditCard },
  { path: "/admin/ai", label: "AI 辅导", icon: MagicStick },
  { path: "/admin/moderation", label: "安全审核", icon: Lock },
  { path: "/admin/settings", label: "系统设置", icon: Setting },
  { path: "/admin/audit", label: "审计日志", icon: DataAnalysis }
];
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
          <small>运营工作台</small>
        </div>
      </div>
      <el-menu
        :default-active="route.path"
        router
        :collapse="collapsed"
      >
        <el-menu-item
          v-for="item in menu"
          :key="item.path"
          :index="item.path"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>
            {{ item.label }}
          </template>
        </el-menu-item>
      </el-menu>
      <button
        class="collapse-button"
        type="button"
        @click="collapsed = !collapsed"
      >
        {{ collapsed ? "展开" : "收起导航" }}
      </button>
    </aside>

    <section class="admin-content">
      <header class="admin-header">
        <div>
          <p class="admin-kicker">
            VAV OPERATIONS
          </p>
          <h1>{{ pageTitle }}</h1>
        </div>
        <div class="operator-chip">
          <span class="status-dot" />
          <div>
            <strong>Foundation preview</strong>
            <small>非生产授权会话</small>
          </div>
        </div>
      </header>
      <div
        class="preview-banner"
        role="note"
      >
        当前为工程基座预览。正式环境必须由后端验证管理员身份、角色和每次操作权限。
      </div>
      <main class="admin-main">
        <RouterView />
      </main>
    </section>
  </div>
</template>

