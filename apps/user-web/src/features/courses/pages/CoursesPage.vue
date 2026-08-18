<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { courseApi, type PublicCourse } from "../api";

const route = useRoute();
const courses = ref<PublicCourse[]>([]);
const loading = ref(true);
const error = ref("");

async function load() {
  loading.value = true;
  error.value = "";
  try {
    courses.value = (await courseApi.list(String(route.params.locale))).items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "课程加载失败";
  } finally {
    loading.value = false;
  }
}

onMounted(() => void load());
watch(() => route.params.locale, () => void load());
</script>

<template>
  <section class="catalog-page course-page">
    <header class="catalog-heading">
      <div>
        <p class="eyebrow">
          VAV LEARNING
        </p>
        <h1>课程中心</h1>
        <p>课程购买沿用统一商品与订单；学习权限只由服务端权益状态确认。</p>
      </div>
    </header>
    <p
      v-if="loading"
      role="status"
    >
      正在加载课程…
    </p>
    <p
      v-else-if="error"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>
    <div
      v-else
      class="product-grid"
    >
      <article
        v-for="course in courses"
        :key="course.id"
        class="product-card"
      >
        <p class="eyebrow">
          {{ course.course_type }} · {{ course.difficulty_level ?? "all levels" }}
        </p>
        <h2>{{ course.title }}</h2>
        <p>{{ course.summary }}</p>
        <p v-if="course.estimated_duration_minutes">
          {{ course.estimated_duration_minutes }} 分钟
        </p>
        <RouterLink :to="`/${String(route.params.locale)}/courses/${course.slug}`">
          查看课程
        </RouterLink>
      </article>
    </div>
  </section>
</template>
