<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import AvailabilityBadge from "./AvailabilityBadge.vue";
import ProductPrice from "./ProductPrice.vue";
import type { CatalogProduct } from "../types";

const props = defineProps<{
  product: CatalogProduct;
  locale: string;
  currency: string;
}>();
const { t } = useI18n();

const firstSku = computed(() => props.product.skus[0]);
const firstPrice = computed(() => firstSku.value?.prices[0]);
</script>

<template>
  <article class="product-card">
    <div
      class="product-card-art"
      aria-hidden="true"
    >
      <span>{{ product.product_type.replaceAll("_", " ") }}</span>
    </div>
    <div class="product-card-body">
      <p class="eyebrow">
        {{ product.product_code }}
      </p>
      <h2>{{ product.name }}</h2>
      <p>{{ product.short_description }}</p>
      <div class="product-card-meta">
        <ProductPrice
          v-if="firstPrice"
          :amount-minor="firstPrice.unit_amount_minor"
          :currency="firstPrice.currency"
        />
        <span v-else-if="firstSku?.billing_type === 'free'">{{ t("catalog.free") }}</span>
        <span v-else>{{ t("catalog.missingPrice") }}</span>
        <AvailabilityBadge
          v-if="firstSku"
          :status="firstSku.availability.status"
          :quantity="firstSku.availability.available_quantity"
        />
      </div>
      <RouterLink
        class="text-link"
        :to="`/${locale}/products/${product.slug}?currency=${currency}`"
      >
        {{ t("catalog.details") }}
      </RouterLink>
    </div>
  </article>
</template>
