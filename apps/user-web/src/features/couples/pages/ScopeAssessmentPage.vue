<script setup lang="ts">
import { VAlert, VButton, VCard, VChip, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { couplesApiClient } from "@/features/couples/api";
import type { ScopeAssessment, ScopeReport, ScopeVersion } from "@/features/couples/types";

const route = useRoute();
const router = useRouter();
const { t, te } = useI18n();

const locale = computed(() => String(route.params.locale ?? "zh-CN"));
const assessmentId = computed(() => {
  const value = route.params.assessmentId;
  return typeof value === "string" && value.length ? value : null;
});

const versions = ref<ScopeVersion[]>([]);
const assessment = ref<ScopeAssessment | null>(null);
const report = ref<ScopeReport | null>(null);
const answers = ref<Record<string, number>>({});
const waitingOn = ref<string[]>([]);
const reasonCode = ref<string | null>(null);
const loading = ref(true);
const busy = ref(false);
const error = ref<string | null>(null);
const notice = ref<string | null>(null);

const submitted = computed(() => assessment.value?.my_status === "submitted");

/**
 * The report exists only once both partners have submitted. Until then the
 * server writes nothing and returns `report_ready: false`, so there is no
 * interim number for this page to show — and inventing one would be a wrong
 * answer dressed as a preview.
 */
const awaitingPartner = computed(
  () => submitted.value && !report.value && Boolean(waitingOn.value.length || reasonCode.value)
);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    versions.value = (await couplesApiClient.scopeVersions().catch(() => ({ items: [] }))).items;
    if (!assessmentId.value) return;
    assessment.value = await couplesApiClient.assessment(assessmentId.value);
    answers.value = { ...(assessment.value.my_answers as Record<string, number>) };
    if (assessment.value.state === "completed") {
      report.value = await couplesApiClient.report(assessmentId.value).catch(() => null);
    }
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    loading.value = false;
  }
}

async function start(versionId: string) {
  busy.value = true;
  error.value = null;
  try {
    const result = await couplesApiClient.startAssessment(versionId);
    await router.push(`/${locale.value}/account/couple/scope/${result.assessment_id}`);
    await load();
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    busy.value = false;
  }
}

async function save(submit: boolean) {
  if (!assessmentId.value) return;
  busy.value = true;
  error.value = null;
  notice.value = null;
  try {
    const result = await couplesApiClient.saveAnswers(assessmentId.value, {
      answers: answers.value,
      submit
    });
    waitingOn.value = result.waiting_on ?? [];
    reasonCode.value = result.reason_code ?? null;
    notice.value = submit ? t("scope.submitted") : t("scope.draftSaved");
    if (result.report_ready) {
      report.value = await couplesApiClient.report(assessmentId.value);
    }
    await load();
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    busy.value = false;
  }
}

