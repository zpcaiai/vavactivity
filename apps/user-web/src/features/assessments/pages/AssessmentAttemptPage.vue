<script setup lang="ts">
import { VAlert, VButton, VCard, VChip, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { assessmentsApiClient } from "@/features/assessments/api";
import type { AssessmentReport, Attempt } from "@/features/assessments/types";

const route = useRoute();
const router = useRouter();
const { t, te } = useI18n();

const locale = computed(() => String(route.params.locale ?? "zh-CN"));
const attemptId = computed(() => {
  const value = route.params.attemptId;
  return typeof value === "string" && value.length ? value : null;
});
const entitlementId = computed(() => {
  const value = route.params.entitlementId;
  return typeof value === "string" && value.length ? value : null;
});

const attempt = ref<Attempt | null>(null);
const report = ref<AssessmentReport | null>(null);
const answers = ref<Record<string, number>>({});
const loading = ref(true);
const busy = ref(false);
const error = ref<string | null>(null);
const notice = ref<string | null>(null);

const submitted = computed(() => attempt.value?.status === "submitted");

const unanswered = computed(() => {
  if (!attempt.value) return [];
  return attempt.value.questions.filter((question) => answers.value[question.question_code] === undefined);
});

const canSubmit = computed(() => Boolean(attempt.value) && unanswered.value.length === 0 && !submitted.value);

function scaleValues(min: number, max: number): number[] {
  return Array.from({ length: max - min + 1 }, (_, index) => min + index);
}

function dimensionLabel(code: string): string {
  const key = `assessments.dimensions.${code}`;
  return te(key) ? t(key) : code;
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    if (!attemptId.value && entitlementId.value) {
      // Landing on the entitlement route starts (or resumes) the attempt and
      // then redirects, so the attempt id always lives in the URL.
      const started = await assessmentsApiClient.startAttempt(entitlementId.value);
      await router.replace(`/${locale.value}/account/assessments/attempts/${started.attempt_id}`);
      return;
    }
    if (!attemptId.value) return;
    attempt.value = await assessmentsApiClient.attempt(attemptId.value);
    answers.value = { ...attempt.value.answers };
    if (attempt.value.status === "submitted") {
      report.value = await assessmentsApiClient.report(attemptId.value).catch(() => null);
    }
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    loading.value = false;
  }
}

async function save(submit: boolean) {
  if (!attemptId.value) return;
  busy.value = true;
  error.value = null;
  notice.value = null;
  try {
    const result = await assessmentsApiClient.saveAnswers(attemptId.value, {
      answers: answers.value,
      submit
    });
    notice.value = submit ? t("assessments.attempt.submitted") : t("assessments.attempt.draftSaved");
    if (result.report_id) {
      report.value = await assessmentsApiClient.report(attemptId.value);
    }
    await load();
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    busy.value = false;
  }
}

