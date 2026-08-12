<script setup lang="ts">
import { onMounted, ref } from "vue";
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

const { sections, breadcrumbs, localePath, t } = useInteractionShell("likes");
const { busy, error, notice, run } = useInteractionState();
const rows = ref<InteractionRow[]>([]);

async function load() {
  busy.value = true;
  error.value = "";
  try {
    rows.value = await matchmakingInteractionsApi.outgoingLikes();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("mm.loadError");
  } finally {
    busy.value = false;
  }
}

function withdraw(row: InteractionRow) {
  if (!row.like_id || !window.confirm(t("mm.likes.confirmWithdraw"))) return;
  return run(
    () => matchmakingInteractionsApi.withdrawLike(String(row.like_id)),
    t("mm.likes.withdrawn"),
    load
  );
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="wide"
    :eyebrow="t('ia.groups.matchmaking')"
    :title="t('mm.likes.title')"
    :description="t('mm.likes.description')"
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
    <VAlert
      v-if="notice"
      tone="success"
      :title="t('common.done')"
      live
    >
      {{ notice }}
    </VAlert>

    <VPageState
      v-if="busy && !rows.length"
      state="loading"
      :title="t('common.loading')"
      :message="t('common.pleaseWait')"
    />

    <div
      v-else-if="rows.length"
      class="like-grid"
    >
      <VCard
        v-for="row in rows"
        :key="String(row.like_id)"
        padding="compact"
      >
        <template #title>
          <h2>{{ t("mm.likes.item") }}</h2>
        </template>
        <template #actions>
          <VStatusBadge
            :status="row.status === 'active' ? 'info' : 'warning'"
            :label="String(row.status ?? '')"
          />
        </template>
        <p>{{ row.created_at }}</p>
        <template #footer>
          <VButton
            v-if="row.status === 'active'"
            variant="secondary"
            @click="withdraw(row)"
          >
            {{ t("mm.likes.withdraw") }}
          </VButton>
        </template>
      </VCard>
    </div>

    <VPageState
      v-else
      state="empty"
      :title="t('mm.likes.emptyTitle')"
      :message="t('mm.likes.emptyMessage')"
    >
      <RouterLink
        class="like-empty-action"
        :to="localePath('recommendations')"
      >
        {{ t("mm.matches.goToRecommendations") }}
      </RouterLink>
    </VPageState>
  </UserPageLayout>
</template>

<style scoped>
.like-grid { display: grid; gap: var(--vav-space-4); grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); }
h2 { margin: 0; font-size: var(--vav-font-size-md); }
p { margin: 0; color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); }

.like-empty-action {
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
