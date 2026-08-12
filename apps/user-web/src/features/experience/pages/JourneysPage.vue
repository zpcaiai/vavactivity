<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { VAlert, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import ExperienceRowCard from "@/features/experience/components/ExperienceRowCard.vue";
import { experienceApi, type ExperienceRow } from "@/features/experience/api";
import { useAppNavigation } from "@/composables/useAppNavigation";

const { t } = useI18n();
const { localePath } = useAppNavigation();

const busy = ref(true);
const error = ref("");
const rows = ref<ExperienceRow[]>([]);

async function load() {
  busy.value = true;
  error.value = "";
  try {
    rows.value = await experienceApi.journeys();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("journeys.loadError");
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="wide"
    :eyebrow="t('ia.groups.overview')"
    :title="t('journeys.title')"
    :description="t('journeys.description')"
    :breadcrumbs="[
      { label: t('ia.groups.overview'), to: localePath('account/home') },
      { label: t('journeys.title') }
    ]"
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
      :title="t('journeys.loadingTitle')"
      :message="t('common.pleaseWait')"
    />

    <div
      v-else-if="rows.length"
      class="journeys-grid"
    >
      <ExperienceRowCard
        v-for="row in rows"
        :key="String(row.id ?? row.journey_code)"
        :row="row"
        :action-label="t('journeys.viewState')"
      />
    </div>

    <VPageState
      v-else
      state="empty"
      :title="t('journeys.emptyTitle')"
      :message="t('journeys.emptyMessage')"
    />
  </UserPageLayout>
</template>

<style scoped>
.journeys-grid { display: grid; gap: var(--vav-space-4); grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); }
</style>
