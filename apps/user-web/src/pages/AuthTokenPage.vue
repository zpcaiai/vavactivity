<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { resolveApiBaseUrl } from "@/config/api";

const props = defineProps<{
  mode: "verify" | "forgot" | "reset" | "pending";
}>();
const route = useRoute();
const baseUrl = resolveApiBaseUrl();
const email = ref("");
const password = ref("");
const busy = ref(false);
const message = ref("");
const error = ref("");
const token = computed(() => String(route.query.token ?? ""));

async function request(path: string, body: object) {
  const response = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  const payload = (await response.json()) as {
    data?: { message?: string };
    error?: { message?: string };
  };
  if (!response.ok) {
    throw new Error(payload.error?.message ?? "请求失败");
  }
  return payload;
}

async function verify() {
  busy.value = true;
  try {
    await request("/auth/email-verification/confirm", { token: token.value });
    message.value = "邮箱已验证，现在可以登录。";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "验证失败";
  } finally {
    busy.value = false;
  }
}

async function submit() {
  busy.value = true;
  error.value = "";
  try {
    if (props.mode === "forgot") {
      const result = await request("/auth/password/forgot", { email: email.value });
      message.value =
        result.data?.message ?? "如果账户符合条件，我们会发送密码重置邮件。";
    } else {
      await request("/auth/password/reset", {
        token: token.value,
        new_password: password.value
      });
      message.value = "密码已重置，所有旧设备会话均已撤销。";
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "请求失败";
  } finally {
    busy.value = false;
  }
}

onMounted(() => {
  if (props.mode === "verify" && token.value) {
    void verify();
  }
});
</script>

<template>
  <section class="auth-page">
    <div class="auth-card">
      <p class="eyebrow">
        ACCOUNT SECURITY
      </p>
      <h1>
        {{
          mode === "verify"
            ? "验证邮箱"
            : mode === "forgot"
              ? "找回密码"
              : mode === "reset"
                ? "重置密码"
                : "等待邮箱验证"
        }}
      </h1>
      <p
        v-if="message"
        role="status"
      >
        {{ message }}
      </p>
      <p
        v-if="error"
        class="form-error"
        role="alert"
      >
        {{ error }}
      </p>
      <form
        v-if="mode === 'forgot' || mode === 'reset'"
        class="auth-form"
        @submit.prevent="submit"
      >
        <label v-if="mode === 'forgot'">
          邮箱
          <input
            v-model.trim="email"
            type="email"
            required
          >
        </label>
        <label v-else>
          新密码
          <input
            v-model="password"
            type="password"
            minlength="12"
            maxlength="128"
            required
          >
        </label>
        <button
          class="primary-button"
          :disabled="busy"
        >
          {{ busy ? "处理中…" : "继续" }}
        </button>
      </form>
    </div>
  </section>
</template>
