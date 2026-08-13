<script setup lang="ts">
import { VCard, VChip, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, RouterLink } from "vue-router";

import { postEventApiClient } from "@/features/post-event/api";
import type { SurveyTask, SurveyTaskStatus } from "@/features/post-event/types";

const route = useRoute();
const { t } = useI18n();

const tasks = ref<SurveyTask[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

const locale = computed(() => String(route.params.locale ?? "zh-CN"));

const outstanding = computed(() =>
  tasks.value.filter((task) => task.status === "pending" || task.status === "in_progress")
);
const finished = computed(() =>
  tasks.value.filter((task) => task.status === "completed" || task.status === "expired")
);

const toneFor: Record<SurveyTaskStatus, "neutral" | "brand" | "success" | "warning" | "danger"> = {
  pending: "warning",
  in_progress: "brand",
  completed: "success",
  expired: "danger",
  waived: "neutral"
};

function dueLabel(task: SurveyTask): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: task.display_timezone
  }).format(new Date(task.due_at));
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    tasks.value = (await postEventApiClient.surveyTasks()).items;
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    :title="t('postEvent.tasks.title')"
    :description="t('postEvent.tasks.description')"
    :eyebrow="t('postEvent.eyebrow')"
  >
    <VPageState
      v-if="loading"
      state="loading"
      :title="t('common.loading')"
      :message="t('postEvent.tasks.loadingMessage')"
    />

    <VPageState
      v-else-if="error"
      state="error"
      :title="t('common.errorTitle')"
      :message="error"
      @action="load"
    />

    <VPageState
      v-else-if="tasks.length === 0"
      state="empty"
      :title="t('postEvent.tasks.emptyTitle')"
      :message="t('postEvent.tasks.emptyMessage')"
    />

    <template v-else>
      <ul class="task-list">
        <li
          v-for="task in [...outstanding, ...finished]"
          :key="task.id"
        >
          <VCard>
            <div class="task-list__row">
              <div>
                <RouterLink
                  class="task-list__link"
                  :to="`/${locale}/account/surveys/${task.assignment_id}`"
                >
                  {{ task.title }}
                </RouterLink>
                <p class="task-list__due">
                  {{ t("postEvent.tasks.dueAt", { time: dueLabel(task) }) }}
                </p>
              </div>
              <VChip
                :tone="toneFor[task.status]"
                :label="t(`postEvent.tasks.status.${task.status}`)"
              />
            </div>
          </VCard>
        </li>
      </ul>
    </template>
  </UserPageLayout>
</template>

<style scoped>
.task-list {
  display: grid;
  gap: var(--vav-space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.task-list__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--vav-space-4);
}

.task-list__link {
  font-weight: var(--vav-font-weight-medium);
  color: var(--vav-color-text-primary);
}

.task-list__due {
  margin: var(--vav-space-1) 0 0;
  color: var(--vav-color-text-secondary);
}
</style>
