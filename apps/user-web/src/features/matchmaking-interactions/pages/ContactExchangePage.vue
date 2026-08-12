<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { VAlert, VButton, VCard, VPageState, VStatusBadge } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import {
  matchmakingInteractionsApi,
  type InteractionRow
} from "@/features/matchmaking-interactions/api";
import {
  useInteractionShell,
  useInteractionState
} from "@/features/matchmaking-interactions/composables/useInteractionShell";
import { privacyApi } from "@/features/privacy/api";

type ContactPoint = { id: string; contact_type: string; masked_value: string; status: string };

const route = useRoute();
const { breadcrumbs, t } = useInteractionShell("matches");
const { busy, error, notice, run } = useInteractionState();

const detail = ref<InteractionRow>();
const contacts = ref<ContactPoint[]>([]);
const selected = ref<string[]>([]);
const revealed = ref<Record<string, string>>({});
const exchangeId = computed(() => String(route.params.id ?? ""));
const sharedContacts = computed(
  () => (detail.value?.contacts as Array<Record<string, unknown>> | undefined) ?? []
);

async function load() {
  busy.value = true;
  error.value = "";
  try {
    detail.value = await matchmakingInteractionsApi.contactExchange(exchangeId.value);
    const result = await privacyApi<{ items: ContactPoint[] }>("/account/contact-points");
    contacts.value = result.items.filter((item) => item.status === "verified");
    selected.value = contacts.value.map((item) => item.id);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("mm.loadError");
  } finally {
    busy.value = false;
  }
}

function consent(platformOnly: boolean) {
  return run(
    () =>
      matchmakingInteractionsApi.consentContactExchange(
        exchangeId.value,
        platformOnly ? [] : selected.value,
        platformOnly
      ),
    platformOnly ? t("mm.contact.platformOnlyDone") : t("mm.contact.consentDone"),
    load
  );
}

function withdrawConsent() {
  return run(
    () => matchmakingInteractionsApi.withdrawContactConsent(exchangeId.value),
    t("mm.contact.withdrawDone"),
    load
  );
}

async function reveal(contact: Record<string, unknown>) {
  const contactPointId = String(contact.contact_point_id ?? "");
  if (!contactPointId) return;
  try {
    const token = await matchmakingInteractionsApi.revealToken(exchangeId.value, contactPointId);
    const result = await matchmakingInteractionsApi.reveal(exchangeId.value, token.reveal_token);
    revealed.value[contactPointId] = result.value;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("mm.contact.revealFailed");
  }
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('ia.groups.matchmaking')"
    :title="t('mm.contact.title')"
    :description="t('mm.contact.description')"
    :breadcrumbs="[...breadcrumbs, { label: t('mm.contact.short') }]"
  >
    <VAlert
      v-if="error"
      tone="danger"
      :title="t('common.loadFailed')"
    >
      {{ error }}
    </VAlert>
    <VAlert
      v-if="notice"
      tone="success"
      :title="t('common.done')"
      live
    >
      {{ notice }}
    </VAlert>

    <VPageState
      v-if="busy && !detail"
      state="loading"
      :title="t('common.loading')"
      :message="t('common.pleaseWait')"
    />

    <template v-else-if="detail">
      <VCard tone="info">
        <template #title>
          <h2>{{ t("mm.contact.stateTitle") }}</h2>
        </template>
        <template #actions>
          <VStatusBadge
            status="info"
            :label="String(detail.status ?? '')"
          />
        </template>
        <p>
          {{
            detail.other_member_has_consented
              ? t("mm.contact.otherConsented")
              : t("mm.contact.otherPending")
          }}
        </p>
      </VCard>

      <VCard>
        <template #title>
          <h2>{{ t("mm.contact.chooseTitle") }}</h2>
        </template>
        <template #description>
          {{ t("mm.contact.chooseDescription") }}
        </template>
        <fieldset class="contact-choices">
          <legend class="sr-only">
            {{ t("mm.contact.chooseTitle") }}
          </legend>
          <label
            v-for="contact in contacts"
            :key="contact.id"
          >
            <input
              v-model="selected"
              type="checkbox"
              :value="contact.id"
            >
            <span>{{ contact.contact_type }} · {{ contact.masked_value }}</span>
          </label>
          <p v-if="!contacts.length">
            {{ t("mm.contact.noVerified") }}
          </p>
        </fieldset>
        <template #footer>
          <VButton
            :disabled="!selected.length"
            @click="consent(false)"
          >
            {{ t("mm.contact.confirmSelected") }}
          </VButton>
          <VButton
            variant="secondary"
            @click="consent(true)"
          >
            {{ t("mm.contact.platformOnly") }}
          </VButton>
          <VButton
            variant="danger"
            @click="withdrawConsent"
          >
            {{ t("mm.contact.withdraw") }}
          </VButton>
        </template>
      </VCard>

      <VCard v-if="sharedContacts.length">
        <template #title>
          <h2>{{ t("mm.contact.sharedTitle") }}</h2>
        </template>
        <ul class="contact-list">
          <li
            v-for="contact in sharedContacts"
            :key="String(contact.contact_point_id)"
          >
            <span>{{ contact.type }} · {{ contact.masked_value ?? contact.state }}</span>
            <VButton
              v-if="contact.state === 'available' && !revealed[String(contact.contact_point_id)]"
              variant="secondary"
              @click="reveal(contact)"
            >
              {{ t("mm.contact.revealOnce") }}
            </VButton>
            <strong v-if="revealed[String(contact.contact_point_id)]">
              {{ revealed[String(contact.contact_point_id)] }}
            </strong>
          </li>
        </ul>
      </VCard>
    </template>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
p { margin: 0; color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); }
.contact-choices { display: grid; gap: var(--vav-space-2); border: 0; margin: 0; padding: 0; }
.contact-choices label { display: flex; align-items: center; gap: var(--vav-space-2); }
.contact-list { display: grid; gap: var(--vav-space-2); margin: 0; padding: 0; list-style: none; }
.contact-list li { display: flex; flex-wrap: wrap; align-items: center; gap: var(--vav-space-3); justify-content: space-between; }
.sr-only { position: absolute; inline-size: 1px; block-size: 1px; overflow: hidden; clip-path: inset(50%); }
</style>
