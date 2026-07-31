<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { useSeo } from "@/composables/useSeo";
import { commerceApi } from "@/features/commerce/api";
import ContentRenderer from "@/features/public-site/components/ContentRenderer.vue";
import { createQuote, getProduct } from "../api/catalog";
import AvailabilityBadge from "../components/AvailabilityBadge.vue";
import CouponInput from "../components/CouponInput.vue";
import CurrencySelector from "../components/CurrencySelector.vue";
import PricingSummary from "../components/PricingSummary.vue";
import ProductPrice from "../components/ProductPrice.vue";
import SkuSelector from "../components/SkuSelector.vue";
import { useCurrency } from "../composables/useCurrency";
import type { CatalogProduct, PricingQuote } from "../types";

const route = useRoute();
const { t } = useI18n();
const locale = computed(() => String(route.params.locale ?? "zh-CN"));
const slug = computed(() => String(route.params.slug ?? ""));
const { currency, currencies } = useCurrency();
const product = ref<CatalogProduct | null>(null);
const selectedSkuId = ref("");
const quantity = ref(1);
const couponCode = ref("");
const quote = ref<PricingQuote | null>(null);
const loading = ref(true);
const quoting = ref(false);
const adding = ref(false);
const added = ref(false);
const error = ref("");
const selectedSku = computed(() =>
  product.value?.skus.find((sku) => sku.id === selectedSkuId.value)
);
const selectedPrice = computed(() => selectedSku.value?.prices[0]);

useSeo(computed(() => ({
  title: product.value?.seo_title || product.value?.name || "服务详情 · VAV",
  description: product.value?.seo_description || product.value?.short_description || ""
})));

async function load() {
  loading.value = true;
  quote.value = null;
  added.value = false;
  error.value = "";
  try {
    product.value = await getProduct(slug.value, locale.value, currency.value);
    selectedSkuId.value = product.value.skus[0]?.id ?? "";
  } catch (cause) {
    product.value = null;
    error.value = cause instanceof Error ? cause.message : "商品暂时无法加载";
  } finally {
    loading.value = false;
  }
}

async function quotePrice() {
  if (!selectedSku.value) {
    return;
  }
  quoting.value = true;
  error.value = "";
  try {
    quote.value = await createQuote({
      skuId: selectedSku.value.id,
      quantity: quantity.value,
      currency: currency.value,
      locale: locale.value,
      couponCode: couponCode.value
    });
  } catch (cause) {
    quote.value = null;
    error.value = cause instanceof Error ? cause.message : "报价失败";
  } finally {
    quoting.value = false;
  }
}

async function addToCart() {
  if (!selectedSku.value) return;
  adding.value = true;
  error.value = "";
  added.value = false;
  try {
    await commerceApi.addItem(
      selectedSku.value.id,
      quantity.value,
      currency.value,
      couponCode.value
    );
    added.value = true;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "加入购物车失败";
  } finally {
    adding.value = false;
  }
}

onMounted(() => void load());
watch([slug, locale, currency], () => void load());
watch([selectedSkuId, quantity], () => {
  quote.value = null;
  added.value = false;
});
</script>

<template>
  <section class="product-detail">
    <p
      v-if="loading"
      role="status"
    >
      正在加载服务详情…
    </p>
    <p
      v-else-if="error && !product"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>
    <template v-else-if="product">
      <div class="product-detail-main">
        <div class="product-detail-copy">
          <p class="eyebrow">
            {{ product.product_code }}
          </p>
          <h1>{{ product.name }}</h1>
          <p class="product-lead">
            {{ product.short_description }}
          </p>
          <ContentRenderer :blocks="product.description_blocks" />
          <RouterLink :to="`/${locale}/refund-policy`">
            查看退款政策
          </RouterLink>
        </div>
        <aside class="purchase-panel">
          <CurrencySelector
            v-model="currency"
            :currencies="currencies"
          />
          <SkuSelector
            v-model="selectedSkuId"
            :skus="product.skus"
          />
          <template v-if="selectedSku">
            <div class="purchase-price">
              <ProductPrice
                v-if="selectedPrice"
                :amount-minor="selectedPrice.unit_amount_minor"
                :currency="selectedPrice.currency"
              />
              <span v-else-if="selectedSku.billing_type === 'free'">
                {{ t("catalog.free") }}
              </span>
              <span v-else>{{ t("catalog.missingPrice") }}</span>
              <AvailabilityBadge
                :status="selectedSku.availability.status"
                :quantity="selectedSku.availability.available_quantity"
              />
            </div>
            <label>
              <span>数量</span>
              <input
                v-model.number="quantity"
                type="number"
                min="1"
                :max="selectedSku.purchase_limit_per_user ?? 100"
              >
            </label>
            <CouponInput
              v-if="selectedSku.billing_type !== 'free'"
              v-model="couponCode"
              :disabled="quoting || !selectedPrice"
              @apply="quotePrice"
            />
            <button
              v-if="selectedSku.billing_type !== 'free'"
              class="primary-button"
              type="button"
              :disabled="quoting || !selectedPrice || selectedSku.availability.status === 'sold_out'"
              @click="quotePrice"
            >
              {{ quoting ? "正在计算…" : "获取后端报价" }}
            </button>
            <p
              v-else
              class="checkout-boundary"
            >
              {{ t("catalog.freeBoundary") }}
            </p>
            <p
              v-if="error"
              class="form-error"
              role="alert"
            >
              {{ error }}
            </p>
            <PricingSummary
              v-if="quote"
              :quote="quote"
            />
            <button
              v-if="quote"
              class="primary-button"
              type="button"
              :disabled="adding"
              @click="addToCart"
            >
              {{ adding ? "正在加入…" : "加入购物车" }}
            </button>
            <RouterLink
              v-if="quote && added"
              class="secondary-link"
              :to="`/${locale}/cart`"
            >
              查看购物车
            </RouterLink>
            <p class="checkout-boundary">
              报价仅用于下单校验；付款状态只由已验签 Provider Webhook 更新。
            </p>
          </template>
        </aside>
      </div>
    </template>
  </section>
</template>
