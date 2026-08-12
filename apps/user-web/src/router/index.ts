import { createRouter, createWebHistory } from "vue-router";
import type { RouteRecordRaw } from "vue-router";

import { i18n, supportedLocales } from "@/i18n";
import type { SupportedLocale } from "@/i18n";

/* Layout shells -------------------------------------------------------------
 * public : marketing site, signed-out visitors and browsing members
 * app    : the member space (persistent sidebar, topbar and mobile tab bar)
 * focus  : single-task full-screen flows (checkout, learning, AI, onboarding)
 * ------------------------------------------------------------------------ */
import LocaleShell from "@/layouts/LocaleShell.vue";

/* Public site */
import HomePage from "@/pages/HomePage.vue";
import LanguageGateway from "@/pages/LanguageGateway.vue";
import NotFoundPage from "@/pages/NotFoundPage.vue";
import CmsPage from "@/features/public-site/pages/CmsPage.vue";
import ContentCollectionPage from "@/features/public-site/pages/ContentCollectionPage.vue";
import ContactPage from "@/features/public-site/pages/ContactPage.vue";
import CatalogPage from "@/features/catalog/pages/CatalogPage.vue";
import ProductDetailPage from "@/features/catalog/pages/ProductDetailPage.vue";
import CartPage from "@/features/commerce/pages/CartPage.vue";
import ActivitiesPage from "@/features/activities/pages/ActivitiesPage.vue";
import ActivityDetailPage from "@/features/activities/pages/ActivityDetailPage.vue";
import CoursesPage from "@/features/courses/pages/CoursesPage.vue";
import CourseDetailPage from "@/features/courses/pages/CourseDetailPage.vue";
import CertificateVerificationPage from "@/features/courses/pages/CertificateVerificationPage.vue";
import CounselingServicesPage from "@/features/counseling/pages/CounselingServicesPage.vue";
import CounselingServicePage from "@/features/counseling/pages/CounselingServicePage.vue";
import PlansPage from "@/features/memberships/pages/PlansPage.vue";
import SafetySupportPage from "@/features/trust-safety/pages/SafetySupportPage.vue";
import SearchPage from "@/features/experience/pages/SearchPage.vue";
import HelpPage from "@/features/experience/pages/HelpPage.vue";
import UnsubscribePage from "@/features/notifications/pages/UnsubscribePage.vue";

/* Auth + focus flows */
import AuthPage from "@/pages/AuthPage.vue";
import AuthTokenPage from "@/pages/AuthTokenPage.vue";
import CheckoutPage from "@/features/commerce/pages/CheckoutPage.vue";
import PaymentProcessingPage from "@/features/commerce/pages/PaymentProcessingPage.vue";
import LearningPage from "@/features/courses/pages/LearningPage.vue";
import AiAssistantPage from "@/features/ai-assistant/pages/AiAssistantPage.vue";
import ActivityExperiencePage from "@/features/activities/pages/ActivityExperiencePage.vue";
import CounselingBookingPage from "@/features/counseling/pages/CounselingBookingPage.vue";
import ProfileOverviewPage from "@/features/dating-profile/pages/ProfileOverviewPage.vue";
import ProfileFieldsPage from "@/features/dating-profile/pages/ProfileFieldsPage.vue";
import ProfilePhotosPage from "@/features/dating-profile/pages/ProfilePhotosPage.vue";
import ProfilePreferencesPage from "@/features/dating-profile/pages/ProfilePreferencesPage.vue";
import ProfilePrivacyPage from "@/features/dating-profile/pages/ProfilePrivacyPage.vue";
import ProfilePreviewPage from "@/features/dating-profile/pages/ProfilePreviewPage.vue";
import ProfileReviewPage from "@/features/dating-profile/pages/ProfileReviewPage.vue";

