<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { courseApi, type PublicCourse } from "../api";

const route = useRoute();
const router = useRouter();
const course = ref<PublicCourse>();
const loading = ref(true);
const enrolling = ref(false);
const error = ref("");

function priceLabel() {
  const price = course.value?.prices?.[0];
  if (!price) return course.value?.free_enrollment ? "免费" : "价格以商品中心为准";
  return new Intl.NumberFormat(String(route.params.locale), {
    style: "currency",
    currency: price.currency
  }).format(price.unit_amount_minor / 100);
}

async function load() {
  try {
    course.value = await courseApi.detail(String(route.params.slug), String(route.params.locale));
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "课程加载失败";
  } finally {
    loading.value = false;
  }
}

async function enroll() {
  if (!course.value) return;
  enrolling.value = true;
  error.value = "";
  try {
    const enrollment = await courseApi.enroll(course.value.id);
    await router.push(`/${String(route.params.locale)}/learn/${enrollment.id}`);
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : "报名失败";
    if (message.toLowerCase().includes("authentication")) {
      await router.push({
        name: "login",
        params: { locale: route.params.locale },
        query: { returnTo: route.fullPath }
      });
    } else {
      error.value = message;
    }
  } finally {
    enrolling.value = false;
  }
}

onMounted(() => void load());
</script>

<template>
  <section
    v-if="course"
    class="catalog-page course-detail"
  >
    <p class="eyebrow">
      {{ course.course_type }} · {{ course.status }}
    </p>
    <h1>{{ course.title }}</h1>
    <p>{{ course.subtitle }}</p>
    <p>{{ course.summary }}</p>
    <div class="commerce-card">
      <strong>{{ priceLabel() }}</strong>
      <p v-if="course.access_duration_days">
        访问期限：{{ course.access_duration_days }} 天
      </p>
      <p v-else>
        访问期限以购买权益或免费课程政策为准
      </p>
    </div>
    <div
      v-if="course.learning_outcomes?.length"
      class="commerce-card"
    >
      <strong>学习目标</strong>
      <ul>
        <li
          v-for="(outcome, index) in course.learning_outcomes"
          :key="index"
        >
          {{ outcome.text }}
        </li>
      </ul>
    </div>
    <div class="commerce-card">
      <strong>课程目录</strong>
      <div
        v-for="module in course.modules"
        :key="module.id"
      >
        <h2>{{ module.title }}</h2>
        <p
          v-for="lesson in module.lessons"
          :key="lesson.id"
        >
          {{ lesson.title }} · {{ lesson.lesson_type }}
          <span v-if="lesson.preview_policy !== 'none'"> · 可预览</span>
        </p>
      </div>
    </div>
    <button
      v-if="course.free_enrollment"
      type="button"
      :disabled="enrolling"
      @click="enroll"
    >
      {{ enrolling ? "正在开通…" : "免费加入课程" }}
    </button>
    <RouterLink
      v-else-if="course.catalog_product_id"
      :to="`/${String(route.params.locale)}/services`"
    >
      前往统一商品中心购买
    </RouterLink>
    <p class="privacy-note">
      支付返回页面不会直接开通课程；请以“我的课程”中的权益结果为准。
    </p>
    <p
      v-if="error"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>
  </section>
  <p
    v-else-if="loading"
    role="status"
  >
    正在加载课程…
  </p>
  <p
    v-else
    class="form-error"
  >
    {{ error }}
  </p>
</template>
