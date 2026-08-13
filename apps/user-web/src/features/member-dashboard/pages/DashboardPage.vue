<script setup lang="ts">
import { VAlert, VButton, VCard, VChip, VPageState, VSection } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";
import { computed, onMounted } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute } from "vue-router";

import { useDashboard } from "@/features/member-dashboard/composables/useDashboard";
import type {
  DashboardSectionKey,
  DashboardSectionOk,
  DashboardTask,
  TaskPriority
} from "@/features/member-dashboard/types";
import { isSectionAvailable } from "@/features/member-dashboard/types";

const route = useRoute();
const { t, te } = useI18n();

const locale = computed(() => String(route.params.locale ?? "zh-CN"));

const {
  preferences,
  loading,
  error,
  busyTaskKey,
  orderedSections,
  visibleSections,
  hiddenCount,
  degraded,
  totalOpenTasks,
  urgentTasks,
  load,
  loadMore,
  toggleSection,
  dismiss
} = useDashboard();

onMounted(() => load(locale.value));

const priorityTone: Record<TaskPriority, "neutral" | "brand" | "success" | "warning" | "danger"> = {
  urgent: "danger",
  high: "warning",
  normal: "brand",
  low: "neutral"
};

/**
 * Localize from the server's `title_code`. The backend deliberately ships no
 * display copy, so an unknown code has to degrade to something readable rather
 * than render an empty row.
 */
function taskTitle(task: DashboardTask): string {
  const key = `memberDashboard.titles.${task.title_code}`;
  if (task.title_code && te(key)) return t(key);
  return t(`memberDashboard.taskTypes.${task.task_type}`);
}

function sectionLabel(key: DashboardSectionKey): string {
  return t(`memberDashboard.sections.${key}`);
}

function countFor(key: DashboardSectionKey): number | null {
  const section = orderedSections.value.find((entry) => entry.key === key)?.section;
  if (!section || !isSectionAvailable(section)) return null;
  return section.count;
}

/** Server-owned route; the locale prefix is the only thing added here. */
function taskLink(task: DashboardTask): string {
  return `/${locale.value}${task.deep_link}`;
}

function dueLabel(task: DashboardTask): string | null {
  if (!task.due_at) return null;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(task.due_at));
}

function itemsOf(section: DashboardSectionOk): DashboardTask[] {
  return section.items;
}

function isHidden(key: DashboardSectionKey): boolean {
  return preferences.value.hidden_sections.includes(key);
}
</script>