/* Member space */
import DashboardPage from "@/features/experience/pages/DashboardPage.vue";
import TasksPage from "@/features/experience/pages/TasksPage.vue";
import JourneysPage from "@/features/experience/pages/JourneysPage.vue";
import NotificationsPage from "@/features/notifications/pages/NotificationsPage.vue";
import ActivityRegistrationsPage from "@/features/activities/pages/ActivityRegistrationsPage.vue";
import ActivityMatchesPage from "@/features/activities/pages/ActivityMatchesPage.vue";
import MyCoursesPage from "@/features/courses/pages/MyCoursesPage.vue";
import CourseCertificatesPage from "@/features/courses/pages/CourseCertificatesPage.vue";
import CounselingAppointmentsPage from "@/features/counseling/pages/CounselingAppointmentsPage.vue";
import CommerceListPage from "@/features/commerce/pages/CommerceListPage.vue";
import OrderDetailPage from "@/features/commerce/pages/OrderDetailPage.vue";
import RecommendationListPage from "@/features/recommendations/pages/RecommendationListPage.vue";
import RecommendationDetailPage from "@/features/recommendations/pages/RecommendationDetailPage.vue";
import RecommendationPreferencesPage from "@/features/recommendations/pages/RecommendationPreferencesPage.vue";
import RecommendationHistoryPage from "@/features/recommendations/pages/RecommendationHistoryPage.vue";
import RecommendationTransparencyPage from "@/features/recommendations/pages/RecommendationTransparencyPage.vue";
import MatchesPage from "@/features/matchmaking-interactions/pages/MatchesPage.vue";
import MatchDetailPage from "@/features/matchmaking-interactions/pages/MatchDetailPage.vue";
import InvitationsPage from "@/features/matchmaking-interactions/pages/InvitationsPage.vue";
import InvitationDetailPage from "@/features/matchmaking-interactions/pages/InvitationDetailPage.vue";
import LikesPage from "@/features/matchmaking-interactions/pages/LikesPage.vue";
import SkipsPage from "@/features/matchmaking-interactions/pages/SkipsPage.vue";
import ContactExchangePage from "@/features/matchmaking-interactions/pages/ContactExchangePage.vue";
import RelationshipJourneyPage from "@/features/relationships/pages/RelationshipJourneyPage.vue";
import ProfilePage from "@/features/privacy/pages/ProfilePage.vue";
import PrivacySettingsPage from "@/features/privacy/pages/PrivacySettingsPage.vue";
import ConsentsPage from "@/features/privacy/pages/ConsentsPage.vue";
import DataRequestsPage from "@/features/privacy/pages/DataRequestsPage.vue";
import AiMemoryPage from "@/features/privacy/pages/AiMemoryPage.vue";
import MyMembershipPage from "@/features/memberships/pages/MyMembershipPage.vue";
import BenefitsPage from "@/features/memberships/pages/BenefitsPage.vue";
import UsagePage from "@/features/memberships/pages/UsagePage.vue";
import ManageMembershipPage from "@/features/memberships/pages/ManageMembershipPage.vue";
import MembershipHistoryPage from "@/features/memberships/pages/MembershipHistoryPage.vue";
import SafetyOverviewPage from "@/features/trust-safety/pages/SafetyOverviewPage.vue";
import ReportsPage from "@/features/trust-safety/pages/ReportsPage.vue";
import BlocksPage from "@/features/trust-safety/pages/BlocksPage.vue";
import RestrictionsPage from "@/features/trust-safety/pages/RestrictionsPage.vue";
import AppealsPage from "@/features/trust-safety/pages/AppealsPage.vue";
import AccountPage from "@/pages/AccountPage.vue";
import SessionPage from "@/pages/SessionPage.vue";

import { isSingle } from "@/navigation/ia";
import { useAuthStore } from "@/stores/auth";

const LOCALE_PATH = "/:locale(zh-CN|zh-TW|en)";
const authed = { requiresAuth: true } as const;
const verified = { requiresAuth: true, requiresVerifiedEmail: true } as const;

