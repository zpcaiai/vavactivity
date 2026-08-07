<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { useAuthStore } from "@/stores/auth";
import { commerceApi, type Cart, type CheckoutPreview } from "../api";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const { t } = useI18n();
const locale = computed(() => String(route.params.locale));
const cart = ref<Cart | null>(null);
const preview = ref<CheckoutPreview | null>(null);
const provider = ref("stripe");
const busy = ref(false);
const error = ref("");

async function load() {
  try {
    cart.value = await commerceApi.getCart();
    preview.value = await commerceApi.preview(cart.value.id, locale.value);
    provider.value = preview.value.available_payment_providers[0] ?? "stripe";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("commerce.error");
  }
}

async function pay() {
  if (!cart.value || !preview.value || !auth.user) return;
  busy.value = true;
  error.value = "";
  try {
    const order = await commerceApi.createOrder(
      cart.value.id,
      locale.value,
      auth.user.email,
      preview.value.total_minor,
      `checkout-${crypto.randomUUID()}`
    );
    const payment = await commerceApi.createPayment(
      order.order_number,
      provider.value,
      `payment-${crypto.randomUUID()}`
    );
    sessionStorage.setItem(`vav_payment_${order.order_number}`, JSON.stringify(payment));
    await router.push(`/${locale.value}/checkout/processing?order=${order.order_number}`);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("commerce.error");
  } finally {
    busy.value = false;
  }
}

onMounted(() => void load());
</script>

<template>
  <section class="commerce-page">
    <p class="eyebrow">
      SECURE CHECKOUT
    </p>
    <h1>{{ t("commerce.checkout") }}</h1>
    <p
      v-if="error"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>
    <div
      v-if="preview"
      class="checkout-summary"
    >
      <p>{{ t("commerce.authoritativeTotal") }}</p>
      <strong>{{ preview.currency }} {{ (preview.total_minor / 100).toFixed(2) }}</strong>
      <p v-if="preview.discount_total_minor">
        {{ t("commerce.discount") }}: {{ preview.discount_total_minor }}
      </p>
      <label>
        <span>{{ t("commerce.provider") }}</span>
        <select v-model="provider">
          <option
            v-for="item in preview.available_payment_providers"
            :key="item"
            :value="item"
          >
            {{ item }}
          </option>
        </select>
      </label>
      <button
        class="primary-button"
        type="button"
        :disabled="busy"
        @click="pay"
      >
        {{ busy ? t("commerce.processing") : t("commerce.pay") }}
      </button>
      <p class="checkout-boundary">
        {{ t("commerce.returnBoundary") }}
      </p>
    </div>
  </section>
</template>
