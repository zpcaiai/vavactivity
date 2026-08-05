import { createRouter, createWebHistory } from "vue-router";

import { i18n, supportedLocales } from "@/i18n";
import type { SupportedLocale } from "@/i18n";

import AccountPage from "@/pages/AccountPage.vue";
import ActivitiesPage from "@/features/activities/pages/ActivitiesPage.vue";
import ActivityDetailPage from "@/features/activities/pages/ActivityDetailPage.vue";
import ActivityRegistrationsPage from "@/features/activities/pages/ActivityRegistrationsPage.vue";
import ActivityExperiencePage from "@/features/activities/pages/ActivityExperiencePage.vue";
import ActivityMatchesPage from "@/features/activities/pages/ActivityMatchesPage.vue";
import CourseDetailPage from "@/features/courses/pages/CourseDetailPage.vue";
import CourseCertificatesPage from "@/features/courses/pages/CourseCertificatesPage.vue";
import CoursesPage from "@/features/courses/pages/CoursesPage.vue";
import CertificateVerificationPage from "@/features/courses/pages/CertificateVerificationPage.vue";
import LearningPage from "@/features/courses/pages/LearningPage.vue";
import MyCoursesPage from "@/features/courses/pages/MyCoursesPage.vue";
import CounselingAppointmentsPage from "@/features/counseling/pages/CounselingAppointmentsPage.vue";
import CounselingBookingPage from "@/features/counseling/pages/CounselingBookingPage.vue";
import CounselingServicePage from "@/features/counseling/pages/CounselingServicePage.vue";
import CounselingServicesPage from "@/features/counseling/pages/CounselingServicesPage.vue";
import AiAssistantPage from "@/features/ai-assistant/pages/AiAssistantPage.vue";
import NotificationsPage from "@/features/notifications/pages/NotificationsPage.vue";
import DatingProfilePage from "@/features/dating-profile/pages/DatingProfilePage.vue";
import RecommendationListPage from "@/features/recommendations/pages/RecommendationListPage.vue";
import RecommendationDetailPage from "@/features/recommendations/pages/RecommendationDetailPage.vue";
import RecommendationPreferencesPage from "@/features/recommendations/pages/RecommendationPreferencesPage.vue";
import RecommendationHistoryPage from "@/features/recommendations/pages/RecommendationHistoryPage.vue";
import RecommendationTransparencyPage from "@/features/recommendations/pages/RecommendationTransparencyPage.vue";
import PrivacyCenterPage from "@/features/privacy/pages/PrivacyCenterPage.vue";
import UnsubscribePage from "@/features/notifications/pages/UnsubscribePage.vue";
import AuthPage from "@/pages/AuthPage.vue";
import AuthTokenPage from "@/pages/AuthTokenPage.vue";
import CatalogPage from "@/features/catalog/pages/CatalogPage.vue";
import CmsPage from "@/features/public-site/pages/CmsPage.vue";
import ContentCollectionPage from "@/features/public-site/pages/ContentCollectionPage.vue";
import ContactPage from "@/features/public-site/pages/ContactPage.vue";
import ProductDetailPage from "@/features/catalog/pages/ProductDetailPage.vue";
import CartPage from "@/features/commerce/pages/CartPage.vue";
import CheckoutPage from "@/features/commerce/pages/CheckoutPage.vue";
import CommerceListPage from "@/features/commerce/pages/CommerceListPage.vue";
import OrderDetailPage from "@/features/commerce/pages/OrderDetailPage.vue";
import PaymentProcessingPage from "@/features/commerce/pages/PaymentProcessingPage.vue";
import HomePage from "@/pages/HomePage.vue";
import LanguageGateway from "@/pages/LanguageGateway.vue";
import NotFoundPage from "@/pages/NotFoundPage.vue";
import PublicLayout from "@/layouts/PublicLayout.vue";
import SessionPage from "@/pages/SessionPage.vue";
import { useAuthStore } from "@/stores/auth";

