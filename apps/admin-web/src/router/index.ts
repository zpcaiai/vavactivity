import { createRouter, createWebHistory } from "vue-router";

import AdminLayout from "@/layouts/AdminLayout.vue";
import AcceptInvitationPage from "@/pages/AcceptInvitationPage.vue";
import ActivityManagementPage from "@/pages/ActivityManagementPage.vue";
import AccessManagementPage from "@/pages/AccessManagementPage.vue";
import CatalogManagementPage from "@/pages/CatalogManagementPage.vue";
import CatalogProductEditorPage from "@/pages/CatalogProductEditorPage.vue";
import CommerceManagementPage from "@/pages/CommerceManagementPage.vue";
import CourseManagementPage from "@/pages/CourseManagementPage.vue";
import CounselingManagementPage from "@/pages/CounselingManagementPage.vue";
import CmsEditorPage from "@/pages/CmsEditorPage.vue";
import DashboardPage from "@/pages/DashboardPage.vue";
import CmsManagementPage from "@/pages/CmsManagementPage.vue";
import ErrorPage from "@/pages/ErrorPage.vue";
import LoginPage from "@/pages/LoginPage.vue";
import MediaLibraryPage from "@/pages/MediaLibraryPage.vue";
import KnowledgeManagementPage from "@/pages/KnowledgeManagementPage.vue";
import AiManagementPage from "@/pages/AiManagementPage.vue";
import NotificationManagementPage from "@/pages/NotificationManagementPage.vue";
import MatchmakingProfileManagementPage from "@/pages/MatchmakingProfileManagementPage.vue";
import PrivacyManagementPage from "@/pages/PrivacyManagementPage.vue";
import ModuleListPage from "@/pages/ModuleListPage.vue";
import NavigationManagementPage from "@/pages/NavigationManagementPage.vue";
import PricingSimulationPage from "@/pages/PricingSimulationPage.vue";
import RecommendationManagementPage from "@/pages/RecommendationManagementPage.vue";
import MatchmakingInteractionManagementPage from "@/pages/MatchmakingInteractionManagementPage.vue";
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

const notificationSectionPermissions: Record<string, string> = {
  dashboard: "notifications.analytics.read",
  templates: "notifications.templates.read",
  "template-releases": "notifications.templates.read",
  "event-subscriptions": "notifications.subscriptions.read",
  deliveries: "notifications.deliveries.read",
  "dead-letters": "notifications.dead_letters.read",
  reminders: "notifications.reminders.read",
  campaigns: "notifications.campaigns.read",
  providers: "notifications.providers.read",
  "provider-events": "notifications.providers.read",
  suppressions: "notifications.suppressions.read",
  unsubscribes: "notifications.preferences.read",
  audit: "notifications.audit.read"
};

const matchmakingSectionPermissions: Record<string, string> = {
  profiles: "matchmaking.profiles.read",
  reviews: "matchmaking.reviews.read",
  "photo-reviews": "matchmaking.photos.read",
  "schema-releases": "matchmaking.schemas.read",
  taxonomies: "matchmaking.taxonomies.read",
  projections: "matchmaking.projections.read",
  audit: "matchmaking.audit.read"
};

export const recommendationSectionPermissions: Record<string, string> = {
  dashboard: "recommendations.analytics.read",
  strategies: "recommendations.strategies.read",
  features: "recommendations.features.read",
  constraints: "recommendations.constraints.read",
  batches: "recommendations.batches.read",
  candidates: "recommendations.candidates.read",
  diagnostics: "recommendations.diagnostics.run",
  "pair-diagnostics": "recommendations.candidates.sensitive.read",
  exposures: "recommendations.exposures.read",
  "cold-start": "recommendations.analytics.read",
  feedback: "recommendations.feedback.read",
  evaluations: "recommendations.evaluations.read",
  experiments: "recommendations.experiments.read",
  incidents: "recommendations.incidents.read",
  audit: "recommendations.audit.read"
};

export const interactionSectionPermissions: Record<string, string> = {
  dashboard: "matchmaking.analytics.read",
  pairs: "matchmaking.interactions.read",
  matches: "matchmaking.matches.read",
  invitations: "matchmaking.invitations.read",
  "contact-exchanges": "matchmaking.contact_exchange.read",
  invalidations: "matchmaking.interactions.read",
  "dead-letters": "matchmaking.dead_letters.resolve",
  incidents: "matchmaking.incidents.read",
  audit: "matchmaking.audit.read"
};