function generatedLabel(): string {
  if (!report.value) return "";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(report.value.generated_at));
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    :title="t('assessments.attempt.title')"
    :description="t('assessments.attempt.description')"
    :eyebrow="t('assessments.eyebrow')"
  >
    <VPageState
      v-if="loading"
      state="loading"
      :title="t('common.loading')"
      :message="t('assessments.attempt.loadingMessage')"
    />

    <template v-else>
      <VAlert
        v-if="error"
        tone="danger"
        :title="t('common.errorTitle')"
      >
        {{ error }}
      </VAlert>
      <VAlert
        v-if="notice"
        tone="success"
        :title="t('common.saved')"
      >
        {{ notice }}
      </VAlert>

      <VPageState
        v-if="!attempt"
        state="empty"
        :title="t('assessments.attempt.missingTitle')"
        :message="t('assessments.attempt.missingMessage')"
      />

      <template v-else>
        <VCard>
          <div class="attempt__chips">
            <VChip
              :tone="submitted ? 'success' : 'warning'"
              :label="t(`assessments.attempt.status.${attempt.status}`)"
            />
            <!--
              The version is pinned at purchase. Showing it means a member can
              tell which edition they were scored on if the catalogue moves on.
            -->
            <VChip
              tone="neutral"
              :label="attempt.semantic_version"
            />
          </div>
        </VCard>

        <VCard v-if="report">
          <h2 class="attempt__heading">
            {{ t("assessments.report.heading") }}
          </h2>
          <p class="attempt__note">
            {{ t("assessments.report.generatedAt", { time: generatedLabel() }) }}
          </p>
          <p class="attempt__note">
            {{ t("assessments.report.algorithm", { version: report.algorithm_version }) }}
          </p>
          <ul class="attempt__scores">
            <li
              v-for="(value, key) in report.scores"
              :key="key"
            >
              <span class="attempt__score-label">{{ dimensionLabel(String(key)) }}</span>
              <span class="attempt__score-value">{{ value }}</span>
            </li>
          </ul>
          <template v-if="report.advice">
            <h3 class="attempt__subheading">
              {{ t("assessments.report.adviceHeading") }}
            </h3>
            <p class="attempt__advice">
              {{ report.advice }}
            </p>
          </template>
        </VCard>

        <template v-else>
          <VCard
            v-for="question in attempt.questions"
            :key="question.question_code"
          >
            <p class="attempt__prompt">
              {{ question.prompt_text }}
            </p>
            <p class="attempt__note">
              {{ dimensionLabel(question.dimension_code) }}
            </p>
            <div
              class="attempt__scale"
              role="radiogroup"
              :aria-label="question.prompt_text"
            >
              <label
                v-for="value in scaleValues(question.scale_min, question.scale_max)"
                :key="value"
                class="attempt__scale-option"
              >
                <input
                  v-model.number="answers[question.question_code]"
                  type="radio"
                  :name="question.question_code"
                  :value="value"
                  :disabled="submitted"
                >
                <span>{{ value }}</span>
              </label>
            </div>
          </VCard>

          <p
            v-if="unanswered.length"
            class="attempt__note"
          >
            {{ t("assessments.attempt.remaining", { count: unanswered.length }) }}
          </p>

          <div class="attempt__actions">
            <VButton
              variant="secondary"
              :loading="busy"
              @click="save(false)"
            >
              {{ t("assessments.attempt.saveDraft") }}
            </VButton>
            <VButton
              :loading="busy"
              :disabled="!canSubmit"
              @click="save(true)"
            >
              {{ t("assessments.attempt.submit") }}
            </VButton>
          </div>
        </template>
      </template>
    </template>
  </UserPageLayout>
</template>

<style scoped>
.attempt__heading {
  margin: 0 0 var(--vav-space-2);
  font-size: var(--vav-font-size-lg);
  color: var(--vav-color-text-primary);
}

.attempt__subheading {
  margin: var(--vav-space-4) 0 var(--vav-space-1);
  font-size: var(--vav-font-size-md);
  color: var(--vav-color-text-primary);
}

.attempt__prompt {
  margin: 0;
  font-weight: var(--vav-font-weight-medium);
  color: var(--vav-color-text-primary);
}

.attempt__note,
.attempt__advice {
  margin: var(--vav-space-1) 0 0;
  color: var(--vav-color-text-secondary);
}

.attempt__advice {
  white-space: pre-wrap;
}

.attempt__chips,
.attempt__actions,
.attempt__scale {
  display: flex;
  flex-wrap: wrap;
  gap: var(--vav-space-2);
  margin-top: var(--vav-space-2);
}

.attempt__scale-option {
  display: inline-flex;
  align-items: center;
  gap: var(--vav-space-1);
  padding: var(--vav-space-1) var(--vav-space-2);
  border: 1px solid var(--vav-color-border-default);
  border-radius: var(--vav-radius-md);
  cursor: pointer;
}

.attempt__scores {
  display: grid;
  gap: var(--vav-space-2);
  margin: var(--vav-space-2) 0 0;
  padding: 0;
  list-style: none;
}

.attempt__scores li {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--vav-space-3);
}

.attempt__score-label {
  color: var(--vav-color-text-secondary);
}

.attempt__score-value {
  font-weight: var(--vav-font-weight-bold);
  color: var(--vav-color-text-primary);
}
</style>
