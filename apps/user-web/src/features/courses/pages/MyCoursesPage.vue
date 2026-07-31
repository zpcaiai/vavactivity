<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import {
  courseApi,
  type CourseCertificate,
  type Enrollment
} from "../api";

const route = useRoute();
const locale = computed(() => String(route.params.locale));
const enrollments = ref<Enrollment[]>([]);
const certificates = ref<CourseCertificate[]>([]);
const loading = ref(true);
const error = ref("");

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [courseResult, certificateResult] = await Promise.all([
      courseApi.enrollments(),
      courseApi.certificates()
    ]);
    enrollments.value = courseResult.items;
    certificates.value = certificateResult.items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "课程记录加载失败";
  } finally {
    loading.value = false;
  }
}

function sourceLabel(source: string) {
  const labels: Record<string, string> = {
    free_enrollment: "免费报名",
    purchase: "购买",
    bundle_purchase: "套餐购买",
    membership: "会员权益",
    admin_grant: "运营授权"
  };
  return labels[source] ?? source;
}

onMounted(() => void load());
</script>

<template>
  <section class="catalog-page">
    <p class="eyebrow">
      MY COURSES
    </p>
    <h1>我的课程</h1>
    <p>课程会固定到报名时的已发布版本，后续内容变更不会悄悄改写你的学习记录。</p>
    <p
      v-if="loading"
      role="status"
    >
      正在加载课程记录…
    </p>
    <p
      v-if="error"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>
    <div
      v-if="!loading && enrollments.length"
      class="commerce-list"
    >
      <article
        v-for="enrollment in enrollments"
        :key="enrollment.id"
        class="commerce-card"
      >
        <div>
          <small>{{ sourceLabel(enrollment.source_type) }} · {{ enrollment.status }}</small>
          <strong>{{ enrollment.course?.title ?? "课程" }}</strong>
          <small>固定版本：{{ enrollment.course_version_id }}</small>
        </div>
        <RouterLink
          class="primary-button"
          :to="`/${locale}/learn/${enrollment.id}`"
        >
          继续学习
        </RouterLink>
      </article>
    </div>
    <p v-else-if="!loading && !error">
      还没有课程，先去课程目录看看。
      <RouterLink :to="`/${locale}/courses`">
        浏览课程
      </RouterLink>
    </p>

    <h2>完成证书</h2>
    <p class="privacy-note">
      证书仅证明 VAV 课程完成，不代表政府、学术或专业资质认证。
    </p>
    <div
      v-if="certificates.length"
      class="commerce-list"
    >
      <article
        v-for="certificate in certificates"
        :key="certificate.certificate_number"
        class="commerce-card"
      >
        <div>
          <small>{{ certificate.status }} · {{ certificate.issued_at }}</small>
          <strong>{{ certificate.course_title }}</strong>
          <small>{{ certificate.certificate_number }}</small>
        </div>
        <RouterLink
          :to="`/${locale}/certificates/verify/${certificate.verification_token}`"
        >
          验证证书
        </RouterLink>
      </article>
    </div>
    <p v-else-if="!loading">
      完成符合要求的课程后，证书会显示在这里。
    </p>
  </section>
</template>
