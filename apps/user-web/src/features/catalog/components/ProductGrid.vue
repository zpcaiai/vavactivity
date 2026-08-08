<script setup lang="ts">
import ProductCard from "./ProductCard.vue";
import type { CatalogProduct } from "../types";

defineProps<{
  products: CatalogProduct[];
  locale: string;
  currency: string;
}>();
</script>

<template>
  <div class="product-grid">
    <ProductCard
      v-for="product in products"
      :key="product.id"
      :product="product"
      :locale="locale"
      :currency="currency"
    />
  </div>
</template>
