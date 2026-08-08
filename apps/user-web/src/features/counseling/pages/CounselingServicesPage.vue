<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { counselingApi, type CounselingService } from "../api";

const route = useRoute();
const services = ref<CounselingService[]>([]);
const error = ref("");

async function load() {
  try {
    services.value = (await counselingApi.services(String(route.params.locale))).items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "咨询服务加载失败";
  }
}

onMounted(() => void load());
watch(() => route.params.locale, () => void load());
</script>

<template>
  <section class="catalog-page counseling-page">
    <header class="catalog-heading">
      <div>
        <p class="eyebrow">
          VAV HUMAN SUPPORT
        </p>
        <h1>真人辅导</h1>
        <p>结构化的关系成长支持；不是心理治疗、医疗诊断、法律意见或紧急危机服务。</p>
      </div>
    </header>
    <p
      v-if="error"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>
    <div class="product-grid">
      <article
        v-for="service in services"
        :key="service.id"
        class="product-card"
      >
        <p class="eyebrow">
          {{ service.delivery_mode }} · {{ service.duration_minutes }} 分钟
        </p>
        <h2>{{ service.name }}</h2>
        <p>{{ service.summary }}</p>
        <p v-if="service.prices.length">
          {{ service.prices[0].currency }} {{ (service.prices[0].unit_amount_minor / 100).toFixed(2) }}
        </p>
        <RouterLink :to="`/${String(route.params.locale)}/counseling/${service.slug}`">
          查看服务与可预约时间
        </RouterLink>
      </article>
    </div>
  </section>
</template>
