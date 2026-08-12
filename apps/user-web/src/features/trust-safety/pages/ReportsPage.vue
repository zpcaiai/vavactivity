<script setup lang="ts">
import { onMounted, ref } from "vue";
import { VAlert, VButton, VCard, VPageState, VStatusBadge } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { safetyApi, type SafetyReport } from "@/features/trust-safety/api";
import {
  REPORT_CATEGORIES,
  useSafetyShell,
  useSafetyState
} from "@/features/trust-safety/composables/useSafetyShell";

const { sections, breadcrumbs, t } = useSafetyShell("reports");
const { busy, error, notice, guard } = useSafetyState();

const reports = ref<SafetyReport[]>([]);
const reportedUserId = ref("");
const category = ref<string>(REPORT_CATEGORIES[0]);
const description = ref("");
const blockTogether = ref(true);
const immediateDanger = ref(false);
const evidenceReportId = ref("");
const evidenceContent = ref("");

async function load() {
  const value = await guard(() => safetyApi.reports());
  if (value) reports.value = value;
}

async function submit() {
  if (!reportedUserId.value.trim()) {
    error.value = t("safety.reports.userRequired");
    return;
  }
  await guard(
    () =>
      safetyApi.report({
        target_type: "user",
        reported_user_id: reportedUserId.value.trim(),
        category: category.value,
        description: description.value || undefined,
        block_user: blockTogether.value,
        immediate_danger: immediateDanger.value,
        idempotency_key: `safety-report-${crypto.randomUUID()}`,
        source_context: { surface: "user_safety_center" }
      }),
    blockTogether.value ? t("safety.reports.submittedWithBlock") : t("safety.reports.submitted")
  );
  description.value = "";
  reportedUserId.value = "";
  await load();
}

async function uploadEvidence() {
  if (!evidenceReportId.value || !evidenceContent.value.trim()) {
    error.value = t("safety.reports.evidenceRequired");
    return;
  }
  await guard(
    () =>
      safetyApi.uploadEvidence(evidenceReportId.value, {
        evidence_type: "text",
        content: evidenceContent.value.trim(),
        collection_reason: "reporter_submission"
      }),
    t("safety.reports.evidenceStored")
  );
  evidenceContent.value = "";
}

