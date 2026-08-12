<script setup lang="ts">
import { onMounted, ref } from "vue";
import { VAlert, VCard, VPageState, VStatusBadge } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import {
  matchmakingInteractionsApi,
  type InteractionRow
} from "@/features/matchmaking-interactions/api";
import {
  useInteractionShell,
  useInteractionState
} from "@/features/matchmaking-interactions/composables/useInteractionShell";

const { sections, breadcrumbs, localePath, t } = useInteractionShell("invitations");
const { busy, error } = useInteractionState();
const rows = ref<InteractionRow[]>([]);

async function load() {
  busy.value = true;
  error.value = "";
  try {
    rows.value = await matchmakingInteractionsApi.invitations();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("mm.loadError");
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="wide"
    :eyebrow="t('ia.groups.matchmaking')"
    :title="t('mm.invitations.title')"
    :description="t('mm.invitations.description')"
    :breadcrumbs="breadcrumbs"
    :sections="sections"
    :sections-label="t('mm.sectionsLabel')"
  >
    <VAlert
      v-if="error"
      tone="danger"
      :title="t('common.loadFailed')"
    >
      {{ error }}
    </VAlert>

    <VPageState
      v-if="busy"
      state="loading"
      :title="t('common.loading')"
      :message="t('common.pleaseWait')"
    />

    <div
      v-else-if="rows.length"
      class="invitation-grid"
    >
      <VCard
        v-for="row in rows"
        :key="String(row.invitation_id)"
        padding="compact"
      >
        <template #title>
          <h2>
            {{ row.role === "sender" ? t("mm.invitations.sent") : t("mm.invitations.received") }}
          </h2>
        </template>
        <template #actions>
          <VStatusBadge
            :status="row.status === 'pending' ? 'warning' : 'info'"
            :label="String(row.status ?? '')"
          />
        </template>
        <template #footer>
          <RouterLink :to="localePath(`account/matchmaking/invitations/${row.invitation_id}`)">
            {{ t("mm.invitations.open") }}
          </RouterLink>
        </template>
      </VCard>
    </div>

    <VPageState
      v-else
      state="empty"
      :title="t('mm.invitations.emptyTitle')"
      :message="t('mm.invitations.emptyMessage')"
    />
  </UserPageLayout>
</template>

<style scoped>
.invitation-grid { display: grid; gap: var(--vav-space-4); grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); }
h2 { margin: 0; font-size: var(--vav-font-size-md); }
</style>
