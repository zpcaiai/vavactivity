<script setup lang="ts">
import { VAlert, VButton, VCard, VMetric, VPageState, VSection } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { matchmakingAccessApiClient } from "@/features/matchmaking-access/api";
import type {
  GenerationResult,
  MatchmakingEntitlement,
  WaitPoolState
} from "@/features/matchmaking-access/types";

const { t, d } = useI18n();

const entitlement = ref<MatchmakingEntitlement | null>(null);
const waitPool = ref<WaitPoolState | null>(null);
const lastResult = ref<GenerationResult | null>(null);
const loading = ref(true);
const generating = ref(false);
const error = ref<string | null>(null);
const errorCode = ref<string | null>(null);

/**
 * 403 here means the member is not single. That is the MATCH-001 gate doing its
 * job, so it renders as a state rather than as a failure — and no quota is
 * shown at all, because a balance readout is itself matchmaking data.
 */
const notAvailable = computed(() => errorCode.value === "MATCHMAKING_NOT_AVAILABLE");

const exhausted = computed(() => (entitlement.value?.balance ?? 0) <= 0);

const canGenerate = computed(
  () => !generating.value && !exhausted.value && entitlement.value !== null
);

/** Only surface a disclaimer that an editor actually approved. */
const disclaimer = computed(() => lastResult.value?.disclaimer ?? null);

async function load() {
  loading.value = true;
  error.value = null;
  errorCode.value = null;
  try {
    entitlement.value = await matchmakingAccessApiClient.entitlement();
    waitPool.value = await matchmakingAccessApiClient.waitPool();
  } catch (caught) {
    error.value = (caught as Error).message;
    errorCode.value = (caught as Error & { code?: string }).code ?? null;
  } finally {
    loading.value = false;
  }
}

async function generate() {
  generating.value = true;
  error.value = null;
  errorCode.value = null;
  try {
    const result = await matchmakingAccessApiClient.generate();
    lastResult.value = result;
    if (entitlement.value) entitlement.value = { ...entitlement.value, balance: result.balance };
    waitPool.value = await matchmakingAccessApiClient.waitPool();
  } catch (caught) {
    error.value = (caught as Error).message;
    errorCode.value = (caught as Error & { code?: string }).code ?? null;
  } finally {
    generating.value = false;
  }
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    :title="t('matchmakingAccess.entitlement.title')"
    :description="t('matchmakingAccess.entitlement.description')"
    :eyebrow="t('matchmakingAccess.eyebrow')"
  >
    <VPageState
      v-if="loading"
      state="loading"
      :title="t('common.loading')"
      :message="t('matchmakingAccess.entitlement.loadingMessage')"
    />

    <VPageState
      v-else-if="notAvailable"
      state="restricted"
      :title="t('matchmakingAccess.entitlement.unavailableTitle')"
      :message="t('matchmakingAccess.entitlement.unavailableMessage')"
    />

    <VPageState
      v-else-if="error && !entitlement"
      state="error"
      :title="t('common.errorTitle')"
      :message="error"
      @action="load"
    />

    <template v-else-if="entitlement">
      <div class="entitlement__metrics">
        <VMetric
          :label="t('matchmakingAccess.entitlement.remaining')"
          :value="entitlement.balance"
          :tone="entitlement.balance > 0 ? 'brand' : 'warning'"
          :hint="t('matchmakingAccess.entitlement.remainingHint', { granted: entitlement.granted })"
        />
        <VMetric
          :label="t('matchmakingAccess.entitlement.used')"
          :value="entitlement.consumed"
        />
        <VMetric
          :label="t('matchmakingAccess.entitlement.perAttempt')"
          :value="entitlement.max_candidates_per_attempt"
          :hint="t('matchmakingAccess.entitlement.perAttemptHint')"
        />
      </div>

      <VAlert
        v-if="error"
        tone="danger"
        live
        :title="t('common.errorTitle')"
      >
        {{ error }}
      </VAlert>

      <VAlert
        v-if="lastResult && !lastResult.consumed"
        tone="info"
        live
        :title="t('matchmakingAccess.entitlement.noNewTitle')"
      >
        {{ t("matchmakingAccess.entitlement.noNewMessage") }}
      </VAlert>

      <VAlert
        v-else-if="lastResult && lastResult.consumed"
        tone="success"
        live
        :title="t('matchmakingAccess.entitlement.deliveredTitle')"
      >
        {{
          t("matchmakingAccess.entitlement.deliveredMessage", {
            count: lastResult.candidates.length
          })
        }}
      </VAlert>

      <VAlert
        v-if="waitPool && (waitPool.status === 'waiting' || waitPool.status === 'notified')"
        tone="info"
        :title="t('matchmakingAccess.waitPool.title')"
      >
        {{ t("matchmakingAccess.waitPool.message") }}
      </VAlert>

      <div class="entitlement__actions">
        <VButton
          :loading="generating"
          :disabled="!canGenerate"
          @click="generate"
        >
          {{ t("matchmakingAccess.entitlement.generate") }}
        </VButton>
      </div>

      <p
        v-if="exhausted"
        class="entitlement__exhausted"
      >
        {{ t("matchmakingAccess.entitlement.exhausted") }}
      </p>

      <VCard
        v-if="disclaimer"
        tone="soft"
      >
        <p class="entitlement__disclaimer">
          {{ disclaimer.body }}
        </p>
      </VCard>

      <VSection
        v-if="entitlement.ledger.length > 0"
        :title="t('matchmakingAccess.entitlement.ledgerTitle')"
        :description="t('matchmakingAccess.entitlement.ledgerDescription')"
      >
        <ul class="entitlement__ledger">
          <li
            v-for="(entry, index) in entitlement.ledger"
            :key="index"
          >
            <span>{{ t(`matchmakingAccess.entitlement.reason.${entry.reason}`) }}</span>
            <span>{{ entry.delta > 0 ? `+${entry.delta}` : entry.delta }}</span>
            <span>{{ d(new Date(entry.created_at), "long") }}</span>
          </li>
        </ul>
      </VSection>
    </template>
  </UserPageLayout>
</template>

<style scoped>
.entitlement__metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
  gap: var(--vav-space-4);
  margin-bottom: var(--vav-space-5);
}

.entitlement__actions {
  display: flex;
  justify-content: flex-end;
  margin: var(--vav-space-5) 0;
}

.entitlement__exhausted,
.entitlement__disclaimer {
  color: var(--vav-color-text-secondary);
}

.entitlement__ledger {
  display: grid;
  gap: var(--vav-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.entitlement__ledger li {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: var(--vav-space-4);
  padding: var(--vav-space-2) 0;
  border-bottom: var(--vav-border-width) solid var(--vav-color-border-subtle);
  color: var(--vav-color-text-secondary);
}
</style>