const privacySectionPermissions: Record<string, string> = {
  dashboard: "privacy.requests.read",
  requests: "privacy.requests.read",
  exports: "privacy.exports.read",
  corrections: "privacy.corrections.read",
  erasures: "privacy.erasures.read",
  consents: "privacy.consents.read",
  "consent-releases": "privacy.consents.read",
  inventory: "privacy.inventory.read",
  processing: "privacy.inventory.read",
  classifications: "privacy.classifications.read",
  retention: "privacy.retention.read",
  "retention-instances": "privacy.retention.read",
  holds: "privacy.holds.read",
  "break-glass": "privacy.break_glass.read",
  "access-events": "privacy.sensitive_access.read",
  incidents: "privacy.incidents.read",
  audit: "privacy.audit.read"
};

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
      path: "/admin/accept-invitation",
      name: "admin-accept-invitation",
      component: AcceptInvitationPage,
      meta: { public: true, title: "接受管理员邀请" }
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
          meta: { title: "工作台" }
        },
        {
          path: "content/pages",
          name: "admin-content-pages",
          component: CmsManagementPage,
          meta: { title: "页面管理", permission: "content.pages.read", cmsSection: "pages" }
        },
        {
          path: "content/pages/:id",
          name: "admin-content-page-edit",
          component: CmsEditorPage,
          meta: { title: "页面编辑", permission: "content.pages.read" }
        },
        {
          path: "content/articles",
          name: "admin-content-articles",
          component: CmsManagementPage,
          meta: { title: "文章管理", permission: "content.articles.read", cmsSection: "articles" }
        },
        {
          path: "content/testimonials",
          name: "admin-content-testimonials",
          component: CmsManagementPage,
          meta: { title: "幸福见证", permission: "content.testimonials.read", cmsSection: "testimonials" }
        },
        {
          path: "content/media",
          name: "admin-content-media",
          component: MediaLibraryPage,
          meta: { title: "媒体库", permission: "content.media.read" }
        },
        {
          path: "content/navigation",
          name: "admin-content-navigation",
          component: NavigationManagementPage,
          meta: { title: "导航管理", permission: "content.navigation.read" }
        },
        {
          path: "content/settings",
          name: "admin-content-settings",
          component: AccessManagementPage,
          meta: { title: "网站设置", permission: "content.settings.read", endpoint: "/admin/site-settings" }
        },
        {
          path: "contact-submissions",
          name: "admin-contact-submissions",
          component: AccessManagementPage,
          meta: { title: "合作联系记录", permission: "contact.submissions.read", endpoint: "/admin/contact-submissions" }
        },
        {
          path: "catalog",
          redirect: "/admin/catalog/products"
        },
        {
          path: "catalog/products",
          name: "admin-catalog-products",
          component: CatalogManagementPage,
          meta: { title: "商品管理", permission: "catalog.products.read", catalogSection: "products" }
        },
        {
          path: "catalog/products/new",
          name: "admin-catalog-products-new",
          component: CatalogManagementPage,
          meta: { title: "新建商品", permission: "catalog.products.create", catalogSection: "products" }
        },
        {
          path: "catalog/products/:id",
          name: "admin-catalog-product-edit",
          component: CatalogProductEditorPage,
          meta: { title: "商品编辑", permission: "catalog.products.read" }
        },
        {
          path: "catalog/skus/:id",
          name: "admin-catalog-sku-edit",
          component: CatalogManagementPage,
          meta: { title: "SKU 管理", permission: "catalog.skus.read", catalogSection: "products" }
        },
        {
          path: "catalog/price-books",
          name: "admin-catalog-price-books",
          component: CatalogManagementPage,
          meta: { title: "价格簿", permission: "catalog.price_books.read", catalogSection: "price-books" }
        },
        {
          path: "catalog/prices",
          name: "admin-catalog-prices",
          component: CatalogManagementPage,
          meta: { title: "价格记录", permission: "catalog.prices.read", catalogSection: "prices" }
        },
        {
          path: "catalog/inventory",
          name: "admin-catalog-inventory",
          component: CatalogManagementPage,
          meta: { title: "库存与名额", permission: "catalog.inventory.read", catalogSection: "inventory" }
        },
        {
          path: "catalog/inventory/:skuId",
          name: "admin-catalog-inventory-detail",
          component: CatalogManagementPage,
          meta: { title: "库存详情", permission: "catalog.inventory.read", catalogSection: "inventory" }
        },
        {
          path: "catalog/promotions",
          name: "admin-catalog-promotions",
          component: CatalogManagementPage,
          meta: { title: "优惠活动", permission: "catalog.promotions.read", catalogSection: "promotions" }
        },
        {
          path: "catalog/promotions/new",
          name: "admin-catalog-promotions-new",
          component: CatalogManagementPage,
          meta: { title: "新建优惠", permission: "catalog.promotions.create", catalogSection: "promotions" }
        },
        {
          path: "catalog/promotions/:id",
          name: "admin-catalog-promotion-edit",
          component: CatalogManagementPage,
          meta: { title: "优惠详情", permission: "catalog.promotions.read", catalogSection: "promotions" }
        },
        {
          path: "catalog/coupons",
          name: "admin-catalog-coupons",
          component: CatalogManagementPage,
          meta: { title: "优惠码", permission: "catalog.coupons.read", catalogSection: "coupons" }
        },
        {
          path: "catalog/coupons/import",
          name: "admin-catalog-coupons-import",
          component: CatalogManagementPage,
          meta: { title: "批量优惠码", permission: "catalog.coupons.create", catalogSection: "coupons" }
        },
        {
          path: "catalog/pricing/simulate",
          name: "admin-catalog-pricing-simulate",
          component: PricingSimulationPage,
          meta: { title: "定价模拟", permission: "catalog.pricing.simulate" }
        },
        ...[
          ["orders", "订单管理", "orders", "commerce.orders.read"],
          ["payments", "支付管理", "payments", "commerce.payments.read"],
          ["subscriptions", "订阅管理", "subscriptions", "commerce.subscriptions.read"],
          ["refunds", "退款审批", "refunds", "commerce.refunds.read"],
          ["webhooks", "Webhook 日志", "webhooks", "commerce.webhooks.read"],
          ["reconciliation", "支付对账", "reconciliation", "commerce.reconciliation.read"],
          ["entitlements", "权益管理", "entitlements", "commerce.entitlements.read"]
        ].map(([path, title, commerceSection, permission]) => ({
          path: `commerce/${path}`,
          name: `admin-commerce-${path}`,
          component: CommerceManagementPage,
          meta: { title, commerceSection, permission }
        })),
        {
          path: "users",
          name: "admin-users",
          component: AccessManagementPage,
          meta: { title: "用户管理", permission: "users.read", endpoint: "/admin/users" }
        },
        {
          path: "activities",
          name: "admin-activities",
          component: ActivityManagementPage,
          meta: { title: "活动中心", permission: "activities.read" }
        },
        {
          path: "courses",
          name: "admin-courses",
          component: CourseManagementPage,
          meta: { title: "课程中心", permission: "courses.read" }
        },
        {
          path: "counseling",
          name: "admin-counseling",
          component: CounselingManagementPage,
          meta: { title: "辅导中心", permission: "counseling.appointments.read" }
        },
        {
          path: "knowledge",
          name: "admin-knowledge",
          component: KnowledgeManagementPage,
          meta: { title: "知识库中心", permission: "knowledge.spaces.read" }
        },
        {
          path: "ai",
          name: "admin-ai",
          component: AiManagementPage,
          meta: { title: "AI 运营中心", permission: "ai.conversations.read" }
        },
        ...[
          "dashboard",
          "templates",
          "template-releases",
          "event-subscriptions",
          "deliveries",
          "dead-letters",
          "reminders",
          "campaigns",
          "providers",
          "provider-events",
          "suppressions",
          "unsubscribes",
          "audit"
        ].map((section) => ({
          path: `notifications/${section}`,
          name: `admin-notifications-${section}`,
          component: NotificationManagementPage,
          meta: { title: "通知运营中心", permission: notificationSectionPermissions[section], notificationSection: section }
        })),
        {
          path: "notifications/templates/:templateId",
          name: "admin-notifications-template-detail",
          component: NotificationManagementPage,
          meta: { title: "通知模板详情", permission: "notifications.templates.read", notificationSection: "templates" }
        },
        {
          path: "notifications/deliveries/:deliveryId",
          name: "admin-notifications-delivery-detail",
          component: NotificationManagementPage,
          meta: { title: "通知发送详情", permission: "notifications.deliveries.read", notificationSection: "deliveries" }
        },
        {
          path: "notifications/campaigns/new",
          name: "admin-notifications-campaign-new",
          component: NotificationManagementPage,
          meta: { title: "新建通知活动", permission: "notifications.campaigns.create", notificationSection: "campaigns" }
        },
        {
          path: "notifications/campaigns/:campaignId",
          name: "admin-notifications-campaign-detail",
          component: NotificationManagementPage,
          meta: { title: "通知活动详情", permission: "notifications.campaigns.read", notificationSection: "campaigns" }
        },
        ...Object.keys(matchmakingSectionPermissions).map((section) => ({
          path: `matchmaking/${section}`,
          name: `admin-matchmaking-${section}`,
          component: MatchmakingProfileManagementPage,
          meta: { title: "婚恋档案运营中心", permission: matchmakingSectionPermissions[section], matchmakingSection: section }
        })),
        {
          path: "matchmaking/profiles/:profileId",
          name: "admin-matchmaking-profile-detail",
          component: MatchmakingProfileManagementPage,
          meta: { title: "婚恋档案详情", permission: "matchmaking.profiles.read", matchmakingSection: "profiles" }
        },
        {
          path: "matchmaking/reviews/:caseId",
          name: "admin-matchmaking-review-detail",
          component: MatchmakingProfileManagementPage,
          meta: { title: "档案审核详情", permission: "matchmaking.reviews.read", matchmakingSection: "reviews" }
        },
        ...Object.keys(recommendationSectionPermissions).map((section) => ({
          path: `recommendations/${section}`,
          name: `admin-recommendations-${section}`,
          component: RecommendationManagementPage,
          meta: { title: "推荐运营中心", permission: recommendationSectionPermissions[section], recommendationSection: section }
        })),
        {
          path: "recommendations/strategies/:id",
          name: "admin-recommendations-strategy-detail",
          component: RecommendationManagementPage,
          meta: { title: "推荐策略详情", permission: "recommendations.strategies.read", recommendationSection: "strategies" }
        },
        {
          path: "recommendations/batches/:id",
          name: "admin-recommendations-batch-detail",
          component: RecommendationManagementPage,
          meta: { title: "推荐批次详情", permission: "recommendations.batches.read", recommendationSection: "batches" }
        },
        {
          path: "recommendations/experiments/:id",
          name: "admin-recommendations-experiment-detail",
          component: RecommendationManagementPage,
          meta: { title: "推荐实验详情", permission: "recommendations.experiments.read", recommendationSection: "experiments" }
        },
        ...Object.keys(interactionSectionPermissions).map((section) => ({
          path: `matchmaking-interactions/${section}`,
          name: `admin-matchmaking-interactions-${section}`,
          component: MatchmakingInteractionManagementPage,
          meta: { title: "互动运营中心", permission: interactionSectionPermissions[section], interactionSection: section }
        })),
        {
          path: "matchmaking-interactions/pairs/:id",
          name: "admin-matchmaking-interactions-pair-detail",
          component: MatchmakingInteractionManagementPage,
          meta: { title: "互动用户对诊断", permission: "matchmaking.interactions.read", interactionSection: "pairs" }
        },
        {
          path: "matchmaking-interactions/contact-exchanges/:id",
          name: "admin-matchmaking-contact-exchange-detail",
          component: MatchmakingInteractionManagementPage,
          meta: { title: "联系方式授权诊断", permission: "matchmaking.contact_exchange.read", interactionSection: "contact-exchanges" }
        },
        ...Object.keys(privacySectionPermissions).map((section) => ({
          path: `privacy/${section}`,
          name: `admin-privacy-${section}`,
          component: PrivacyManagementPage,
          meta: { title: "隐私运营中心", permission: privacySectionPermissions[section], privacySection: section }
        })),
        {
          path: "privacy/requests/:requestId",
          name: "admin-privacy-request-detail",
          component: PrivacyManagementPage,
          meta: { title: "隐私请求详情", permission: "privacy.requests.read", privacySection: "requests" }
        },
        {
          path: "access/admins",
          name: "admin-access-admins",
          component: AccessManagementPage,
          meta: { title: "管理员", permission: "admins.read", endpoint: "/admin/admins" }
        },
        {
          path: "access/roles",
          name: "admin-access-roles",
          component: AccessManagementPage,
          meta: { title: "角色权限", permission: "roles.read", endpoint: "/admin/roles" }
        },
        {
          path: "access/permissions",
          name: "admin-access-permissions",
          component: AccessManagementPage,
          meta: { title: "权限注册表", permission: "roles.read", endpoint: "/admin/roles" }
        },
        {
          path: "access/invitations",
          name: "admin-access-invitations",
          component: AccessManagementPage,
          meta: { title: "管理员邀请", permission: "admins.read", endpoint: "/admin/admins/invitations" }
        },
        {
          path: "audit/auth",
          name: "admin-audit-auth",
          component: AccessManagementPage,
          meta: { title: "认证审计", permission: "audit.read", endpoint: "/admin/audit/security-events" }
        },
        {
          path: "audit/permissions",
          name: "admin-audit-permissions",
          component: AccessManagementPage,
          meta: { title: "权限审计", permission: "audit.read", endpoint: "/admin/audit/security-events" }
        },
        ...modules.filter(([path]) => !["users", "catalog", "activities", "courses", "counseling", "ai"].includes(path)).map(([path, title, description, routePermission]) => ({
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

router.beforeEach(async (to) => {
  document.title = `${String(to.meta.title ?? "运营工作台")} · VAV`;
  if (to.meta.public) {
    return true;
  }

  const access = useAccessStore();
  await access.bootstrap();
  if (!access.isAuthenticated) {
    return { name: "admin-login", query: { returnTo: to.fullPath } };
  }
  if (
    typeof to.meta.permission === "string" &&
    !access.hasPermission(to.meta.permission)
  ) {
    return { name: "admin-forbidden" };
  }
  return true;
});

export const adminModuleRoutes = modules;