export const router = createRouter({
  history: createWebHistory(),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    { path: "/", name: "language", component: LanguageGateway },
    {
      path: "/:locale(zh-CN|zh-TW|en)",
      component: PublicLayout,
      children: [
        { path: "", name: "home", component: HomePage },
        { path: "about", name: "about", component: CmsPage, meta: { copyKey: "about", cmsSlug: "about" } },
        { path: "stories", name: "stories", component: ContentCollectionPage, meta: { collectionType: "testimonials" } },
        { path: "stories/:slug", name: "story-detail", component: CmsPage, meta: { copyKey: "stories" } },
        { path: "articles", name: "articles", component: ContentCollectionPage, meta: { collectionType: "articles" } },
        { path: "articles/:slug", name: "article-detail", component: CmsPage, meta: { copyKey: "articles" } },
        { path: "services", name: "services", component: CatalogPage, meta: { catalogTitle: "全部服务" } },
        { path: "services/:category", name: "service-category", component: CatalogPage, meta: { catalogTitle: "分类服务" } },
        { path: "products/:slug", name: "product-detail", component: ProductDetailPage },
        { path: "cart", name: "cart", component: CartPage },
        { path: "checkout", name: "checkout", component: CheckoutPage, meta: { requiresAuth: true, requiresVerifiedEmail: true } },
        { path: "checkout/processing", name: "checkout-processing", component: PaymentProcessingPage, meta: { requiresAuth: true } },
        { path: "account/orders", name: "account-orders", component: CommerceListPage, meta: { requiresAuth: true, commerceKind: "orders" } },
        { path: "account/orders/:orderNumber", name: "account-order-detail", component: OrderDetailPage, meta: { requiresAuth: true } },
        { path: "account/subscriptions", name: "account-subscriptions", component: CommerceListPage, meta: { requiresAuth: true, commerceKind: "subscriptions" } },
        { path: "account/entitlements", name: "account-entitlements", component: CommerceListPage, meta: { requiresAuth: true, commerceKind: "entitlements" } },
        { path: "contact", name: "contact", component: ContactPage },
        { path: "privacy", name: "privacy", component: CmsPage, meta: { copyKey: "about", cmsSlug: "privacy" } },
        { path: "terms", name: "terms", component: CmsPage, meta: { copyKey: "about", cmsSlug: "terms" } },
        { path: "refund-policy", name: "refund-policy", component: CmsPage, meta: { copyKey: "about", cmsSlug: "refund-policy" } },
        { path: "ai-disclaimer", name: "ai-disclaimer", component: CmsPage, meta: { copyKey: "ai", cmsSlug: "ai-disclaimer" } },
        { path: "activities", name: "activities", component: ActivitiesPage },
        { path: "activities/:slug", name: "activity-detail", component: ActivityDetailPage },
        { path: "activities/:slug/register", name: "activity-register", component: ActivityDetailPage, meta: { requiresAuth: true } },
        { path: "activities/:slug/waitlist", name: "activity-waitlist", component: ActivityDetailPage, meta: { requiresAuth: true } },
        { path: "account/activity-registrations", name: "activity-registrations", component: ActivityRegistrationsPage, meta: { requiresAuth: true } },
        { path: "account/activities", name: "account-activities", component: ActivityRegistrationsPage, meta: { requiresAuth: true } },
        { path: "account/activities/:activityId", name: "activity-experience", component: ActivityExperiencePage, meta: { requiresAuth: true } },
        { path: "account/activity-matches", name: "activity-matches", component: ActivityMatchesPage, meta: { requiresAuth: true } },
        { path: "courses", name: "courses", component: CoursesPage },
        { path: "courses/:slug", name: "course-detail", component: CourseDetailPage },
        { path: "certificates/verify/:verificationToken", name: "course-certificate-verify", component: CertificateVerificationPage },
        { path: "certificates/:verificationToken", name: "course-certificate", component: CertificateVerificationPage },
        { path: "account/courses", name: "account-courses", component: MyCoursesPage, meta: { requiresAuth: true } },
        { path: "account/course-certificates", name: "account-course-certificates", component: CourseCertificatesPage, meta: { requiresAuth: true } },
        { path: "learn/:enrollmentId", name: "course-learning", component: LearningPage, meta: { requiresAuth: true } },
        { path: "learn/:enrollmentId/lessons/:lessonId", name: "course-learning-lesson", component: LearningPage, meta: { requiresAuth: true } },
        { path: "learn/:enrollmentId/exercises/:exerciseId", name: "course-learning-exercise", component: LearningPage, meta: { requiresAuth: true } },
        { path: "counseling", name: "counseling", component: CounselingServicesPage },
        { path: "counseling/:slug", name: "counseling-detail", component: CounselingServicePage },
        { path: "counseling/:slug/book", name: "counseling-book", component: CounselingBookingPage, meta: { requiresAuth: true, requiresVerifiedEmail: true } },
        { path: "account/counseling", name: "account-counseling", component: CounselingAppointmentsPage, meta: { requiresAuth: true } },
        { path: "account/counseling/:appointmentId", name: "account-counseling-detail", component: CounselingAppointmentsPage, meta: { requiresAuth: true } },
        { path: "ai-assistant", name: "ai-assistant", component: AiAssistantPage, meta: { requiresAuth: true } },
        { path: "ai-assistant/:conversationId", name: "ai-assistant-conversation", component: AiAssistantPage, meta: { requiresAuth: true } },
        { path: "ai-assistant/plans", name: "ai-plans", component: CatalogPage, meta: { catalogTitle: "AI 辅导方案", catalogCategory: "ai-coaching" } },
        { path: "account/notifications", name: "account-notifications", component: NotificationsPage, meta: { requiresAuth: true } },
        { path: "account/notification-preferences", name: "account-notification-preferences", component: NotificationsPage, meta: { requiresAuth: true } },
        { path: "account/dating-profile", name: "account-dating-profile", component: DatingProfilePage, meta: { requiresAuth: true, requiresVerifiedEmail: true } },
        { path: "account/dating-profile/edit", name: "account-dating-profile-edit", component: DatingProfilePage, meta: { requiresAuth: true, requiresVerifiedEmail: true } },
        { path: "account/dating-profile/photos", name: "account-dating-profile-photos", component: DatingProfilePage, meta: { requiresAuth: true, requiresVerifiedEmail: true } },
        { path: "account/dating-profile/preferences", name: "account-dating-profile-preferences", component: DatingProfilePage, meta: { requiresAuth: true, requiresVerifiedEmail: true } },
        { path: "account/dating-profile/privacy", name: "account-dating-profile-privacy", component: DatingProfilePage, meta: { requiresAuth: true, requiresVerifiedEmail: true } },
        { path: "account/dating-profile/preview", name: "account-dating-profile-preview", component: DatingProfilePage, meta: { requiresAuth: true, requiresVerifiedEmail: true } },
        { path: "account/dating-profile/review", name: "account-dating-profile-review", component: DatingProfilePage, meta: { requiresAuth: true, requiresVerifiedEmail: true } },
        { path: "recommendations", name: "recommendations", component: RecommendationListPage, meta: { requiresAuth: true } },
        { path: "recommendations/:recommendationItemId", name: "recommendation-detail", component: RecommendationDetailPage, meta: { requiresAuth: true } },
        { path: "account/recommendation-preferences", name: "account-recommendation-preferences", component: RecommendationPreferencesPage, meta: { requiresAuth: true } },
        { path: "account/recommendation-history", name: "account-recommendation-history", component: RecommendationHistoryPage, meta: { requiresAuth: true } },
        { path: "account/recommendation-transparency", name: "account-recommendation-transparency", component: RecommendationTransparencyPage, meta: { requiresAuth: true } },
        { path: "account/profile", name: "account-profile", component: PrivacyCenterPage, meta: { requiresAuth: true } },
        { path: "account/contact-points", name: "account-contact-points", component: PrivacyCenterPage, meta: { requiresAuth: true } },
        { path: "account/privacy", name: "account-privacy", component: PrivacyCenterPage, meta: { requiresAuth: true } },
        { path: "account/consents", name: "account-consents", component: PrivacyCenterPage, meta: { requiresAuth: true } },
        { path: "account/consents/:consentCode", name: "account-consent-detail", component: PrivacyCenterPage, meta: { requiresAuth: true } },
        { path: "account/privacy/requests", name: "account-privacy-requests", component: PrivacyCenterPage, meta: { requiresAuth: true } },
        { path: "account/privacy/requests/:requestId", name: "account-privacy-request-detail", component: PrivacyCenterPage, meta: { requiresAuth: true } },
        { path: "account/privacy/export", name: "account-privacy-export", component: PrivacyCenterPage, meta: { requiresAuth: true } },
        { path: "account/privacy/corrections", name: "account-privacy-corrections", component: PrivacyCenterPage, meta: { requiresAuth: true } },
        { path: "account/privacy/erasure", name: "account-privacy-erasure", component: PrivacyCenterPage, meta: { requiresAuth: true } },
        { path: "account/ai-memory", name: "account-ai-memory", component: PrivacyCenterPage, meta: { requiresAuth: true } },
        { path: "account/email-preferences", redirect: (to) => `/${String(to.params.locale)}/account/notification-preferences` },
        { path: "notifications/unsubscribe/:token", name: "notification-unsubscribe", component: UnsubscribePage },
        { path: "membership", name: "membership", component: CatalogPage, meta: { catalogTitle: "婚恋会员", catalogCategory: "memberships" } },
        { path: "login", redirect: (to) => `/${String(to.params.locale)}/auth/login` },
        { path: "register", redirect: (to) => `/${String(to.params.locale)}/auth/register` },
        { path: "auth/login", name: "login", component: AuthPage, props: { mode: "login" } },
        { path: "auth/register", name: "register", component: AuthPage, props: { mode: "register" } },
        { path: "auth/verify-email", name: "verify-email", component: AuthTokenPage, props: { mode: "verify" } },
        { path: "auth/verification-pending", name: "verification-pending", component: AuthTokenPage, props: { mode: "pending" } },
        { path: "auth/forgot-password", name: "forgot-password", component: AuthTokenPage, props: { mode: "forgot" } },
        { path: "auth/reset-password", name: "reset-password", component: AuthTokenPage, props: { mode: "reset" } },
        { path: "account", name: "account", component: AccountPage, meta: { requiresAuth: true } },
        { path: "account/security", name: "account-security", component: AccountPage, meta: { requiresAuth: true, requiresVerifiedEmail: true } },
        { path: "account/sessions", name: "account-sessions", component: SessionPage, meta: { requiresAuth: true, requiresVerifiedEmail: true } }
      ]
    },
    { path: "/:pathMatch(.*)*", name: "not-found", component: NotFoundPage }
  ]
});

router.beforeEach(async (to) => {
  const locale = to.params.locale;
  if (typeof locale === "string" && supportedLocales.includes(locale as SupportedLocale)) {
    i18n.global.locale.value = locale as SupportedLocale;
    document.documentElement.lang = locale;
  }
  if (to.meta.requiresAuth) {
    const auth = useAuthStore();
    await auth.bootstrap();
    if (!auth.isAuthenticated) {
      return {
        name: "login",
        params: { locale: typeof locale === "string" ? locale : "zh-CN" },
        query: { returnTo: to.fullPath }
      };
    }
    if (to.meta.requiresVerifiedEmail && !auth.user?.email_verified) {
      return {
        name: "verification-pending",
        params: { locale: typeof locale === "string" ? locale : "zh-CN" }
      };
    }
  }
});