<template>
  <UserPageLayout
    :title="t('memberDashboard.title')"
    :description="t('memberDashboard.description')"
    :eyebrow="t('memberDashboard.eyebrow')"
    width="wide"
  >
    <VPageState
      v-if="loading"
      state="loading"
      :title="t('common.loading')"
      :message="t('memberDashboard.loadingMessage')"
    />

    <VPageState
      v-else-if="error && !orderedSections.length"
      state="error"
      :title="t('common.errorTitle')"
      :message="error"
      @action="load(locale)"
    />

    <template v-else>
      <!--
        A partial failure is reported, never hidden. The member is told which
        part of the board is missing so they do not read an incomplete list as
        a complete one.
      -->
      <VAlert
        v-if="degraded.length"
        tone="warning"
        :title="t('memberDashboard.degradedTitle')"
      >
        {{
          t("memberDashboard.degradedMessage", {
            sections: degraded.map(sectionLabel).join(t("common.listSeparator"))
          })
        }}
      </VAlert>

      <VAlert
        v-if="error"
        tone="danger"
        :title="t('common.errorTitle')"
      >
        {{ error }}
      </VAlert>

      <VCard class="dashboard__summary">
        <div class="dashboard__summary-row">
          <div>
            <p class="dashboard__summary-count">
              {{ totalOpenTasks }}
            </p>
            <p class="dashboard__summary-label">
              {{ t("memberDashboard.openTasks") }}
            </p>
          </div>
          <VChip
            v-if="urgentTasks.length"
            tone="danger"
            :label="t('memberDashboard.urgentCount', { count: urgentTasks.length })"
          />
        </div>
        <p
          v-if="degraded.length"
          class="dashboard__summary-note"
        >
          {{ t("memberDashboard.countExcludesDegraded") }}
        </p>
      </VCard>

      <VPageState
        v-if="!orderedSections.length"
        state="empty"
        :title="t('memberDashboard.emptyTitle')"
        :message="t('memberDashboard.emptyMessage')"
      />

      <VSection
        v-for="entry in visibleSections"
        :key="entry.key"
        :level="2"
        :title="sectionLabel(entry.key)"
      >
        <template #actions>
          <VChip
            v-if="countFor(entry.key) !== null"
            tone="neutral"
            :label="String(countFor(entry.key))"
          />
          <VButton
            variant="secondary"
            @click="toggleSection(entry.key)"
          >
            {{ t("memberDashboard.hideSection") }}
          </VButton>
        </template>

        <VAlert
          v-if="!isSectionAvailable(entry.section)"
          tone="warning"
          :title="t('memberDashboard.sectionUnavailableTitle')"
        >
          {{
            te(`memberDashboard.errors.${entry.section.error_code}`)
              ? t(`memberDashboard.errors.${entry.section.error_code}`)
              : t("memberDashboard.sectionUnavailableMessage")
          }}
        </VAlert>

        <template v-else>
          <p
            v-if="!itemsOf(entry.section).length"
            class="dashboard__section-empty"
          >
            {{ t("memberDashboard.sectionEmpty") }}
          </p>

          <ul
            v-else
            class="dashboard__tasks"
          >
            <li
              v-for="task in itemsOf(entry.section)"
              :key="task.task_key"
            >
              <VCard>
                <div class="dashboard__task">
                  <div class="dashboard__task-main">
                    <RouterLink
                      class="dashboard__task-link"
                      :to="taskLink(task)"
                    >
                      {{ taskTitle(task) }}
                    </RouterLink>
                    <p
                      v-if="dueLabel(task)"
                      class="dashboard__task-due"
                    >
                      {{ t("memberDashboard.dueAt", { time: dueLabel(task) }) }}
                    </p>
                  </div>
                  <div class="dashboard__task-side">
                    <VChip
                      :tone="priorityTone[task.priority]"
                      :label="t(`memberDashboard.priority.${task.priority}`)"
                    />
                    <VButton
                      variant="secondary"
                      :disabled="busyTaskKey === task.task_key"
                      @click="dismiss(task, locale)"
                    >
                      {{ t("memberDashboard.dismiss") }}
                    </VButton>
                  </div>
                </div>
              </VCard>
            </li>
          </ul>

          <VButton
            v-if="entry.section.has_more"
            variant="secondary"
            @click="loadMore(entry.key, locale)"
          >
            {{ t("memberDashboard.loadMore") }}
          </VButton>
        </template>
      </VSection>

      <VSection
        v-if="hiddenCount > 0"
        :level="2"
        :title="t('memberDashboard.hiddenTitle')"
      >
        <ul class="dashboard__hidden">
          <li
            v-for="entry in orderedSections.filter((item) => isHidden(item.key))"
            :key="entry.key"
          >
            <VButton
              variant="secondary"
              @click="toggleSection(entry.key)"
            >
              {{ t("memberDashboard.showSection", { section: sectionLabel(entry.key) }) }}
            </VButton>
          </li>
        </ul>
      </VSection>
    </template>
  </UserPageLayout>
</template>

<style scoped>
.dashboard__summary-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--vav-space-4);
}

.dashboard__summary-count {
  margin: 0;
  font-size: var(--vav-font-size-4xl);
  font-weight: var(--vav-font-weight-bold);
  color: var(--vav-color-text-primary);
}

.dashboard__summary-label,
.dashboard__summary-note {
  margin: var(--vav-space-1) 0 0;
  color: var(--vav-color-text-secondary);
}

.dashboard__tasks,
.dashboard__hidden {
  display: grid;
  gap: var(--vav-space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.dashboard__task {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--vav-space-4);
}

.dashboard__task-main {
  min-width: 0;
}

.dashboard__task-link {
  font-weight: var(--vav-font-weight-medium);
  color: var(--vav-color-text-primary);
}

.dashboard__task-due {
  margin: var(--vav-space-1) 0 0;
  color: var(--vav-color-text-secondary);
}

.dashboard__task-side {
  display: flex;
  align-items: center;
  gap: var(--vav-space-2);
  flex-shrink: 0;
}

.dashboard__section-empty {
  margin: 0;
  color: var(--vav-color-text-secondary);
}
</style>
