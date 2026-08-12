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

const { sections, breadcrumbs, t } = useInteractionShell("skips");
const { busy, error, notice, run } = useInteractionState();
const rows = ref<InteractionRow[]>([]);

async function load() {
  busy.value = true;
  error.value = "";
  try {
    rows.value = await matchmakingInteractionsApi.skips();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("mm.loadError");
  } finally {
    busy.value = false;
  }
}

function withdraw(row: InteractionRow) {
  if (!row.skip_id) return;
  return run(
    () => matchmakingInteractionsApi.withdrawSkip(String(row.skip_id)),
    t("mm.skips.withdrawn"),
    load
  );
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="wide"
    :eyebrow="t('ia.groups.matchmaking')"
    :title="t('mm.skips.title')"
    :description="t('mm.skips.description')"
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
      class="skip-grid"
    >
      <VCard
        v-for="row in rows"
        :key="String(row.skip_id)"
        padding="compact"
      >
        <template #title>
          <h2>{{ row.skip_type }}</h2>
        </template>
        <template #actions>
          <VStatusBadge
            :status="row.status === 'active' ? 'warning' : 'info'"
            :label="String(row.status ?? '')"
          />
        </template>
        <p>{{ t("mm.skips.cooldownUntil") }}: {{ row.cooldown_until ?? "-" }}</p>
        <template #footer>
          <VButton
            v-if="row.status === 'active'"
            variant="secondary"
            @click="withdraw(row)"
          >
            {{ t("mm.skips.withdraw") }}
          </VButton>
        </template>
      </VCard>
    </div>

    <VPageState
      v-else
      state="empty"
      :title="t('mm.skips.emptyTitle')"
      :message="t('mm.skips.emptyMessage')"
    />
  </UserPageLayout>
</template>

<style scoped>
.skip-grid { display: grid; gap: var(--vav-space-4); grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); }
h2 { margin: 0; font-size: var(--vav-font-size-md); }
p { margin: 0; color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); }
</style>
