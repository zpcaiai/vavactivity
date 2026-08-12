<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { recommendationsApi } from "@/features/recommendations/api";
import RecommendationTransparency from "@/features/recommendations/components/RecommendationTransparency.vue";
import type { RecommendationTransparencyData } from "@/features/recommendations/types";

const route = useRoute();
const transparency = ref<RecommendationTransparencyData>();
const loading = ref(false);
const error = ref("");

const locale = computed(() => String(route.params.locale ?? "zh-CN"));
const listPath = computed(() => `/${locale.value}/recommendations`);
const preferencesPath = computed(() => `/${locale.value}/account/recommendation-preferences`);
const datingPreferencesPath = computed(
  () => `/${locale.value}/account/dating-profile/preferences`
);
const privacyPath = computed(() => `/${locale.value}/account/privacy`);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    transparency.value = await recommendationsApi.transparency();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "推荐说明加载失败";
  } finally {
    loading.value = false;
  }
}

onMounted(() => void load());
</script>

<template>
  <section class="transparency-page">
    <RouterLink :to="listPath">
      ← 返回今日推荐
    </RouterLink>
    <h1>推荐是怎么产生的</h1>
    <p class="intro">
      下面的内容按你的账户实际情况生成：哪些资料类别参与了推荐、哪些来自你自己填写的条件、
      哪些使用平台默认设置，以及哪些资料永远不会被使用。这里不会显示任何其他会员的资料，
      也不会显示单条推荐的内部权重或分数。
    </p>

    <p
      v-if="error"
      class="alert error"
      role="alert"
    >
      {{ error }}
    </p>
    <p v-if="loading">
      正在加载推荐说明…
    </p>

    <RecommendationTransparency
      v-else-if="transparency"
      :transparency="transparency"
    >
      <template #actions>
        <div class="links">
          <RouterLink :to="preferencesPath">
            前往推荐设置
          </RouterLink>
          <RouterLink :to="datingPreferencesPath">
            修改择偶条件
          </RouterLink>
          <RouterLink :to="privacyPath">
            隐私中心
          </RouterLink>
        </div>
      </template>
    </RecommendationTransparency>
  </section>
</template>

<style scoped>
.transparency-page { display: flex; flex-direction: column; gap: 1rem; padding: 2rem 0; }
.transparency-page h1 { margin: 0; font-size: 1.4rem; }
.intro { max-width: 62ch; line-height: 1.7; margin: 0; }
.alert { padding: 0.75rem 1rem; border-radius: 0.5rem; margin: 0; }
.alert.error { background: var(--vav-color-surface-danger); color: var(--vav-color-danger); }
.links { display: flex; flex-wrap: wrap; gap: 1rem; font-size: 0.9rem; }
</style>
