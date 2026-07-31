<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";

import { activityApi, type PublicActivity } from "../api";

const route = useRoute();
const router = useRouter();
const { t } = useI18n();
const activity = ref<PublicActivity>();
const ticketTypeId = ref("");
const accepted = ref<string[]>([]);
const answers = reactive<Record<string, unknown>>({});
const loading = ref(true);
const submitting = ref(false);
const error = ref("");
const result = ref("");

function ticketPrice(ticket: PublicActivity["ticket_types"][number]) {
  const price = ticket.prices.find((item) => item.currency === "USD") ?? ticket.prices[0];
  if (!price) return "—";
  if (price.unit_amount_minor === 0) return t("activities.free");
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: price.currency
  }).format(price.unit_amount_minor / 100);
}

async function load() {
  try {
    activity.value = await activityApi.detail(
      String(route.params.slug),
      String(route.params.locale)
    );
    ticketTypeId.value = activity.value.ticket_types[0]?.id ?? "";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("activities.loadError");
  } finally {
    loading.value = false;
  }
}

async function register() {
  if (!activity.value || !ticketTypeId.value) return;
  submitting.value = true;
  error.value = "";
  try {
    const registration = await activityApi.register(
      activity.value.id,
      ticketTypeId.value,
      String(route.params.locale),
      answers,
      accepted.value
    );
    result.value = `${registration.registration_number} · ${registration.status}`;
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : "报名失败";
    if (message.toLowerCase().includes("authentication")) {
      await router.push({
        name: "login",
        params: { locale: route.params.locale },
        query: { returnTo: route.fullPath }
      });
    } else {
      error.value = message;
    }
  } finally {
    submitting.value = false;
  }
}

onMounted(() => void load());
</script>

<template>
  <section
    v-if="activity"
    class="catalog-page activity-detail"
  >
    <p class="eyebrow">
      {{ activity.format }} · {{ activity.status }}
    </p>
    <h1>{{ activity.title }}</h1>
    <p>{{ activity.summary }}</p>
    <div class="commerce-card">
      <strong>{{ new Date(activity.starts_at).toLocaleString() }}</strong>
      <span>{{ activity.timezone }}</span>
      <span
        v-for="location in activity.locations"
        :key="String(location.id)"
      >
        {{ location.city }} · {{ location.venue_name }}
      </span>
    </div>
    <form
      class="auth-form"
      @submit.prevent="register"
    >
      <h2>{{ t("activities.registerTitle") }}</h2>
      <label>
        {{ t("activities.ticket") }}
        <select
          v-model="ticketTypeId"
          required
        >
          <option
            v-for="ticket in activity.ticket_types"
            :key="ticket.id"
            :value="ticket.id"
          >
            {{ ticket.name }} · {{ ticketPrice(ticket) }} · {{ ticket.availability.status }}
          </option>
        </select>
      </label>
      <label
        v-for="field in activity.registration_form.form_schema.fields"
        :key="field.key"
      >
        {{ field.label ?? field.key }}
        <textarea
          v-if="field.type === 'textarea'"
          v-model="answers[field.key] as string"
          :required="field.required"
        />
        <input
          v-else
          v-model="answers[field.key] as string"
          :type="field.type === 'checkbox' ? 'checkbox' : 'text'"
          :required="field.required"
        >
      </label>
      <label
        v-for="consent in activity.registration_form.consent_requirements"
        :key="consent.key"
      >
        <input
          v-model="accepted"
          type="checkbox"
          :value="consent.key"
          :required="consent.required"
        >
        {{ consent.label ?? consent.key }}
      </label>
      <button
        type="submit"
        :disabled="submitting || !ticketTypeId"
      >
        {{
          submitting
            ? t("activities.submitting")
            : activity.ticket_types.find((ticket) => ticket.id === ticketTypeId)?.availability.status === "sold_out"
              ? t("activities.joinWaitlist")
              : t("activities.submit")
        }}
      </button>
      <p
        v-if="result"
        class="success-message"
      >
        {{ t("activities.registrationStatus") }}：{{ result }}。{{ t("activities.paymentBoundary") }}
      </p>
      <p
        v-if="error"
        class="form-error"
        role="alert"
      >
        {{ error }}
      </p>
    </form>
  </section>
  <p
    v-else-if="loading"
    role="status"
  >
    {{ t("activities.loading") }}
  </p>
  <p
    v-else
    class="form-error"
  >
    {{ error }}
  </p>
</template>
