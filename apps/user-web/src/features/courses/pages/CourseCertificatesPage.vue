<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { courseApi, type CourseCertificate } from "../api";

const route = useRoute();
const certificates = ref<CourseCertificate[]>([]);
const error = ref("");

onMounted(async () => {
  try {
    certificates.value = (await courseApi.certificates()).items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "证书加载失败";
  }
});
</script>

<template>
  <section class="catalog-page">
    <p class="eyebrow">
      COURSE CERTIFICATES
    </p>
    <h1>课程证书</h1>
    <p class="privacy-note">
      VAV 证书只证明课程完成，不代表政府、学术或专业资质认证。
    </p>
    <p
      v-if="error"
      role="alert"
      class="form-error"
    >
      {{ error }}
    </p>
    <article
      v-for="certificate in certificates"
      :key="certificate.certificate_number"
      class="commerce-card"
    >
      <h2>{{ certificate.course_title }}</h2>
      <p>
        {{ certificate.status }} · {{ certificate.issued_at }}
      </p>
      <RouterLink
        :to="`/${String(route.params.locale)}/certificates/${encodeURIComponent(certificate.verification_token)}`"
      >
        验证证书
      </RouterLink>
    </article>
    <p v-if="!error && certificates.length === 0">
      暂无课程证书。
    </p>
  </section>
</template>
