<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import { VAlert, VButton, VPageState, VSection } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import ExperienceRowCard from "@/features/experience/components/ExperienceRowCard.vue";
import { experienceApi, type ExperienceRow } from "@/features/experience/api";
import { useAppNavigation } from "@/composables/useAppNavigation";
import { useAuthStore } from "@/stores/auth";

const { t } = useI18n();
const route = useRoute();
const auth = useAuthStore();
const { localePath } = useAppNavigation();

const busy = ref(true);
const error = ref("");
const notice = ref("");
const rows = ref<ExperienceRow[]>([]);

const includeHistory = computed(() => Boolean(route.query.history));
const critical = computed(() => rows.value.filter((row) => Number(row.priority ?? 0) >= 900));
const rest = computed(() => rows.value.filter((row) => Number(row.priority ?? 0) < 900));

async function load() {
  busy.value = true;
  error.value = "";
  try {
    rows.value = await experienceApi.tasks(includeHistory.value);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("tasks.loadError");
  } finally {
    busy.value = false;
  }
}

async function reportDeadEnd() {
  if (!auth.user) return;
  await experienceApi.feedback("user.tasks", "cannot_find_next_step");
  notice.value = t("tasks.feedbackRecorded");
}

onMounted(load);
watch(includeHistory, load);
</script>

<template>
  <UserPageLayout
    width="wide"
    :eyebrow="t('ia.groups.overview')"
    :title="t('tasks.title')"
    :description="t('tasks.description')"
    :breadcrumbs="[
      { label: t('ia.groups.overview'), to: localePath('account/home') },
      { label: t('tasks.title') }
    ]"
  >
    <template #actions>
      <RouterLink
        class="tasks-toggle"
        :to="includeHistory ? localePath('account/tasks') : `${localePath('account/tasks')}?history=1`"
      >
        {{ includeHistory ? t("tasks.hideHistory") : t("tasks.showHistory") }}
      </RouterLink>
      <VButton
        variant="secondary"
        @click="reportDeadEnd"
      >
        {{ t("tasks.cannotFindNext") }}
      </VButton>
    </template>

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
      :title="t('common.received')"
      live
    >
      {{ notice }}
    </VAlert>

    <VPageState
      v-if="busy"
      state="loading"
      :title="t('tasks.loadingTitle')"
      :message="t('tasks.loadingMessage')"
    />

    <template v-else-if="rows.length">
      <VSection
        v-if="critical.length"
        :title="t('tasks.criticalTitle')"
        :description="t('tasks.criticalDescription')"
      >
        <div class="tasks-grid">
          <ExperienceRowCard
            v-for="row in critical"
            :key="String(row.id ?? row.task_code)"
            :row="row"
            tone="danger"
            :action-label="t('dashboard.handleNow')"
          />
        </div>
      </VSection>

      <VSection
        :title="t('tasks.otherTitle')"
        :description="t('tasks.otherDescription')"
      >
        <div class="tasks-grid">
          <ExperienceRowCard
            v-for="row in rest"
            :key="String(row.id ?? row.task_code)"
            :row="row"
            :action-label="t('dashboard.continue')"
          />
        </div>
      </VSection>
    </template>

    <VPageState
      v-else
      state="empty"
      :title="t('tasks.emptyTitle')"
      :message="t('tasks.emptyMessage')"
    />
  </UserPageLayout>
</template>

<style scoped>
.tasks-grid { display: grid; gap: var(--vav-space-4); grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); }

.tasks-toggle {
  display: inline-flex;
  align-items: center;
  min-block-size: var(--vav-component-button-height);
  padding-inline: var(--vav-space-3);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-component-button-radius);
  background: var(--vav-color-surface-raised);
  color: var(--vav-color-text);
  text-decoration: none;
  font-size: var(--vav-font-size-sm);
}
</style>
