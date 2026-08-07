<script setup lang="ts">
import { ref } from "vue";
import { useRoute } from "vue-router";
import { resolveApiBaseUrl } from "@/config/api";

const route = useRoute();
const baseUrl = resolveApiBaseUrl();
const startedAt = new Date().toISOString();
const form = ref({
  name: "",
  email: "",
  region: "",
  subject: "",
  message: "",
  consent: false,
  website: ""
});
const message = ref("");
const error = ref("");

async function submit() {
  error.value = "";
  if (!form.value.consent) {
    error.value = "请先确认隐私同意。";
    return;
  }
  const response = await fetch(`${baseUrl}/public/contact-submissions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      submission_type: "cooperation",
      name: form.value.name,
      email: form.value.email,
      region: form.value.region || null,
      subject: form.value.subject || null,
      message: form.value.message,
      locale: String(route.params.locale),
      privacy_consent_version: "2026-07-01",
      source_page: route.fullPath,
      website: form.value.website,
      form_started_at: startedAt
    })
  });
  const payload = (await response.json()) as { error?: { message: string } };
  if (!response.ok) {
    error.value = payload.error?.message ?? "提交失败";
    return;
  }
  message.value = "已收到你的联系信息。运营人员会按流程处理；我们不会自动订阅营销邮件。";
}
</script>

<template>
  <section class="editorial-page">
    <article>
      <p class="eyebrow">
        CONTACT & COOPERATION
      </p>
      <h1>合作联系</h1>
      <form
        class="auth-form contact-form"
        @submit.prevent="submit"
      >
        <label>姓名<input
          v-model="form.name"
          required
          maxlength="160"
        ></label>
        <label>邮箱<input
          v-model="form.email"
          type="email"
          required
        ></label>
        <label>所在地区<input
          v-model="form.region"
          maxlength="128"
        ></label>
        <label>联系主题<input
          v-model="form.subject"
          maxlength="300"
        ></label>
        <label>消息<textarea
          v-model="form.message"
          required
          minlength="10"
          maxlength="5000"
          rows="7"
        /></label>
        <label class="honeypot">Website<input
          v-model="form.website"
          tabindex="-1"
          autocomplete="off"
        ></label>
        <label class="checkbox-row"><input
          v-model="form.consent"
          type="checkbox"
        >我同意按照隐私说明处理本次联系资料</label>
        <p
          v-if="error"
          class="form-error"
          role="alert"
        >
          {{ error }}
        </p>
        <p
          v-if="message"
          role="status"
        >
          {{ message }}
        </p>
        <button class="primary-button">
          提交联系
        </button>
      </form>
    </article>
  </section>
</template>
