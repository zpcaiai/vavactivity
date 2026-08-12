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
const { breadcrumbs, t } = useInteractionShell("invitations");
const { busy, error, notice, run } = useInteractionState();

const detail = ref<InteractionRow>();
const declineReason = ref("");
const invitationId = computed(() => String(route.params.id ?? ""));

const facts = computed(() => [
  { term: t("mm.detail.status"), value: String(detail.value?.status ?? "-") },
  { term: t("mm.invitations.role"), value: String(detail.value?.role ?? "-") }
]);

async function load() {
  busy.value = true;
  error.value = "";
  try {
    detail.value = await matchmakingInteractionsApi.invitation(invitationId.value);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("mm.loadError");
  } finally {
    busy.value = false;
  }
}

function decide(action: "accept" | "decline" | "cancel") {
  const invitation = detail.value;
  if (!invitation?.invitation_id || !invitation.invitation_version) return;
  const confirmation =
    action === "accept" ? t("mm.invitations.confirmAccept") : t("mm.invitations.confirmOther");
  if (!window.confirm(confirmation)) return;
  return run(
    () =>
      matchmakingInteractionsApi.invitationDecision(
        String(invitation.invitation_id),
        action,
        Number(invitation.invitation_version),
        declineReason.value || undefined
      ),
    t(`mm.invitations.${action}Done`),
    load
  );
}
onMounted(load);
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('ia.groups.matchmaking')"
    :title="t('mm.invitations.detailTitle')"
    :description="t('mm.invitations.detailDescription')"
    :breadcrumbs="[...breadcrumbs, { label: invitationId }]"
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
        <p v-if="detail.message">
          {{ t("mm.invitations.message") }}: {{ detail.message }}
        </p>
        <p v-if="detail.outcome_note">
          {{ detail.outcome_note }}
        </p>
      </VCard>

      <VCard v-if="detail.status === 'pending' && detail.role === 'recipient'">
        <template #title>
          <h2>{{ t("mm.invitations.decideTitle") }}</h2>
        </template>
        <template #description>
          {{ t("mm.invitations.decideDescription") }}
        </template>
        <label class="field">
          <span>{{ t("mm.invitations.declineReason") }}</span>
          <input
            v-model="declineReason"
            maxlength="128"
          >
        </label>
        <template #footer>
          <VButton @click="decide('accept')">
            {{ t("mm.invitations.accept") }}
          </VButton>
          <VButton
            variant="secondary"
            @click="decide('decline')"
          >
            {{ t("mm.invitations.decline") }}
          </VButton>
        </template>
      </VCard>

      <VCard v-else-if="detail.status === 'pending' && detail.role === 'sender'">
        <template #title>
          <h2>{{ t("mm.invitations.cancelTitle") }}</h2>
        </template>
        <template #footer>
          <VButton
            variant="secondary"
            @click="decide('cancel')"
          >
            {{ t("mm.invitations.cancel") }}
          </VButton>
        </template>
      </VCard>
    </template>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
p { margin: 0; color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); }
.field { display: grid; gap: var(--vav-space-2); }
.field span { font-weight: var(--vav-font-weight-semibold); font-size: var(--vav-font-size-sm); }

.field input {
  min-block-size: var(--vav-component-input-height);
  padding-inline: var(--vav-component-input-padding-inline);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-component-input-radius);
  background: var(--vav-color-surface-raised);
  color: var(--vav-color-text);
  font: inherit;
}
</style>
