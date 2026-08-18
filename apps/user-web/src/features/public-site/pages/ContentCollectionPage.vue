<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { useSeo } from "@/composables/useSeo";
import { listArticles, listTestimonials } from "../api/content";
import type { PublicContent } from "../types";

const route = useRoute();

/**
 * The card eyebrow used to print `item.locale` — "ZH-CN" on every card, which
 * says nothing to a reader. The publication date is the useful thing a
 * collection card can carry there.
 */
function publishedOn(item: PublicContent): string {
  if (!item.published_at) return "";
  const date = new Date(item.published_at);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleDateString(String(route.params.locale ?? "zh-CN"), {
      year: "numeric",
      month: "long",
      day: "numeric"
    });
}
const locale = computed(() => String(route.params.locale ?? "zh-CN"));
const kind = computed(() => String(route.meta.collectionType ?? "articles"));
const title = computed(() => kind.value === "testimonials" ? "幸福见证" : "文章");
const items = ref<PublicContent[]>([]);
const loading = ref(true);
const error = ref("");

useSeo(computed(() => ({
  title: `${title.value} · VAV`,
  description: kind.value === "testimonials"
    ? "仅展示已取得明确授权并通过隐私审查的真实见证。"
    : "VAV 婚恋成长、沟通边界与信仰生活文章。"
})));

async function load() {
  loading.value = true;
  error.value = "";
  try {
    items.value = kind.value === "testimonials"
      ? await listTestimonials(locale.value)
      : await listArticles(locale.value);
  } catch {
    error.value = "内容列表暂时无法加载，请稍后重试。";
  } finally {
    loading.value = false;
  }
}

onMounted(() => void load());
watch([locale, kind], () => void load());
</script>

<template>
  <section class="editorial-page collection-page">
    <header>
      <p class="eyebrow">
        VAV EDITORIAL
      </p>
      <h1>{{ title }}</h1>
      <p v-if="kind === 'testimonials'">
        仅展示已取得明确授权并通过隐私审查的真实内容。
      </p>
    </header>
    <p
      v-if="loading"
      role="status"
    >
      正在加载…
    </p>
    <p
      v-else-if="error"
      role="alert"
    >
      {{ error }}
    </p>
    <div
      v-else-if="items.length"
      class="editorial-grid"
    >
      <article
        v-for="item in items"
        :key="item.id"
      >
        <p class="eyebrow">
          {{ publishedOn(item) }}
        </p>
        <h2>{{ item.title }}</h2>
        <p>{{ item.excerpt }}</p>
        <RouterLink
          :to="`/${locale}/${kind === 'testimonials' ? 'stories' : 'articles'}/${item.canonical_slug}`"
        >
          阅读全文
        </RouterLink>
      </article>
    </div>
    <div
      v-else
      class="catalog-empty"
    >
      <h2>尚无已发布内容</h2>
      <p>草稿、未审核内容和未获授权的见证不会公开展示。</p>
    </div>
  </section>
</template>
