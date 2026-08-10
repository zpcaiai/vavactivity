<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import {
  commerceApi,
  type Entitlement,
  type Order,
  type Subscription
} from "../api";

const route = useRoute();
const { t } = useI18n();
const kind = computed(() => String(route.meta.commerceKind ?? "orders"));
const rows = ref<Array<Order | Subscription | Entitlement>>([]);
const loading = ref(true);
const error = ref("");

async function load() {
  loading.value = true;
  try {
    const response = kind.value === "subscriptions"
      ? await commerceApi.subscriptions()
      : kind.value === "entitlements"
        ? await commerceApi.entitlements()
        : await commerceApi.orders();
    rows.value = response.items;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("commerce.error");
  } finally {
    loading.value = false;
  }
}

async function cancel(item: Subscription) {
  try {
    await commerceApi.cancelSubscription(item.id);
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("commerce.error");
  }
}

function isOrder(row: Order | Subscription | Entitlement): row is Order {
  return "order_number" in row;
}
function isSubscription(row: Order | Subscription | Entitlement): row is Subscription {
  return "billing_interval" in row;
}

onMounted(() => void load());
</script>

<template>
  <section class="commerce-page">
    <p class="eyebrow">
      MY VAV
    </p>
    <h1>{{ t(`commerce.${kind}`) }}</h1>
    <p v-if="loading">
      {{ t("commerce.loading") }}
    </p>
    <p
      v-if="error"
      class="form-error"
    >
      {{ error }}
    </p>
    <div class="commerce-list">
      <article
        v-for="row in rows"
        :key="row.id"
        class="commerce-card"
      >
        <template v-if="isOrder(row)">
          <div><strong>{{ row.order_number }}</strong><small>{{ row.status }}</small></div>
          <span>{{ row.currency }} {{ (row.total_minor / 100).toFixed(2) }}</span>
          <RouterLink :to="`/${String(route.params.locale)}/account/orders/${row.order_number}`">
            {{ t("commerce.orderDetail") }}
          </RouterLink>
        </template>
        <template v-else-if="isSubscription(row)">
          <div><strong>{{ row.provider }}</strong><small>{{ row.status }}</small></div>
          <span>{{ row.currency }} {{ (row.amount_minor / 100).toFixed(2) }}/{{ row.billing_interval }}</span>
          <button
            v-if="!row.cancel_at_period_end && row.status === 'active'"
            type="button"
            @click="cancel(row)"
          >
            {{ t("commerce.cancelAtPeriodEnd") }}
          </button>
        </template>
        <template v-else>
          <div><strong>{{ row.type }}</strong><small>{{ row.status }}</small></div>
          <span>{{ row.quantity_consumed }}/{{ row.quantity_granted ?? "∞" }}</span>
        </template>
      </article>
      <p v-if="!loading && !rows.length">
        {{ t("commerce.empty") }}
      </p>
    </div>
  </section>
</template>
