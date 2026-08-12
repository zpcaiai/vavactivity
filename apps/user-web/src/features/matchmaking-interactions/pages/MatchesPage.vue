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

const { sections, breadcrumbs, localePath, t } = useInteractionShell("matches");
const { busy, error } = useInteractionState();
const rows = ref<InteractionRow[]>([]);

async function load() {
  busy.value = true;
  error.value = "";
  try {
    rows.value = await matchmakingInteractionsApi.matches();
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
    :title="t('mm.matches.title')"
    :description="t('mm.matches.description')"
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
      class="match-grid"
    >
      <VCard
        v-for="row in rows"
        :key="String(row.mutual_match_id)"
        padding="compact"
      >
        <template #title>
          <h2>{{ t("mm.matches.item", { number: row.match_number }) }}</h2>
        </template>
        <template #actions>
          <VStatusBadge
            status="info"
            :label="String(row.status ?? '')"
          />
        </template>
        <p>{{ t("mm.matches.privacyNote") }}</p>
        <template #footer>
          <RouterLink :to="localePath(`account/matchmaking/matches/${row.mutual_match_id}`)">
            {{ t("mm.matches.open") }}
          </RouterLink>
        </template>
      </VCard>
    </div>

    <VPageState
      v-else
      state="empty"
      :title="t('mm.matches.emptyTitle')"
      :message="t('mm.matches.emptyMessage')"
    >
      <RouterLink
        class="match-empty-action"
        :to="localePath('recommendations')"
      >
        {{ t("mm.matches.goToRecommendations") }}
      </RouterLink>
    </VPageState>
  </UserPageLayout>
</template>

<style scoped>
.match-grid { display: grid; gap: var(--vav-space-4); grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); }
h2 { margin: 0; font-size: var(--vav-font-size-md); }
p { margin: 0; color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); }

.match-empty-action {
  display: inline-flex;
  align-items: center;
  min-block-size: var(--vav-component-button-height);
  padding-inline: var(--vav-space-4);
  border-radius: var(--vav-radius-pill);
  background: var(--vav-color-action-primary);
  color: var(--vav-color-on-action);
  text-decoration: none;
  font-weight: var(--vav-font-weight-semibold);
}
</style>
