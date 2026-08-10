import { computed, ref } from "vue";

import en from "./locales/en.json";
import zhCN from "./locales/zh-CN.json";
import zhTW from "./locales/zh-TW.json";

export const adminLocales = ["zh-CN", "zh-TW", "en"] as const;
export type AdminLocale = (typeof adminLocales)[number];

type MessageTree = typeof zhCN;
const messages: Record<AdminLocale, MessageTree> = {
  "zh-CN": zhCN,
  "zh-TW": zhTW,
  en
};

function initialLocale(): AdminLocale {
  const cookieLocale = document.cookie
    .split("; ")
    .find((item) => item.startsWith("vav_locale="))
    ?.split("=")[1];
  if (adminLocales.includes(cookieLocale as AdminLocale)) {
    return cookieLocale as AdminLocale;
  }
  return "zh-CN";
}

const locale = ref<AdminLocale>(initialLocale());

function translate(key: string): string {
  const value = key
    .split(".")
    .reduce<unknown>(
      (current, segment) =>
        current && typeof current === "object"
          ? (current as Record<string, unknown>)[segment]
          : undefined,
      messages[locale.value]
    );
  return typeof value === "string" ? value : key;
}

export function useAdminLocale() {
  function setLocale(value: AdminLocale) {
    locale.value = value;
    document.documentElement.lang = value;
    document.cookie = `vav_locale=${value}; Path=/; Max-Age=31536000; SameSite=Lax`;
  }

  return {
    locale: computed(() => locale.value),
    setLocale,
    t: translate
  };
}
