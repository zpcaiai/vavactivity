<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { useAdminAuthStore } from "@/stores/admin-auth";

const auth = useAdminAuthStore();
const route = useRoute();
const router = useRouter();
const email = ref("admin");
const password = ref("admin");
const busy = ref(false);
const error = ref("");

async function submit() {
  busy.value = true;
  error.value = "";
  try {
    await auth.login(email.value, password.value);
    const returnTo =
      typeof route.query.returnTo === "string" ? route.query.returnTo : "/admin/dashboard";
    await router.replace(returnTo);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "登录失败";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="admin-login">
    <section class="login-story">
      <span
        class="brand-mark login-mark"
        aria-hidden="true"
      >V</span>
      <p class="admin-kicker">
        VAV OPERATIONS
      </p>
      <h1>让每一次运营动作，都有边界和记录。</h1>
      <p>
        管理端与用户端使用不同 Token Audience。所有菜单与敏感操作都由后端权限再次确认。
      </p>
    </section>
    <section class="login-card">
      <span class="login-status">SECURE ACCESS</span>
      <h2>超级管理员登录</h2>
      <form @submit.prevent="submit">
        <label>
          超级管理员邮箱
          <el-input
            v-model="email"
            type="text"
            autocomplete="username"
            placeholder="admin@example.com"
          />
        </label>
        <label>
          密码
          <el-input
            v-model="password"
            type="password"
            autocomplete="current-password"
            show-password
          />
        </label>
        <el-alert
          v-if="error"
          :title="error"
          type="error"
          :closable="false"
          show-icon
        />
        <el-button
          native-type="submit"
          type="primary"
          :loading="busy"
        >
          安全登录
        </el-button>
      </form>
      <RouterLink
        class="preview-link"
        to="/admin/accept-invitation"
      >
        接受管理员邀请
      </RouterLink>
    </section>
  </main>
</template>
