<script setup lang="ts">
import { onMounted, ref } from "vue";
import { VAlert, VCard, VMetric, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { safetyApi, type SafetyBlock, type SafetyReport } from "@/features/trust-safety/api";
import { useSafetyShell, useSafetyState } from "@/features/trust-safety/composables/useSafetyShell";

const { sections, breadcrumbs, localePath, t } = useSafetyShell("overview");
const { busy, error, guard } = useSafetyState();

const reports = ref<SafetyReport[]>([]);
const blocks = ref<SafetyBlock[]>([]);
const appeals = ref<Array<Record<string, unknown>>>([]);

async function load() {
  const [reportValue, blockValue, appealValue] = await Promise.all([
    guard(() => safetyApi.reports()),
    guard(() => safetyApi.blocks()),
    guard(() => safetyApi.appeals())
  ]);
  if (reportValue) reports.value = reportValue;
  if (blockValue) blocks.value = blockValue;
  if (appealValue) appeals.value = appealValue;
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="wide"
    :eyebrow="t('safety.eyebrow')"
    :title="t('safety.title')"
    :description="t('safety.description')"
    :breadcrumbs="breadcrumbs"
    :sections="sections"
    :sections-label="t('safety.sectionsLabel')"
  >
    <VAlert
      tone="warning"
      :title="t('safety.emergencyTitle')"
    >
      {{ t("safety.emergency") }}
    </VAlert>

    <VAlert
      v-if="error"
      tone="danger"
      :title="t('common.loadFailed')"
    >
      {{ error }}
    </VAlert>

    <VPageState
      v-if="busy && !reports.length && !blocks.length"
      state="loading"
      :title="t('common.loading')"
      :message="t('common.pleaseWait')"
    />

    <template v-else>
      <div class="safety-metrics">
        <VMetric
          :label="t('safety.sections.reports')"
          :value="reports.length"
          :to="localePath('account/safety/reports')"
        />
        <VMetric
          :label="t('safety.sections.blocks')"
          :value="blocks.length"
          :to="localePath('account/safety/blocks')"
        />
        <VMetric
          :label="t('safety.sections.appeals')"
          :value="appeals.length"
          :to="localePath('account/safety/appeals')"
        />
        <VMetric
          :label="t('safety.sections.restrictions')"
          :value="'→'"
          :to="localePath('account/safety/restrictions')"
        />
      </div>

      <VCard tone="soft">
        <template #title>
          <h2>{{ t("safety.noContactTitle") }}</h2>
        </template>
        <p>{{ t("safety.noContact") }}</p>
        <template #footer>
          <RouterLink
            class="safety-cta"
            :to="localePath('account/safety/reports')"
          >
            {{ t("safety.reportNow") }}
          </RouterLink>
          <RouterLink :to="localePath('safety-support')">
            {{ t("safety.supportTitle") }}
          </RouterLink>
        </template>
      </VCard>
    </template>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
p { margin: 0; color: var(--vav-color-text-muted); }
.safety-metrics { display: grid; gap: var(--vav-space-4); grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); }

.safety-cta {
  align-items: center;
  background: var(--vav-color-danger);
  border-radius: var(--vav-radius-pill);
  color: var(--vav-color-on-action);
  display: inline-flex;
  font-weight: var(--vav-font-weight-semibold);
  min-block-size: var(--vav-component-button-height);
  padding-inline: var(--vav-space-4);
  text-decoration: none;
}
</style>