async function withdraw(report: SafetyReport) {
  if (!window.confirm(t("safety.reports.withdrawConfirm"))) return;
  await guard(() => safetyApi.withdrawReport(report.id), t("safety.reports.withdrawn"));
  await load();
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="wide"
    :eyebrow="t('safety.eyebrow')"
    :title="t('safety.reports.title')"
    :description="t('safety.reports.description')"
    :breadcrumbs="breadcrumbs"
    :sections="sections"
    :sections-label="t('safety.sectionsLabel')"
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

    <div class="report-layout">
      <VCard tone="danger">
        <template #title>
          <h2>{{ t("safety.reports.formTitle") }}</h2>
        </template>
        <template #description>
          {{ t("safety.reports.formDescription") }}
        </template>
        <form
          class="report-form"
          @submit.prevent="submit"
        >
          <label>
            <span>{{ t("safety.reports.userId") }}</span>
            <input
              v-model="reportedUserId"
              autocomplete="off"
              required
            >
          </label>
          <label>
            <span>{{ t("safety.reports.category") }}</span>
            <select v-model="category">
              <option
                v-for="item in REPORT_CATEGORIES"
                :key="item"
                :value="item"
              >
                {{ t(`safety.reports.categories.${item}`) }}
              </option>
            </select>
          </label>
          <label>
            <span>{{ t("safety.reports.details") }}</span>
            <textarea
              v-model="description"
              maxlength="5000"
            />
          </label>
          <label class="report-form__check">
            <input
              v-model="blockTogether"
              type="checkbox"
            >
            <span>{{ t("safety.reports.blockToo") }}</span>
          </label>
          <label class="report-form__check">
            <input
              v-model="immediateDanger"
              type="checkbox"
            >
            <span>{{ t("safety.reports.immediateDanger") }}</span>
          </label>
          <VButton
            type="submit"
            variant="danger"
            :loading="busy"
          >
            {{ t("safety.reports.submit") }}
          </VButton>
        </form>
      </VCard>

      <div class="report-side">
        <VCard padding="compact">
          <template #title>
            <h2>{{ t("safety.reports.myReports") }}</h2>
          </template>
          <ul
            v-if="reports.length"
            class="report-list"
          >
            <li
              v-for="item in reports"
              :key="item.id"
            >
              <div>
                <strong>{{ item.report_number }}</strong>
                <small>{{ t(`safety.reports.categories.${item.category}`) }} · {{ item.submitted_at }}</small>
              </div>
              <div class="report-list__actions">
                <VStatusBadge
                  :status="item.status === 'resolved' ? 'success' : 'info'"
                  :label="item.status"
                />
                <VButton
                  v-if="item.status === 'submitted' || item.status === 'received'"
                  variant="secondary"
                  @click="withdraw(item)"
                >
                  {{ t("safety.reports.withdraw") }}
                </VButton>
              </div>
            </li>
          </ul>
          <VPageState
            v-else
            state="empty"
            :title="t('safety.reports.emptyTitle')"
            :message="t('safety.reports.emptyMessage')"
          />
        </VCard>

        <VCard
          v-if="reports.length"
          padding="compact"
        >
          <template #title>
            <h2>{{ t("safety.reports.evidenceTitle") }}</h2>
          </template>
          <template #description>
            {{ t("safety.reports.evidenceDescription") }}
          </template>
          <form
            class="report-form"
            @submit.prevent="uploadEvidence"
          >
            <label>
              <span>{{ t("safety.reports.evidenceReport") }}</span>
              <select
                v-model="evidenceReportId"
                required
              >
                <option
                  value=""
                  disabled
                >
                  {{ t("safety.reports.evidenceChoose") }}
                </option>
                <option
                  v-for="item in reports"
                  :key="item.id"
                  :value="item.id"
                >
                  {{ item.report_number }}
                </option>
              </select>
            </label>
            <label>
              <span>{{ t("safety.reports.evidenceContent") }}</span>
              <textarea
                v-model="evidenceContent"
                maxlength="20000"
                required
              />
            </label>
            <VButton
              type="submit"
              variant="secondary"
              :loading="busy"
            >
              {{ t("safety.reports.evidenceUpload") }}
            </VButton>
          </form>
        </VCard>
      </div>
    </div>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
small { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-xs); }
.report-layout { display: grid; gap: var(--vav-space-4); grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); align-items: start; }
.report-side { display: grid; gap: var(--vav-space-4); }
.report-form { display: grid; gap: var(--vav-space-3); }
.report-form label { display: grid; gap: var(--vav-space-1); }
.report-form label span { font-size: var(--vav-font-size-sm); font-weight: var(--vav-font-weight-semibold); }
.report-form__check { align-items: center; display: flex !important; gap: var(--vav-space-2); }
.report-form__check span { font-weight: var(--vav-font-weight-regular) !important; }

.report-form :where(input, select, textarea) {
  background: var(--vav-color-surface-raised);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-component-input-radius);
  color: var(--vav-color-text);
  font: inherit;
  min-block-size: var(--vav-component-input-height);
  padding: var(--vav-space-2) var(--vav-component-input-padding-inline);
}

.report-form textarea { min-block-size: 6.5rem; }
.report-list { display: grid; gap: var(--vav-space-3); list-style: none; margin: 0; padding: 0; }
.report-list li { align-items: center; border-block-end: 1px solid var(--vav-color-border); display: flex; flex-wrap: wrap; gap: var(--vav-space-3); justify-content: space-between; padding-block-end: var(--vav-space-2); }
.report-list li div:first-child { display: grid; }
.report-list__actions { align-items: center; display: flex; gap: var(--vav-space-2); }

@media (max-width: 64rem) {
  .report-layout { grid-template-columns: minmax(0, 1fr); }
}
</style>
