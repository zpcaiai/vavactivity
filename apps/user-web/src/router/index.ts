import { createRouter, createWebHistory } from "vue-router";

import { i18n, supportedLocales } from "@/i18n";
import type { SupportedLocale } from "@/i18n";

import AccountPage from "@/pages/AccountPage.vue";
import AuthPage from "@/pages/AuthPage.vue";
import ContentPage from "@/pages/ContentPage.vue";
import HomePage from "@/pages/HomePage.vue";
import LanguageGateway from "@/pages/LanguageGateway.vue";
import NotFoundPage from "@/pages/NotFoundPage.vue";
import PublicLayout from "@/layouts/PublicLayout.vue";

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
        { path: "about", name: "about", component: ContentPage, meta: { copyKey: "about" } },
        { path: "stories", name: "stories", component: ContentPage, meta: { copyKey: "stories" } },
        { path: "articles", name: "articles", component: ContentPage, meta: { copyKey: "articles" } },
        { path: "activities", name: "activities", component: ContentPage, meta: { copyKey: "activities" } },
        { path: "courses", name: "courses", component: ContentPage, meta: { copyKey: "courses" } },
        { path: "counseling", name: "counseling", component: ContentPage, meta: { copyKey: "counseling" } },
        { path: "ai-assistant", name: "ai-assistant", component: ContentPage, meta: { copyKey: "ai" } },
        { path: "login", name: "login", component: AuthPage, props: { mode: "login" } },
        { path: "register", name: "register", component: AuthPage, props: { mode: "register" } },
        { path: "account", name: "account", component: AccountPage }
      ]
    },
    { path: "/:pathMatch(.*)*", name: "not-found", component: NotFoundPage }
  ]
});

router.beforeEach((to) => {
  const locale = to.params.locale;
  if (typeof locale === "string" && supportedLocales.includes(locale as SupportedLocale)) {
    i18n.global.locale.value = locale as SupportedLocale;
    document.documentElement.lang = locale;
  }
});