const publicRoutes: RouteRecordRaw[] = [
  { path: "", name: "home", component: HomePage },
  { path: "about", name: "about", component: CmsPage, meta: { copyKey: "about", cmsSlug: "about" } },
  { path: "stories", name: "stories", component: ContentCollectionPage, meta: { collectionType: "testimonials" } },
  { path: "stories/:slug", name: "story-detail", component: CmsPage, meta: { copyKey: "stories" } },
  { path: "articles", name: "articles", component: ContentCollectionPage, meta: { collectionType: "articles" } },
  { path: "articles/:slug", name: "article-detail", component: CmsPage, meta: { copyKey: "articles" } },
  { path: "services", name: "services", component: CatalogPage, meta: { catalogTitleKey: "catalog.allServices" } },
  { path: "services/:category", name: "service-category", component: CatalogPage, meta: { catalogTitleKey: "catalog.categoryServices" } },
  { path: "products/:slug", name: "product-detail", component: ProductDetailPage },
  { path: "cart", name: "cart", component: CartPage },
  { path: "contact", name: "contact", component: ContactPage },
  { path: "privacy", name: "privacy", component: CmsPage, meta: { copyKey: "about", cmsSlug: "privacy" } },
  { path: "terms", name: "terms", component: CmsPage, meta: { copyKey: "about", cmsSlug: "terms" } },
  { path: "refund-policy", name: "refund-policy", component: CmsPage, meta: { copyKey: "about", cmsSlug: "refund-policy" } },
  { path: "ai-disclaimer", name: "ai-disclaimer", component: CmsPage, meta: { copyKey: "ai", cmsSlug: "ai-disclaimer" } },
  { path: "activities", name: "activities", component: ActivitiesPage },
  { path: "activities/:slug", name: "activity-detail", component: ActivityDetailPage },
  { path: "activities/:slug/register", name: "activity-register", component: ActivityDetailPage, meta: authed },
  { path: "activities/:slug/waitlist", name: "activity-waitlist", component: ActivityDetailPage, meta: authed },
  { path: "courses", name: "courses", component: CoursesPage },
  { path: "courses/:slug", name: "course-detail", component: CourseDetailPage },
  { path: "certificates/verify/:verificationToken", name: "course-certificate-verify", component: CertificateVerificationPage },
  { path: "certificates/:verificationToken", name: "course-certificate", component: CertificateVerificationPage },
  { path: "counseling", name: "counseling", component: CounselingServicesPage },
  { path: "counseling/:slug", name: "counseling-detail", component: CounselingServicePage },
  { path: "ai-assistant/plans", name: "ai-plans", component: CatalogPage, meta: { catalogTitleKey: "catalog.aiPlans", catalogCategory: "ai-coaching" } },
  { path: "membership", name: "membership", component: PlansPage },
  { path: "membership/plans", name: "membership-plans", component: PlansPage },
  { path: "membership/plans/:planCode", name: "membership-plan-detail", component: PlansPage },
  { path: "safety-support", name: "safety-support", component: SafetySupportPage },
  { path: "search", name: "global-search", component: SearchPage },
  { path: "help", name: "help-center", component: HelpPage },
  { path: "notifications/unsubscribe/:token", name: "notification-unsubscribe", component: UnsubscribePage },
  { path: "login", redirect: (to) => `/${String(to.params.locale)}/auth/login` },
  { path: "register", redirect: (to) => `/${String(to.params.locale)}/auth/register` },
  { path: "account/email-preferences", redirect: (to) => `/${String(to.params.locale)}/account/notification-preferences` }
];

