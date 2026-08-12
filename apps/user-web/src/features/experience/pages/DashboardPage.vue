<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { VAlert, VCard, VMetric, VPageState, VSection } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import ExperienceRowCard from "@/features/experience/components/ExperienceRowCard.vue";
import { experienceApi, type ExperienceRow } from "@/features/experience/api";
import { useAppNavigation } from "@/composables/useAppNavigation";

const { t } = useI18n();
const { localePath, groups } = useAppNavigation();

const busy = ref(true);
const error = ref("");
const home = ref<ExperienceRow>({});

const criticalTasks = computed(() => (home.value.critical_tasks as ExperienceRow[] | undefined) ?? []);
const nextTasks = computed(() => (home.value.next_tasks as ExperienceRow[] | undefined) ?? []);
const membership = computed(
  () => (home.value.membership as Record<string, unknown> | undefined) ?? {}
);
const unread = computed(() => Number(home.value.unread_notifications ?? 0));
const activeJourneys = computed(() => Number(home.value.active_journeys ?? 0));

/** Quick entries mirror the sidebar so the two never disagree. */
const shortcuts = computed(() =>
  groups.value
    .filter((group) => group.key !== "overview")
    .flatMap((group) => group.items.slice(0, 2).map((item) => ({ ...item, group: group.label })))
);

async function load() {
  busy.value = true;
  error.value = "";
  try {
    home.value = await experienceApi.home();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("dashboard.loadError");
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="wide"
    :eyebrow="t('dashboard.eyebrow')"
    :title="t('dashboard.title')"
    :description="t('dashboard.description')"
  >
    <VAlert
      v-if="error"
      tone="danger"
      :title="t('common.loadFailed')"
    >
      {{ error }}
      <button
        type="button"
        class="link-button"
        @click="load"
      >
        {{ t("common.retry") }}
      </button>
    </VAlert>

    <VPageState
      v-if="busy"
      state="loading"
      :title="t('dashboard.loadingTitle')"
      :message="t('dashboard.loadingMessage')"
    />

    <template v-else>
      <div class="dashboard-metrics">
        <VMetric
          :label="t('dashboard.metrics.critical')"
          :value="criticalTasks.length"
          :tone="criticalTasks.length ? 'danger' : 'default'"
          :to="localePath('account/tasks')"
        />
        <VMetric
          :label="t('dashboard.metrics.next')"
          :value="nextTasks.length"
          :to="localePath('account/tasks')"
        />
        <VMetric
          :label="t('dashboard.metrics.unread')"
          :value="unread"
          :tone="unread ? 'info' : 'default'"
          :to="localePath('account/notifications')"
        />
        <VMetric
          :label="t('dashboard.metrics.journeys')"
          :value="activeJourneys"
          :to="localePath('account/journeys')"
        />
      </div>

      <VSection
        v-if="criticalTasks.length"
        :title="t('dashboard.criticalTitle')"
        :description="t('dashboard.criticalDescription')"
      >
        <div class="dashboard-cards">
          <ExperienceRowCard
            v-for="row in criticalTasks"
            :key="String(row.id ?? row.task_code)"
            :row="row"
            tone="danger"
            :action-label="t('dashboard.handleNow')"
          />
        </div>
      </VSection>

      <VSection
        :title="t('dashboard.nextTitle')"
        :description="t('dashboard.nextDescription')"
      >
        <div
          v-if="nextTasks.length"
          class="dashboard-cards"
        >
          <ExperienceRowCard
            v-for="row in nextTasks.slice(0, 6)"
            :key="String(row.id ?? row.task_code)"
            :row="row"
            :action-label="t('dashboard.continue')"
          />
        </div>
        <VPageState
          v-else
          state="empty"
          :title="t('dashboard.nextEmptyTitle')"
          :message="t('dashboard.nextEmptyMessage')"
        >
          <RouterLink
            class="dashboard-empty-action"
            :to="localePath('activities')"
          >
            {{ t("dashboard.exploreActivities") }}
          </RouterLink>
        </VPageState>
      </VSection>

      <div class="dashboard-split">
        <VCard tone="brand">
          <template #title>
            <h2>{{ t("dashboard.membershipTitle") }}</h2>
          </template>
          <template #description>
            {{ t("dashboard.membershipDescription") }}
          </template>
          <p class="dashboard-plan">
            {{ membership.plan_code ?? t("dashboard.noPlan") }}
          </p>
          <p class="dashboard-plan-status">
            {{ t("dashboard.planStatus") }}: {{ membership.status ?? "not_available" }}
          </p>
          <template #footer>
            <RouterLink :to="localePath('account/membership')">
              {{ t("dashboard.manageMembership") }}
            </RouterLink>
            <RouterLink :to="localePath('membership')">
              {{ t("dashboard.comparePlans") }}
            </RouterLink>
          </template>
        </VCard>

        <VCard tone="soft">
          <template #title>
            <h2>{{ t("dashboard.priorityTitle") }}</h2>
          </template>
          <template #description>
            {{ t("dashboard.priorityDescription") }}
          </template>
          <ol class="dashboard-priority">
            <li
              v-for="item in (home.priority_policy as string[] | undefined) ?? []"
              :key="item"
            >
              {{ t(`dashboard.priority.${item}`) }}
            </li>
          </ol>
        </VCard>
      </div>

      <VSection
        :title="t('dashboard.shortcutsTitle')"
        :description="t('dashboard.shortcutsDescription')"
      >
        <div class="dashboard-shortcuts">
          <RouterLink
            v-for="shortcut in shortcuts"
            :key="shortcut.key + shortcut.to"
            class="dashboard-shortcut"
            :to="shortcut.to"
          >
            <small>{{ shortcut.group }}</small>
            <strong>{{ shortcut.label }}</strong>
          </RouterLink>
        </div>
      </VSection>
    </template>
  </UserPageLayout>
</template>

<style scoped>
.dashboard-metrics,
.dashboard-cards,
.dashboard-shortcuts {
  display: grid;
  gap: var(--vav-space-4);
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
}

.dashboard-split { display: grid; gap: var(--vav-space-4); grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr)); }
.dashboard-split h2 { margin: 0; font-size: var(--vav-font-size-lg); }
.dashboard-plan { margin: 0; font-size: var(--vav-font-size-lg); font-weight: var(--vav-font-weight-bold); }
.dashboard-plan-status { margin: 0; color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); }
.dashboard-priority { margin: 0; padding-inline-start: var(--vav-space-5); color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); display: grid; gap: var(--vav-space-1); }

.dashboard-shortcut {
  display: grid;
  gap: var(--vav-space-1);
  padding: var(--vav-space-4);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-radius-md);
  background: var(--vav-color-surface-raised);
  color: var(--vav-color-text);
  text-decoration: none;
}

.dashboard-shortcut:hover { background: var(--vav-color-interactive-hover); }
.dashboard-shortcut small { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-xs); }

.dashboard-empty-action,
.link-button {
  display: inline-flex;
  align-items: center;
  min-block-size: var(--vav-component-nav-item-height);
  padding-inline: var(--vav-space-3);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-radius-pill);
  background: var(--vav-color-surface-raised);
  color: var(--vav-color-text);
  text-decoration: none;
  font: inherit;
  font-size: var(--vav-font-size-sm);
  cursor: pointer;
}
</style>
