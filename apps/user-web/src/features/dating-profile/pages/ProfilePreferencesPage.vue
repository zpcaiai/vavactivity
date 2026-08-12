<script setup lang="ts">
import { onMounted } from "vue";
import { VAlert, VButton, VCard, VChip, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { useDatingProfile } from "@/features/dating-profile/composables/useDatingProfile";

const {
  preferences,
  busy,
  error,
  notice,
  exists,
  steps,
  breadcrumbs,
  localePath,
  t,
  ensureLoaded,
  savePreferences
} = useDatingProfile();

onMounted(() => void ensureLoaded());
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('ia.groups.matchmaking')"
    :title="t('dating.steps.preferences')"
    :description="t('dating.preferences.description')"
    :breadcrumbs="breadcrumbs('preferences')"
    :sections="steps"
    :sections-label="t('dating.stepsLabel')"
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
      v-if="!exists && !busy"
      state="empty"
      :title="t('dating.emptyTitle')"
      :message="t('dating.emptyMessage')"
    >
      <RouterLink :to="localePath('account/dating-profile')">
        {{ t("dating.goToOverview") }}
      </RouterLink>
    </VPageState>

    <template v-else-if="preferences">
      <VAlert
        tone="info"
        :title="t('dating.preferences.boundaryTitle')"
      >
        {{ t("dating.preferences.boundary") }}
      </VAlert>

      <VCard>
        <template #title>
          <h2>{{ t("dating.preferences.criteriaTitle") }}</h2>
        </template>
        <ul
          v-if="preferences.criteria.length"
          class="criteria-list"
        >
          <li
            v-for="criterion in preferences.criteria"
            :key="criterion.criterion_code"
          >
            <div class="criteria-list__head">
              <strong>{{ criterion.criterion_code }}</strong>
              <VChip
                tone="neutral"
                :label="criterion.operator"
              />
              <VChip
                tone="neutral"
                :label="criterion.importance"
              />
              <VChip
                v-if="criterion.hard_constraint"
                tone="danger"
                :label="t('dating.preferences.hard')"
              />
            </div>
            <code>{{ JSON.stringify(criterion.desired_value) }}</code>
          </li>
        </ul>
        <p v-else>
          {{ t("dating.preferences.empty") }}
        </p>

        <VAlert
          v-if="preferences.hard_constraints.length"
          tone="warning"
          :title="t('dating.preferences.hardListTitle')"
        >
          {{ preferences.hard_constraints.map((item) => item.criterion_code).join("、") }}
        </VAlert>

        <label class="preference-toggle">
          <input
            v-model="preferences.allow_recommendation_relaxation"
            type="checkbox"
          >
          <span>{{ t("dating.preferences.allowRelaxation") }}</span>
        </label>

        <template #footer>
          <VButton
            :loading="busy"
            @click="savePreferences"
          >
            {{ t("dating.preferences.save") }}
          </VButton>
        </template>
      </VCard>
    </template>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
p { color: var(--vav-color-text-muted); margin: 0; }
.criteria-list { display: grid; gap: var(--vav-space-3); list-style: none; margin: 0; padding: 0; }
.criteria-list li { border-block-end: 1px solid var(--vav-color-border); display: grid; gap: var(--vav-space-1); padding-block-end: var(--vav-space-2); }
.criteria-list__head { align-items: center; display: flex; flex-wrap: wrap; gap: var(--vav-space-2); }
code { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-xs); }
.preference-toggle { align-items: center; display: flex; gap: var(--vav-space-2); }
</style>
