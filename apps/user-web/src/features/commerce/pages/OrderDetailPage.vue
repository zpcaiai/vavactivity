<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { commerceApi, type Order } from "../api";

const route = useRoute();
const { t } = useI18n();
const order = ref<Order | null>(null);
const error = ref("");

onMounted(async () => {
  try {
    order.value = await commerceApi.order(String(route.params.orderNumber));
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("commerce.error");
  }
});
</script>

<template>
  <section class="commerce-page">
    <p class="eyebrow">
      ORDER
    </p>
    <p
      v-if="error"
      class="form-error"
    >
      {{ error }}
    </p>
    <template v-if="order">
      <h1>{{ order.order_number }}</h1>
      <div class="status-panel">
        <p>{{ t("commerce.orderStatus") }}: <strong>{{ order.status }}</strong></p>
        <p>{{ order.currency }} {{ (order.total_minor / 100).toFixed(2) }}</p>
      </div>
      <div class="commerce-list">
        <article
          v-for="item in order.items"
          :key="item.id"
          class="commerce-card"
        >
          <div><strong>{{ item.product_name }}</strong><small>{{ item.sku_name }}</small></div>
          <span>× {{ item.quantity }}</span>
        </article>
      </div>
      <h2>{{ t("commerce.payments") }}</h2>
      <p
        v-for="payment in order.payments"
        :key="payment.id"
      >
        {{ payment.provider }} · {{ payment.status }} · {{ payment.environment }}
      </p>
      <h2>{{ t("commerce.entitlements") }}</h2>
      <p
        v-for="item in order.entitlements"
        :key="item.id"
      >
        {{ item.type }} · {{ item.status }}
      </p>
    </template>
  </section>
</template>