const focusRoutes: RouteRecordRaw[] = [
  { path: "auth/login", name: "login", component: AuthPage, props: { mode: "login" }, meta: { focusTitleKey: "auth.loginTitle" } },
  { path: "auth/register", name: "register", component: AuthPage, props: { mode: "register" }, meta: { focusTitleKey: "auth.registerTitle" } },
  { path: "auth/verify-email", name: "verify-email", component: AuthTokenPage, props: { mode: "verify" }, meta: { focusTitleKey: "auth.verifyTitle" } },
  { path: "auth/verification-pending", name: "verification-pending", component: AuthTokenPage, props: { mode: "pending" }, meta: { focusTitleKey: "auth.verifyTitle" } },
  { path: "auth/forgot-password", name: "forgot-password", component: AuthTokenPage, props: { mode: "forgot" }, meta: { focusTitleKey: "auth.forgotTitle" } },
  { path: "auth/reset-password", name: "reset-password", component: AuthTokenPage, props: { mode: "reset" }, meta: { focusTitleKey: "auth.resetTitle" } },
  { path: "checkout", name: "checkout", component: CheckoutPage, meta: { ...verified, focusTitleKey: "focus.checkout" } },
  { path: "checkout/processing", name: "checkout-processing", component: PaymentProcessingPage, meta: { ...authed, focusTitleKey: "focus.payment" } },
  { path: "counseling/:slug/book", name: "counseling-book", component: CounselingBookingPage, meta: { ...verified, focusTitleKey: "focus.counselingBooking" } },
  { path: "learn/:enrollmentId", name: "course-learning", component: LearningPage, meta: { ...authed, focusTitleKey: "focus.learning" } },
  { path: "learn/:enrollmentId/lessons/:lessonId", name: "course-learning-lesson", component: LearningPage, meta: { ...authed, focusTitleKey: "focus.learning" } },
  { path: "learn/:enrollmentId/exercises/:exerciseId", name: "course-learning-exercise", component: LearningPage, meta: { ...authed, focusTitleKey: "focus.learning" } },
  { path: "ai-assistant", name: "ai-assistant", component: AiAssistantPage, meta: { ...authed, focusTitleKey: "focus.ai" } },
  { path: "ai-assistant/:conversationId", name: "ai-assistant-conversation", component: AiAssistantPage, meta: { ...authed, focusTitleKey: "focus.ai" } },
  { path: "account/activities/:activityId", name: "activity-experience", component: ActivityExperiencePage, meta: { ...authed, focusTitleKey: "focus.activityExperience" } },
  { path: "account/dating-profile/edit", name: "account-dating-profile-edit", component: ProfileFieldsPage, meta: { ...verified, focusTitleKey: "focus.datingProfile" } },
  { path: "account/dating-profile/photos", name: "account-dating-profile-photos", component: ProfilePhotosPage, meta: { ...verified, focusTitleKey: "focus.datingProfile" } },
  { path: "account/dating-profile/preferences", name: "account-dating-profile-preferences", component: ProfilePreferencesPage, meta: { ...verified, focusTitleKey: "focus.datingProfile" } },
  { path: "account/dating-profile/privacy", name: "account-dating-profile-privacy", component: ProfilePrivacyPage, meta: { ...verified, focusTitleKey: "focus.datingProfile" } },
  { path: "account/dating-profile/preview", name: "account-dating-profile-preview", component: ProfilePreviewPage, meta: { ...verified, focusTitleKey: "focus.datingProfile" } },
  { path: "account/dating-profile/review", name: "account-dating-profile-review", component: ProfileReviewPage, meta: { ...verified, focusTitleKey: "focus.datingProfile" } }
];

