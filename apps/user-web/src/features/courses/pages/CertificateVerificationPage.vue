<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { courseApi, type CourseCertificate } from "../api";

const route = useRoute();
const certificate = ref<Omit<CourseCertificate, "verification_token">>();
const loading = ref(true);
const error = ref("");

async function verify() {
  try {
    certificate.value = await courseApi.verifyCertificate(
      String(route.params.verificationToken)
    );
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "无法验证此证书";
  } finally {
    loading.value = false;
  }
}

onMounted(() => void verify());
</script>

<template>
  <section class="catalog-page">
    <p class="eyebrow">
      COURSE COMPLETION RECORD
    </p>
    <h1>课程完成记录验证</h1>
    <p
      v-if="loading"
      role="status"
    >
      正在验证…
    </p>
    <p
      v-if="error"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>
    <article
      v-if="certificate"
      class="commerce-card"
    >
      <div>
        <small>{{ certificate.status }}</small>
        <strong>{{ certificate.course_title }}</strong>
        <span>持有人：{{ certificate.recipient_name }}</span>
        <span>签发时间：{{ certificate.issued_at }}</span>
        <small>编号：{{ certificate.certificate_number }}</small>
      </div>
    </article>
    <p class="privacy-note">
      此记录仅证明 VAV 课程完成，不代表政府、学术或专业资质认证。
    </p>
  </section>
</template>
