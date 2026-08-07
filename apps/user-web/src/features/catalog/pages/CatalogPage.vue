<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { useSeo } from "@/composables/useSeo";
import { listProducts } from "../api/catalog";
import CurrencySelector from "../components/CurrencySelector.vue";
import ProductGrid from "../components/ProductGrid.vue";
import { useCurrency } from "../composables/useCurrency";
import type { CatalogProduct } from "../types";

const route = useRoute();
const locale = computed(() => String(route.params.locale ?? "zh-CN"));
const category = computed(() => String(route.meta.catalogCategory ?? route.params.category ?? ""));
const title = computed(() => String(route.meta.catalogTitle ?? "服务目录"));
const products = ref<CatalogProduct[]>([]);
const loading = ref(true);
const error = ref("");
const { currency, currencies } = useCurrency();

useSeo(computed(() => ({
  title: `${title.value} · VAV`,
  description: "浏览 VAV 当前公开、可售并由后端定价的活动、课程、辅导、AI 与会员服务。"
})));

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const result = await listProducts({
      locale: locale.value,
      currency: currency.value,
      category: category.value || undefined
    });
    products.value = result.items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "服务目录暂时无法加载";
  } finally {
    loading.value = false;
  }
}

onMounted(() => void load());
watch([locale, category, currency], () => void load());
</script>

<template>
  <section class="catalog-page">
    <header class="catalog-heading">
      <div>
        <p class="eyebrow">
          VAV SERVICE CATALOG
        </p>
        <h1>{{ title }}</h1>
        <p>价格、优惠和名额均以后端实时报价为准。</p>
      </div>
      <CurrencySelector
        v-model="currency"
        :currencies="currencies"
      />
    </header>
    <p
      v-if="loading"
      role="status"
    >
      正在加载服务…
    </p>
    <p
      v-else-if="error"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>
    <ProductGrid
      v-else-if="products.length"
      :products="products"
      :locale="locale"
      :currency="currency"
    />
    <div
      v-else
      class="catalog-empty"
    >
      <h2>该分类尚无已上架服务</h2>
      <p>草稿、待审核或缺少明确价格的商品不会在此展示。</p>
    </div>
  </section>
</template>
