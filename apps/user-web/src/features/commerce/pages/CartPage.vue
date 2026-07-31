<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { commerceApi, type Cart, type CartItem } from "../api";

const route = useRoute();
const { t } = useI18n();
const cart = ref<Cart | null>(null);
const loading = ref(true);
const error = ref("");

async function load() {
  loading.value = true;
  error.value = "";
  try {
    cart.value = await commerceApi.getCart();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("commerce.error");
  } finally {
    loading.value = false;
  }
}

async function change(item: CartItem, quantity: number) {
  if (!cart.value) return;
  try {
    cart.value = quantity > 0
      ? await commerceApi.updateItem(item, cart.value, quantity)
      : await commerceApi.removeItem(item.id);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("commerce.error");
  }
}

onMounted(() => void load());
</script>

<template>
  <section class="commerce-page">
    <p class="eyebrow">
      COMMERCE
    </p>
    <h1>{{ t("commerce.cart") }}</h1>
    <p
      v-if="loading"
      role="status"
    >
      {{ t("commerce.loading") }}
    </p>
    <p
      v-if="error"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>
    <div
      v-if="cart && cart.items.length"
      class="commerce-list"
    >
      <article
        v-for="item in cart.items"
        :key="item.id"
        class="commerce-card"
      >
        <div>
          <strong>{{ item.sku_id }}</strong>
          <small v-if="item.coupon_code">{{ item.coupon_code }}</small>
        </div>
        <div class="commerce-actions">
          <button
            type="button"
            @click="change(item, item.quantity - 1)"
          >
            −
          </button>
          <span>{{ item.quantity }}</span>
          <button
            type="button"
            @click="change(item, item.quantity + 1)"
          >
            +
          </button>
          <button
            type="button"
            @click="change(item, 0)"
          >
            {{ t("commerce.remove") }}
          </button>
        </div>
      </article>
      <RouterLink
        class="primary-button commerce-cta"
        :to="`/${String(route.params.locale)}/checkout`"
      >
        {{ t("commerce.checkout") }}
      </RouterLink>
    </div>
    <p v-else-if="!loading">
      {{ t("commerce.emptyCart") }}
    </p>
  </section>
</template>
