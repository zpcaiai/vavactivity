<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { commerceApi, type Order, type Payment } from "../api";

const route = useRoute();
const { t } = useI18n();
const orderNumber = computed(() => String(route.query.order ?? ""));
const order = ref<Order | null>(null);
const payment = ref<Payment | null>(null);
const error = ref("");
let timer: number | undefined;

async function refresh() {
  if (!orderNumber.value) return;
  try {
    order.value = await commerceApi.order(orderNumber.value);
    payment.value = order.value.payments?.at(-1) ?? null;
    if (["fulfilled", "refunded", "cancelled", "manual_review"].includes(order.value.status)) {
      window.clearInterval(timer);
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("commerce.error");
  }
}

onMounted(() => {
  const cached = sessionStorage.getItem(`vav_payment_${orderNumber.value}`);
  if (cached) payment.value = JSON.parse(cached) as Payment;
  void refresh();
  timer = window.setInterval(() => void refresh(), 3000);
});
onBeforeUnmount(() => window.clearInterval(timer));
</script>

<template>
  <section class="commerce-page commerce-centered">
    <p class="eyebrow">
      PAYMENT STATUS
    </p>
    <h1>{{ t("commerce.processing") }}</h1>
    <p
      v-if="error"
      class="form-error"
    >
      {{ error }}
    </p>
    <div
      v-if="order"
      class="status-panel"
    >
      <strong>{{ order.order_number }}</strong>
      <p>{{ t("commerce.orderStatus") }}: {{ order.status }}</p>
      <p v-if="payment">
        {{ t("commerce.paymentStatus") }}: {{ payment.status }}
      </p>
      <a
        v-if="payment?.client_action?.url && !payment.client_action.test_only"
        class="primary-button"
        :href="payment.client_action.url"
      >{{ t("commerce.continueProvider") }}</a>
      <p
        v-if="payment?.client_action?.test_only"
        class="checkout-boundary"
      >
        {{ t("commerce.testProvider") }}
      </p>
      <RouterLink :to="`/${String(route.params.locale)}/account/orders/${order.order_number}`">
        {{ t("commerce.orderDetail") }}
      </RouterLink>
    </div>
    <p class="checkout-boundary">
      {{ t("commerce.returnBoundary") }}
    </p>
  </section>
</template>