function dimensionLabel(code: string): string {
  const key = `scope.dimensions.${code}`;
  return te(key) ? t(key) : code;
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
    :title="t('scope.title')"
    :description="t('scope.description')"
    :eyebrow="t('couples.eyebrow')"
  >
    <VPageState
      v-if="loading"
      state="loading"
      :title="t('common.loading')"
      :message="t('scope.loadingMessage')"
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

      <!-- No assessment selected: offer the published versions. -->
      <VCard v-if="!assessmentId">
        <h2 class="scope__heading">
          {{ t("scope.start.heading") }}
        </h2>
        <p
          v-if="!versions.length"
          class="scope__note"
        >
          {{ t("scope.start.noVersions") }}
        </p>
        <ul
          v-else
          class="scope__list"
        >
          <li
            v-for="version in versions"
            :key="version.id"
          >
            <div class="scope__version">
              <div>
                <p class="scope__version-title">
                  {{ version.version_label }}
                </p>
                <p class="scope__note">
                  {{ t("scope.start.algorithm", { version: version.algorithm_version }) }}
                </p>
              </div>
              <VButton
                :loading="busy"
                @click="start(version.id)"
              >
                {{ t("scope.start.action") }}
              </VButton>
            </div>
          </li>
        </ul>
      </VCard>

      <template v-else-if="assessment">
        <VCard>
          <h2 class="scope__heading">
            {{ t("scope.progress.heading") }}
          </h2>
          <div class="scope__chips">
            <VChip
              :tone="submitted ? 'success' : 'warning'"
              :label="t(`scope.participant.${assessment.my_status}`)"
            />
            <!--
              The partner's *progress* is shown; their answers are not, and are
              not fetchable from here — the server seals them per owner.
            -->
            <VChip
              v-if="assessment.partner"
              tone="neutral"
              :label="
                t('scope.progress.partner', {
                  status: t(`scope.participant.${assessment.partner.status}`)
                })
              "
            />
          </div>
        </VCard>

        <VAlert
          v-if="awaitingPartner"
          tone="info"
          :title="t('scope.waiting.title')"
        >
          {{
            reasonCode && te(`scope.waiting.${reasonCode}`)
              ? t(`scope.waiting.${reasonCode}`)
              : t("scope.waiting.default")
          }}
        </VAlert>

        <VCard v-if="report">
          <h2 class="scope__heading">
            {{ t("scope.report.heading") }}
          </h2>
          <p class="scope__note">
            {{ t("scope.report.generatedAt", { time: generatedLabel() }) }}
          </p>
          <ul class="scope__scores">
            <li
              v-for="dimension in report.dimensions"
              :key="dimension"
            >
              <span class="scope__score-label">{{ dimensionLabel(dimension) }}</span>
              <span class="scope__score-value">{{ report.scores[dimension] ?? "—" }}</span>
            </li>
          </ul>
          <!--
            Advice lives in its own field and is never merged into the scores.
            Rendering it separately keeps that boundary visible to the reader.
          -->
          <template v-if="report.advice">
            <h3 class="scope__subheading">
              {{ t("scope.report.adviceHeading") }}
            </h3>
            <p class="scope__advice">
              {{ report.advice }}
            </p>
          </template>
          <p
            v-else
            class="scope__note"
          >
            {{
              te(`scope.report.adviceStatus.${report.advice_status}`)
                ? t(`scope.report.adviceStatus.${report.advice_status}`)
                : t("scope.report.advicePending")
            }}
          </p>
        </VCard>

        <VCard v-else-if="!submitted">
          <h2 class="scope__heading">
            {{ t("scope.answers.heading") }}
          </h2>
          <p class="scope__note">
            {{ t("scope.answers.hint") }}
          </p>
          <p
            v-if="!Object.keys(answers).length"
            class="scope__note"
          >
            {{ t("scope.answers.empty") }}
          </p>
          <div class="scope__actions">
            <VButton
              variant="secondary"
              :loading="busy"
              @click="save(false)"
            >
              {{ t("scope.answers.saveDraft") }}
            </VButton>
            <VButton
              :loading="busy"
              @click="save(true)"
            >
              {{ t("scope.answers.submit") }}
            </VButton>
          </div>
        </VCard>
      </template>
    </template>
  </UserPageLayout>
</template>

<style scoped>
.scope__heading {
  margin: 0 0 var(--vav-space-2);
  font-size: var(--vav-font-size-lg);
  color: var(--vav-color-text-primary);
}

.scope__subheading {
  margin: var(--vav-space-4) 0 var(--vav-space-1);
  font-size: var(--vav-font-size-md);
  color: var(--vav-color-text-primary);
}

.scope__note,
.scope__advice {
  margin: var(--vav-space-1) 0 0;
  color: var(--vav-color-text-secondary);
}

.scope__advice {
  white-space: pre-wrap;
}

.scope__chips,
.scope__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--vav-space-2);
  margin-top: var(--vav-space-2);
}

.scope__list,
.scope__scores {
  display: grid;
  gap: var(--vav-space-2);
  margin: var(--vav-space-2) 0 0;
  padding: 0;
  list-style: none;
}

.scope__scores li {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--vav-space-3);
}

.scope__score-label {
  color: var(--vav-color-text-secondary);
}

.scope__score-value {
  font-weight: var(--vav-font-weight-bold);
  color: var(--vav-color-text-primary);
}

.scope__version {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--vav-space-4);
}

.scope__version-title {
  margin: 0;
  font-weight: var(--vav-font-weight-medium);
  color: var(--vav-color-text-primary);
}
</style>
