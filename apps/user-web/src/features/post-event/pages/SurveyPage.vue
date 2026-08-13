<script setup lang="ts">
import { VAlert, VButton, VPageState, VSection } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";
import { computed, onMounted } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import SurveyQuestionField from "@/features/post-event/components/SurveyQuestionField.vue";
import { useSurveyResponse } from "@/features/post-event/composables/useSurveyResponse";

const route = useRoute();
const { t } = useI18n();

const assignmentId = computed(() => String(route.params.assignmentId ?? ""));

const {
  detail,
  questions,
  subjects,
  loading,
  saving,
  error,
  errorCode,
  savedAt,
  isSubmitted,
  deadline,
  deadlinePassed,
  notYetOpen,
  editable,
  missingRequired,
  canSubmit,
  get,
  set,
  load,
  save
} = useSurveyResponse();

onMounted(() => load(assignmentId.value));

/**
 * The deadline is enforced in UTC by the server but shown to the member in the
 * activity's own timezone — the same instant, described where they were.
 */
const deadlineLabel = computed(() => {
  if (!deadline.value || !detail.value) return "";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: detail.value.display_timezone
  }).format(deadline.value);
});

const notFound = computed(() => errorCode.value === "SURVEY_TASK_NOT_FOUND");

function onSubmit() {
  void save(assignmentId.value, "submitted");
}

function onSaveDraft() {
  void save(assignmentId.value, "draft");
}
</script>

<template>
  <UserPageLayout
    :title="detail?.definition.title ?? t('postEvent.survey.title')"
    :description="detail?.definition.description ?? t('postEvent.survey.description')"
    :eyebrow="t('postEvent.eyebrow')"
    width="reading"
  >
    <VPageState
      v-if="loading"
      state="loading"
      :title="t('common.loading')"
      :message="t('postEvent.survey.loadingMessage')"
    />

    <VPageState
      v-else-if="notFound"
      state="restricted"
      :title="t('postEvent.survey.notFoundTitle')"
      :message="t('postEvent.survey.notFoundMessage')"
    />

    <VPageState
      v-else-if="error && !detail"
      state="error"
      :title="t('common.errorTitle')"
      :message="error"
      @action="load(assignmentId)"
    />

    <template v-else-if="detail">
      <VAlert
        v-if="notYetOpen"
        tone="info"
        :title="t('postEvent.survey.notOpenTitle')"
      >
        {{ t("postEvent.survey.notOpenMessage") }}
      </VAlert>

      <VAlert
        v-else-if="deadlinePassed"
        tone="warning"
        :title="t('postEvent.survey.closedTitle')"
      >
        {{ t("postEvent.survey.closedMessage", { deadline: deadlineLabel }) }}
      </VAlert>

      <VAlert
        v-else
        tone="info"
        :title="t('postEvent.survey.deadlineTitle')"
      >
        {{
          t("postEvent.survey.deadlineMessage", {
            deadline: deadlineLabel,
            timezone: detail.display_timezone
          })
        }}
      </VAlert>

      <VAlert
        v-if="isSubmitted && editable"
        tone="success"
        :title="t('postEvent.survey.submittedTitle')"
      >
        {{ t("postEvent.survey.submittedEditable") }}
      </VAlert>

      <VAlert
        v-if="error"
        tone="danger"
        live
        :title="t('common.errorTitle')"
      >
        {{ error }}
      </VAlert>

      <VSection
        v-for="question in questions"
        :key="question.id"
        :title="`${question.position}. ${question.prompt}`"
        :level="3"
      >
        <template v-if="question.per_subject">
          <SurveyQuestionField
            v-for="subject in subjects"
            :key="`${question.id}-${subject.user_id}`"
            :question="question"
            :answer="get(question.question_code, subject.user_id)"
            :subject-user-id="subject.user_id"
            :subject-name="subject.display_name"
            :disabled="!editable"
            @update="set"
          />
          <p
            v-if="subjects.length === 0"
            class="survey__empty-subjects"
          >
            {{ t("postEvent.survey.noSubjects") }}
          </p>
        </template>

        <SurveyQuestionField
          v-else
          :question="question"
          :answer="get(question.question_code)"
          :disabled="!editable"
          @update="set"
        />
      </VSection>

      <p
        v-if="missingRequired.length > 0 && editable"
        class="survey__missing"
        role="status"
      >
        {{ t("postEvent.survey.missingRequired", { count: missingRequired.length }) }}
      </p>

      <p
        v-if="savedAt"
        class="survey__saved"
        role="status"
      >
        {{ t("postEvent.survey.savedAt", { time: savedAt.toLocaleTimeString() }) }}
      </p>

      <div class="survey__actions">
        <VButton
          variant="secondary"
          :disabled="!editable || saving"
          @click="onSaveDraft"
        >
          {{ t("postEvent.survey.saveDraft") }}
        </VButton>
        <VButton
          :loading="saving"
          :disabled="!canSubmit"
          @click="onSubmit"
        >
          {{ t("postEvent.survey.submit") }}
        </VButton>
      </div>
    </template>
  </UserPageLayout>
</template>

<style scoped>
.survey__empty-subjects,
.survey__missing,
.survey__saved {
  color: var(--vav-color-text-secondary);
}

.survey__missing {
  color: var(--vav-color-warning-text);
}

.survey__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--vav-space-3);
  margin-top: var(--vav-space-6);
}
</style>
