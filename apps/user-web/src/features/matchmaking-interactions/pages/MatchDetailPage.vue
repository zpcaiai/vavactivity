<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { VAlert, VButton, VCard, VDescriptionList, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import {
  matchmakingInteractionsApi,
  type InteractionRow
} from "@/features/matchmaking-interactions/api";
import {
  useInteractionShell,
  useInteractionState
} from "@/features/matchmaking-interactions/composables/useInteractionShell";

const route = useRoute();
const { breadcrumbs, localePath, t } = useInteractionShell("matches");
const { busy, error, notice, run } = useInteractionState();

const detail = ref<InteractionRow>();
const invitationMessage = ref("");
const matchId = computed(() => String(route.params.id ?? ""));

const facts = computed(() => [
  { term: t("mm.detail.status"), value: String(detail.value?.status ?? "-") },
  { term: t("mm.detail.number"), value: String(detail.value?.match_number ?? "-") },
  {
    term: t("mm.detail.invitation"),
    value: String(detail.value?.invitation_status ?? t("mm.detail.notSent"))
  }
]);

async function load() {
  busy.value = true;
  error.value = "";
  try {
    detail.value = await matchmakingInteractionsApi.match(matchId.value);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("mm.loadError");
  } finally {
    busy.value = false;
  }
}

function sendInvitation() {
  if (!detail.value?.mutual_match_id) return;
  if (!window.confirm(t("mm.detail.confirmInvitation"))) return;
  return run(
    () =>
      matchmakingInteractionsApi.sendInvitation(
        String(detail.value?.mutual_match_id),
        invitationMessage.value
      ),
    t("mm.detail.invitationSent"),
    load
  );
}

function requestExchange() {
  if (!detail.value?.mutual_match_id) return;
  return run(
    () => matchmakingInteractionsApi.requestContactExchange(String(detail.value?.mutual_match_id)),
    t("mm.detail.exchangeRequested"),
    load
  );
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('ia.groups.matchmaking')"
    :title="t('mm.detail.title')"
    :description="t('mm.detail.description')"
    :breadcrumbs="[...breadcrumbs, { label: matchId }]"
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
      <VCard>
        <template #title>
          <h2>{{ t("mm.detail.factsTitle") }}</h2>
        </template>
        <VDescriptionList :items="facts" />
      </VCard>

      <VCard v-if="!detail.invitation_status">
        <template #title>
          <h2>{{ t("mm.detail.inviteTitle") }}</h2>
        </template>
        <template #description>
          {{ t("mm.detail.inviteDescription") }}
        </template>
        <label class="field">
          <span>{{ t("mm.detail.messageLabel") }}</span>
          <textarea
            v-model="invitationMessage"
            maxlength="500"
            :placeholder="t('mm.detail.messagePlaceholder')"
          />
        </label>
        <template #footer>
          <VButton
            :loading="busy"
            @click="sendInvitation"
          >
            {{ t("mm.detail.sendInvitation") }}
          </VButton>
        </template>
      </VCard>

      <VCard v-else>
        <template #title>
          <h2>{{ t("mm.detail.inviteExistsTitle") }}</h2>
        </template>
        <template #footer>
          <RouterLink :to="localePath(`account/matchmaking/invitations/${detail.invitation_id}`)">
            {{ t("mm.detail.openInvitation") }}
          </RouterLink>
        </template>
      </VCard>

      <VCard
        v-if="detail.status === 'introduction_accepted'"
        tone="soft"
      >
        <template #title>
          <h2>{{ t("mm.detail.contactTitle") }}</h2>
        </template>
        <template #description>
          {{ t("mm.detail.contactDescription") }}
        </template>
        <template #footer>
          <VButton
            v-if="!detail.contact_exchange_id"
            variant="secondary"
            @click="requestExchange"
          >
            {{ t("mm.detail.requestExchange") }}
          </VButton>
          <RouterLink
            v-else
            :to="localePath(`account/matchmaking/contact-exchanges/${detail.contact_exchange_id}`)"
          >
            {{ t("mm.detail.manageExchange") }}
          </RouterLink>
        </template>
      </VCard>
    </template>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
.field { display: grid; gap: var(--vav-space-2); }
.field span { font-weight: var(--vav-font-weight-semibold); font-size: var(--vav-font-size-sm); }

.field textarea {
  min-block-size: 7rem;
  padding: var(--vav-space-3);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-radius-sm);
  background: var(--vav-color-surface-raised);
  color: var(--vav-color-text);
  font: inherit;
}
</style>