const appRoutes: RouteRecordRaw[] = [
  { path: "account", name: "account", component: AccountPage, meta: authed },
  { path: "account/home", name: "experience-home", component: DashboardPage, meta: authed },
  { path: "account/tasks", name: "account-tasks", component: TasksPage, meta: authed },
  { path: "account/journeys", name: "account-journeys", component: JourneysPage, meta: authed },
  { path: "account/notifications", name: "account-notifications", component: NotificationsPage, meta: authed },
  { path: "account/notification-preferences", name: "account-notification-preferences", component: NotificationsPage, meta: authed },

  { path: "account/activity-registrations", name: "activity-registrations", component: ActivityRegistrationsPage, meta: authed },
  { path: "account/activities", name: "account-activities", component: ActivityRegistrationsPage, meta: authed },
  { path: "account/activity-matches", name: "activity-matches", component: ActivityMatchesPage, meta: authed },
  { path: "account/courses", name: "account-courses", component: MyCoursesPage, meta: authed },
  { path: "account/course-certificates", name: "account-course-certificates", component: CourseCertificatesPage, meta: authed },
  { path: "account/counseling", name: "account-counseling", component: CounselingAppointmentsPage, meta: authed },
  { path: "account/counseling/:appointmentId", name: "account-counseling-detail", component: CounselingAppointmentsPage, meta: authed },

  { path: "account/orders", name: "account-orders", component: CommerceListPage, meta: { ...authed, commerceKind: "orders" } },
  { path: "account/orders/:orderNumber", name: "account-order-detail", component: OrderDetailPage, meta: authed },
  { path: "account/subscriptions", name: "account-subscriptions", component: CommerceListPage, meta: { ...authed, commerceKind: "subscriptions" } },
  { path: "account/entitlements", name: "account-entitlements", component: CommerceListPage, meta: { ...authed, commerceKind: "entitlements" } },
  { path: "account/membership", name: "account-membership", component: MyMembershipPage, meta: authed },
  { path: "account/membership/benefits", name: "account-membership-benefits", component: BenefitsPage, meta: authed },
  { path: "account/membership/usage", name: "account-membership-usage", component: UsagePage, meta: authed },
  { path: "account/membership/manage", name: "account-membership-manage", component: ManageMembershipPage, meta: authed },
  { path: "account/membership/history", name: "account-membership-history", component: MembershipHistoryPage, meta: authed },

  { path: "account/dating-profile", name: "account-dating-profile", component: ProfileOverviewPage, meta: verified },
  { path: "recommendations", name: "recommendations", component: RecommendationListPage, meta: { ...authed, requiresSingle: true } },
  { path: "recommendations/:recommendationItemId", name: "recommendation-detail", component: RecommendationDetailPage, meta: { ...authed, requiresSingle: true } },
  { path: "account/recommendation-preferences", name: "account-recommendation-preferences", component: RecommendationPreferencesPage, meta: authed },
  { path: "account/recommendation-history", name: "account-recommendation-history", component: RecommendationHistoryPage, meta: authed },
  { path: "account/recommendation-transparency", name: "account-recommendation-transparency", component: RecommendationTransparencyPage, meta: authed },

  { path: "account/matchmaking/likes", name: "account-matchmaking-likes", component: LikesPage, meta: verified },
  { path: "account/matchmaking/skips", name: "account-matchmaking-skips", component: SkipsPage, meta: verified },
  { path: "account/matchmaking/matches", name: "account-matchmaking-matches", component: MatchesPage, meta: verified },
  { path: "account/matchmaking/matches/:id", name: "account-matchmaking-match-detail", component: MatchDetailPage, meta: verified },
  { path: "account/matchmaking/invitations", name: "account-matchmaking-invitations", component: InvitationsPage, meta: verified },
  { path: "account/matchmaking/invitations/:id", name: "account-matchmaking-invitation-detail", component: InvitationDetailPage, meta: verified },
  { path: "account/matchmaking/contact-exchanges/:id", name: "account-matchmaking-contact-exchange", component: ContactExchangePage, meta: verified },

  { path: "account/relationships", name: "account-relationships", component: RelationshipJourneyPage, meta: verified },
  { path: "account/relationships/:id", name: "account-relationship-detail", component: RelationshipJourneyPage, meta: verified },
  { path: "account/relationships/:id/stage", name: "account-relationship-stage", component: RelationshipJourneyPage, meta: verified },
  { path: "account/relationships/:id/milestones", name: "account-relationship-milestones", component: RelationshipJourneyPage, meta: verified },
  { path: "account/relationships/:id/checkins", name: "account-relationship-checkins", component: RelationshipJourneyPage, meta: verified },
  { path: "account/relationships/:id/reflections", name: "account-relationship-reflections", component: RelationshipJourneyPage, meta: verified },

  { path: "account/profile", name: "account-profile", component: ProfilePage, meta: authed },
  { path: "account/contact-points", name: "account-contact-points", component: ProfilePage, meta: authed },
  { path: "account/privacy", name: "account-privacy", component: PrivacySettingsPage, meta: authed },
  { path: "account/consents", name: "account-consents", component: ConsentsPage, meta: authed },
  { path: "account/consents/:consentCode", name: "account-consent-detail", component: ConsentsPage, meta: authed },
  { path: "account/privacy/requests", name: "account-privacy-requests", component: DataRequestsPage, meta: authed },
  { path: "account/privacy/requests/:requestId", name: "account-privacy-request-detail", component: DataRequestsPage, meta: authed },
  { path: "account/privacy/export", name: "account-privacy-export", component: DataRequestsPage, meta: authed },
  { path: "account/privacy/corrections", name: "account-privacy-corrections", component: DataRequestsPage, meta: authed },
  { path: "account/privacy/erasure", name: "account-privacy-erasure", component: DataRequestsPage, meta: authed },
  { path: "account/ai-memory", name: "account-ai-memory", component: AiMemoryPage, meta: authed },

  { path: "account/safety", name: "account-safety", component: SafetyOverviewPage, meta: authed },
  { path: "account/safety/reports", name: "account-safety-reports", component: ReportsPage, meta: authed },
  { path: "account/safety/blocks", name: "account-safety-blocks", component: BlocksPage, meta: authed },
  { path: "account/safety/restrictions", name: "account-safety-restrictions", component: RestrictionsPage, meta: authed },
  { path: "account/safety/appeals", name: "account-safety-appeals", component: AppealsPage, meta: authed },

  { path: "account/security", name: "account-security", component: AccountPage, meta: verified },
  { path: "account/sessions", name: "account-sessions", component: SessionPage, meta: verified }
];

