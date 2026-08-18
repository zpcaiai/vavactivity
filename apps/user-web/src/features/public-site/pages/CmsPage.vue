<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { useSeo } from "@/composables/useSeo";
import { getArticle, getPage, getTestimonial } from "../api/content";
import ContentRenderer from "../components/ContentRenderer.vue";
import type { PublicContent } from "../types";

const route = useRoute();
const { t } = useI18n();
const content = ref<PublicContent | null>(null);
const loading = ref(true);
const error = ref("");
const slug = computed(() => String(route.meta.cmsSlug ?? route.meta.copyKey ?? ""));
const locale = computed(() => String(route.params.locale ?? "zh-CN"));
const fallbackTitle = computed(() => t(`pages.${String(route.meta.copyKey)}.title`));
const fallbackBody = computed(() => t(`pages.${String(route.meta.copyKey)}.body`));

useSeo(
  computed(() => ({
    title: content.value?.seo_title || content.value?.title || fallbackTitle.value,
    description:
      content.value?.seo_description || content.value?.excerpt || fallbackBody.value
  }))
);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const routeName = String(route.name ?? "");
    const dynamicSlug = String(route.params.slug ?? "");
    content.value =
      routeName === "article-detail"
        ? await getArticle(dynamicSlug, locale.value)
        : routeName === "story-detail"
          ? await getTestimonial(dynamicSlug, locale.value)
          : await getPage(slug.value, locale.value);
  } catch {
    error.value = "内容暂时无法加载，请稍后重试。";
  } finally {
    loading.value = false;
  }
}

onMounted(() => void load());
watch([slug, locale], () => void load());
</script>

<template>
  <section class="editorial-page cms-page">
    <article v-if="content">
      <p class="eyebrow">
        {{ content.fallback_used ? "LOCALE FALLBACK" : "VAV" }}
      </p>
      <h1>{{ content.title }}</h1>
      <p v-if="content.subtitle">
        {{ content.subtitle }}
      </p>
      <ContentRenderer :blocks="content.content_blocks" />
    </article>

    <!-- Loading and error used to replace the whole page, which left these
         routes with no `h1` at all — the layout's post-navigation focus
         handler targets `#main-content h1`, and the page collapsed to a single
         centred line. The heading now renders in every state. -->
    <article v-else>
      <p class="eyebrow">
        {{ t(`pages.${String(route.meta.copyKey)}.eyebrow`) }}
      </p>
      <h1>{{ fallbackTitle }}</h1>
      <p
        v-if="loading"
        role="status"
      >
        {{ t("common.loading") }}
      </p>
      <p
        v-else-if="error"
        class="form-error"
        role="alert"
      >
        {{ error }}
      </p>
      <template v-else>
        <p>{{ fallbackBody }}</p>
        <p class="draft-notice">
          正式运营内容尚未发布；当前仅显示明确标记的产品说明。
        </p>
      </template>
    </article>
  </section>
</template>
