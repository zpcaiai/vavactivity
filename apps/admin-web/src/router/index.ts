import { createRouter, createWebHistory } from "vue-router";

import AdminLayout from "@/layouts/AdminLayout.vue";
import DashboardPage from "@/pages/DashboardPage.vue";
import ErrorPage from "@/pages/ErrorPage.vue";
import LoginPage from "@/pages/LoginPage.vue";
import ModuleListPage from "@/pages/ModuleListPage.vue";
import { useAccessStore } from "@/stores/access";

const modules = [
  ["users", "用户", "账户、资料与数据权利", "users:view"],
  ["content", "内容", "页面、文章与幸福见证", "content:view"],
  ["activities", "活动", "发布、报名、签到与分组", "activities:view"],
  ["courses", "课程", "课程结构、资源与进度", "courses:view"],
  ["counseling", "辅导", "导师、预约与跟进", "counseling:view"],
  ["catalog", "服务目录", "商品、价格与权益定义", "catalog:view"],
  ["orders", "订单", "订单状态与售后处理", "orders:view"],
  ["payments", "支付", "Webhook、退款与支付日志", "payments:view"],
  ["ai", "AI 辅导", "知识库、对话风险与转介", "ai:view"],
  ["moderation", "安全审核", "档案、照片、举报与屏蔽", "moderation:view"],
  ["settings", "系统设置", "配置与待决策项状态", "settings:view"],
  ["audit", "审计日志", "追加式操作记录", "audit:view"]
] as const;

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/admin/login",
      name: "admin-login",
      component: LoginPage,
      meta: { public: true, title: "运营登录" }
    },
    {
      path: "/admin",
      component: AdminLayout,
      children: [
        { path: "", redirect: "/admin/dashboard" },
        {
          path: "dashboard",
          name: "admin-dashboard",
          component: DashboardPage,
          meta: { title: "工作台", permission: "dashboard:view" }
        },
        ...modules.map(([path, title, description, routePermission]) => ({
          path,
          name: `admin-${path}`,
          component: ModuleListPage,
          meta: { title, description, permission: routePermission }
        }))
      ]
    },
    {
      path: "/admin/403",
      name: "admin-forbidden",
      component: ErrorPage,
      props: { status: 403 }
    },
    {
      path: "/admin/500",
      name: "admin-error",
      component: ErrorPage,
      props: { status: 500 }
    },
    {
      path: "/admin/:pathMatch(.*)*",
      name: "admin-not-found",
      component: ErrorPage,
      props: { status: 404 }
    },
    { path: "/:pathMatch(.*)*", redirect: "/admin/login" }
  ]
});

router.beforeEach((to) => {
  document.title = `${String(to.meta.title ?? "运营工作台")} · VAV`;
  if (to.meta.public) {
    return true;
  }

  const access = useAccessStore();
  if (!access.isAuthenticated && !access.foundationPreview) {
    return { name: "admin-login", query: { returnTo: to.fullPath } };
  }
  if (
    !access.foundationPreview &&
    typeof to.meta.permission === "string" &&
    !access.hasPermission(to.meta.permission)
  ) {
    return { name: "admin-forbidden" };
  }
  return true;
});

export const adminModuleRoutes = modules;