function withLayout(routes: RouteRecordRaw[], layout: "app" | "focus" | "public"): RouteRecordRaw[] {
  return routes.map((route) => ({ ...route, meta: { ...route.meta, layout } }) as RouteRecordRaw);
}

export const router = createRouter({
  history: createWebHistory(),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    { path: "/", name: "language", component: LanguageGateway },
    {
      path: LOCALE_PATH,
      component: LocaleShell,
      children: [
        ...withLayout(appRoutes, "app"),
        ...withLayout(focusRoutes, "focus"),
        ...withLayout(publicRoutes, "public")
      ]
    },
    { path: "/:pathMatch(.*)*", name: "not-found", component: NotFoundPage }
  ]
});

router.beforeEach(async (to) => {
  const locale = to.params.locale;
  const fallbackLocale = typeof locale === "string" ? locale : "zh-CN";
  if (typeof locale === "string" && supportedLocales.includes(locale as SupportedLocale)) {
    i18n.global.locale.value = locale as SupportedLocale;
    document.documentElement.lang = locale;
  }

  if (!to.meta.requiresAuth) return;

  const auth = useAuthStore();
  await auth.bootstrap();
  if (!auth.isAuthenticated) {
    return { name: "login", params: { locale: fallbackLocale }, query: { returnTo: to.fullPath } };
  }
  if (to.meta.requiresVerifiedEmail && !auth.user?.email_verified) {
    return { name: "verification-pending", params: { locale: fallbackLocale } };
  }
  // V1.6: matchmaking is single-only. The IA hides it, the guard closes it and
  // the API rejects it — three independent layers, as the requirement asks.
  if (
    to.meta.requiresSingle &&
    !isSingle({
      relationshipStatus: (auth.user as { relationship_status?: string } | null)?.relationship_status,
      emailVerified: Boolean(auth.user?.email_verified)
    })
  ) {
    return { name: "experience-home", params: { locale: fallbackLocale } };
  }
  return;
});
