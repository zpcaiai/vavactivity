<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { useAuthStore } from "@/stores/auth";

const props = defineProps<{ mode: "login" | "register" }>();
const route = useRoute();
const router = useRouter();
const { t } = useI18n();
const auth = useAuthStore();
const locale = computed(() => String(route.params.locale));
const title = computed(() =>
  props.mode === "login" ? t("auth.loginTitle") : t("auth.registerTitle")
);
const email = ref("");
const password = ref("");
const accepted = ref(false);
const busy = ref(false);
const error = ref("");
const complete = ref(false);

async function submit() {
  busy.value = true;
  error.value = "";
  try {
    if (props.mode === "login") {
      await auth.login(email.value, password.value);
      await router.replace(`/${locale.value}/account/security`);
    } else {
      if (!accepted.value) {
        throw new Error("请先阅读并同意服务条款与隐私说明。");
      }
      await auth.register({
        email: email.value,
        password: password.value,
        preferred_locale: locale.value,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        terms_version: "2026-07-01",
        privacy_version: "2026-07-01"
      });
      complete.value = true;
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "请求失败，请稍后重试。";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="auth-page">
    <div class="auth-card">
      <span
        class="brand-mark"
        aria-hidden="true"
      >V</span>
      <p class="eyebrow">
        VAV ACCOUNT
      </p>
      <h1>{{ title }}</h1>
      <div
        v-if="complete"
        class="auth-success"
        role="status"
      >
        <h2>请查收验证邮件</h2>
        <p>验证链接仅可使用一次，并会在 24 小时后失效。</p>
      </div>
      <form
        v-else
        class="auth-form"
        @submit.prevent="submit"
      >
        <label>
          {{ mode === "login" ? "邮箱或账号" : "邮箱" }}
          <input
            v-model.trim="email"
            :type="mode === 'login' ? 'text' : 'email'"
            :autocomplete="mode === 'login' ? 'username' : 'email'"
            required
          >
        </label>
        <label>
          密码
          <input
            v-model="password"
            type="password"
            :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
            :minlength="mode === 'register' ? 12 : undefined"
            maxlength="128"
            required
          >
        </label>
        <p
          v-if="mode === 'login'"
          class="auth-hint"
        >
          测试账号：test / test
        </p>
        <label
          v-if="mode === 'register'"
          class="checkbox-row"
        >
          <input
            v-model="accepted"
            type="checkbox"
          >
          我已阅读并同意服务条款与隐私说明
        </label>
        <p
          v-if="error"
          class="form-error"
          role="alert"
        >
          {{ error }}
        </p>
        <button
          class="primary-button"
          type="submit"
          :disabled="busy"
        >
          {{ busy ? "处理中…" : title }}
        </button>
      </form>
      <nav class="auth-links">
        <RouterLink
          v-if="mode === 'login'"
          :to="`/${locale}/auth/forgot-password`"
        >
          忘记密码
        </RouterLink>
        <RouterLink :to="`/${locale}/${mode === 'login' ? 'auth/register' : 'auth/login'}`">
          {{ mode === "login" ? "创建账户" : "已有账户，前往登录" }}
        </RouterLink>
      </nav>
    </div>
  </section>
</template>
