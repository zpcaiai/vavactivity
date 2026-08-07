<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { resolveApiBaseUrl } from "@/config/api";

const route = useRoute();
const router = useRouter();
const password = ref("");
const accepted = ref(false);
const busy = ref(false);
const error = ref("");
const baseUrl = resolveApiBaseUrl();

async function submit() {
  if (!accepted.value) {
    error.value = "请先同意服务条款和隐私说明。";
    return;
  }
  busy.value = true;
  error.value = "";
  const response = await fetch(`${baseUrl}/admin/admins/invitations/accept`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      token: String(route.query.token ?? ""),
      password: password.value,
      preferred_locale: "zh-CN",
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      terms_version: "2026-07-01",
      privacy_version: "2026-07-01"
    })
  });
  const payload = (await response.json()) as { error?: { message: string } };
  busy.value = false;
  if (!response.ok) {
    error.value = payload.error?.message ?? "邀请无效";
    return;
  }
  await router.replace("/admin/login");
}
</script>

<template>
  <main class="admin-login">
    <section class="login-card">
      <p class="admin-kicker">
        ADMIN INVITATION
      </p>
      <h1>接受管理员邀请</h1>
      <form @submit.prevent="submit">
        <label>
          设置密码
          <el-input
            v-model="password"
            type="password"
            minlength="12"
            maxlength="128"
            show-password
          />
        </label>
        <label>
          <input
            v-model="accepted"
            type="checkbox"
          >
          我同意服务条款与隐私说明
        </label>
        <el-alert
          v-if="error"
          :title="error"
          type="error"
          :closable="false"
        />
        <el-button
          native-type="submit"
          type="primary"
          :loading="busy"
        >
          激活管理员账户
        </el-button>
      </form>
    </section>
  </main>
</template>
