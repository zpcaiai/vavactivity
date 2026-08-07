<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { notificationApi } from "../api";

const route = useRoute();
const token = computed(() => String(route.params.token ?? ""));
const valid = ref(false);
const category = ref("");
const status = ref("");
const error = ref("");

onMounted(async () => {
  try {
    const value = await notificationApi.unsubscribePreview(token.value);
    valid.value = value.valid;
    category.value = value.category ?? "";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "Invalid unsubscribe link";
  }
});

async function unsubscribe() {
  try {
    const value = await notificationApi.unsubscribe(token.value);
    status.value = value.status;
    valid.value = false;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "Unable to unsubscribe";
  }
}
</script>

<template>
  <section class="unsubscribe-page page-section">
    <p class="eyebrow">
      VAV · EMAIL PREFERENCES
    </p>
    <h1>邮件退订 / Email unsubscribe</h1>
    <p>此操作只关闭对应的营销邮件，不会注销账户，也不会关闭安全、支付或必要服务通知。</p>
    <p v-if="category">
      Category: {{ category }}
    </p>
    <p
      v-if="status"
      class="form-success"
      role="status"
    >
      Marketing email unsubscribed.
    </p>
    <p
      v-if="error || (!valid && !status)"
      class="form-error"
      role="alert"
    >
      {{ error || "This link is invalid or has already been used." }}
    </p>
    <button
      v-if="valid"
      class="primary-button"
      type="button"
      @click="unsubscribe"
    >
      确认退订营销邮件
    </button>
  </section>
</template>
