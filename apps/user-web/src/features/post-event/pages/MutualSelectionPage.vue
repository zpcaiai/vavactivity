<script setup lang="ts">
import { VAlert, VButton, VCard, VChip, VFormField, VPageState, VSection } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";
import { computed, onMounted } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import CandidateChoiceCard from "@/features/post-event/components/CandidateChoiceCard.vue";
import { useMutualSelection } from "@/features/post-event/composables/useMutualSelection";

const route = useRoute();
const { t, te, d } = useI18n();

const activityId = computed(() => String(route.params.activityId ?? ""));

const {
  board,
  selectedIds,
  reasonCode,
  reasonNote,
  loading,
  saving,
  error,
  errorCode,
  notice,
  maxSelections,
  remaining,
  hasSelection,
  requiresReason,
  requiresNote,
  isSubmitted,
  editableUntil,
  editWindowClosed,
  canSubmit,
  isSelected,
  toggle,
  load,
  save
} = useMutualSelection();

onMounted(() => load(activityId.value));

const atCeiling = computed(() => selectedIds.value.length >= maxSelections.value);

/**
 * A member who did not check in is not a candidate and gets 403 from the
 * server. That is a state, not a failure — say so plainly instead of showing a
 * generic error.
 */
const notEligible = computed(
  () => errorCode.value === "SELECTION_NOT_ELIGIBLE" || errorCode.value === "SNAPSHOT_NOT_FROZEN"
);

function reasonLabel(code: string): string {
  const key = `postEvent.passReasons.${code}`;
  return te(key) ? t(key) : code;
}

function onSubmit() {
  void save(activityId.value, "submitted");
}

function onSaveDraft() {
  void save(activityId.value, "draft");
}
</script>

<template>
  <UserPageLayout
    :title="t('postEvent.selection.title')"
    :description="t('postEvent.selection.description')"
    :eyebrow="t('postEvent.eyebrow')"
    width="wide"
  >
    <VPageState
      v-if="loading"
      state="loading"
      :title="t('common.loading')"
      :message="t('postEvent.selection.loadingMessage')"
    />

    <VPageState
      v-else-if="notEligible"
      state="restricted"
      :title="t('postEvent.selection.notEligibleTitle')"
      :message="t('postEvent.selection.notEligibleMessage')"
    />

    <VPageState
      v-else-if="error && !board"
      state="error"
      :title="t('common.errorTitle')"
      :message="error"
      @action="load(activityId)"
    />

    <template v-else-if="board">
      <VAlert
        v-if="isSubmitted && !editWindowClosed"
        tone="success"
        :title="t('postEvent.selection.submittedTitle')"
      >
        {{
          editableUntil
            ? t("postEvent.selection.editableUntil", { time: d(editableUntil, "long") })
            : t("postEvent.selection.submittedMessage")
        }}
      </VAlert>

      <VAlert
        v-else-if="editWindowClosed"
        tone="info"
        :title="t('postEvent.selection.lockedTitle')"
      >
        {{ t("postEvent.selection.lockedMessage") }}
      </VAlert>

      <VAlert
        v-if="error"
        tone="danger"
        live
        :title="t('common.errorTitle')"
      >
        {{ error }}
      </VAlert>

      <VAlert
        v-else-if="notice === 'draft'"
        tone="info"
        live
        :title="t('postEvent.selection.draftSavedTitle')"
      >
        {{ t("postEvent.selection.draftSavedMessage") }}
      </VAlert>

      <VSection
        :title="t('postEvent.selection.candidatesTitle')"
        :description="
          t('postEvent.selection.counter', {
            selected: selectedIds.length,
            max: maxSelections
          })
        "
      >
        <p
          id="selection-limit-hint"
          class="selection__hint"
        >
          {{ t("postEvent.selection.limitHint", { max: maxSelections, remaining }) }}
        </p>

        <VPageState
          v-if="board.candidates.length === 0"
          state="empty"
          :title="t('postEvent.selection.emptyTitle')"
          :message="t('postEvent.selection.emptyMessage')"
        />

        <div
          v-else
          class="selection__grid"
        >
          <CandidateChoiceCard
            v-for="candidate in board.candidates"
            :key="candidate.user_id"
            :candidate="candidate"
            :selected="isSelected(candidate.user_id)"
            :blocked="atCeiling"
            :disabled="editWindowClosed"
            @toggle="toggle"
          />
        </div>
      </VSection>

      <VSection
        v-if="requiresReason"
        :title="t('postEvent.selection.reasonTitle')"
        :description="t('postEvent.selection.reasonDescription')"
      >
        <VCard>
          <div class="selection__reasons">
            <VChip
              v-for="option in board.pass_reasons"
              :key="option.reason_code"
              :tone="reasonCode === option.reason_code ? 'brand' : 'neutral'"
              :label="reasonLabel(option.reason_code)"
              class="selection__reason"
              role="button"
              tabindex="0"
              @click="reasonCode = option.reason_code"
              @keydown.enter.prevent="reasonCode = option.reason_code"
              @keydown.space.prevent="reasonCode = option.reason_code"
            />
          </div>

          <VFormField
            v-if="requiresNote"
            :label="t('postEvent.selection.reasonNoteLabel')"
            :hint="t('postEvent.selection.reasonNoteHint')"
            required
          >
            <textarea
              v-model="reasonNote"
              class="selection__note"
              rows="3"
              maxlength="1000"
              :disabled="editWindowClosed"
            />
          </VFormField>
        </VCard>
      </VSection>

      <div class="selection__actions">
        <VButton
          variant="secondary"
          :disabled="editWindowClosed || saving"
          @click="onSaveDraft"
        >
          {{ t("postEvent.selection.saveDraft") }}
        </VButton>
        <VButton
          :loading="saving"
          :disabled="!canSubmit"
          @click="onSubmit"
        >
          {{ hasSelection ? t("postEvent.selection.submit") : t("postEvent.selection.submitNone") }}
        </VButton>
      </div>
    </template>
  </UserPageLayout>
</template>

<style scoped>
.selection__hint {
  margin-bottom: var(--vav-space-4);
  color: var(--vav-color-text-secondary);
}

.selection__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr));
  gap: var(--vav-space-4);
}

.selection__reasons {
  display: flex;
  flex-wrap: wrap;
  gap: var(--vav-space-2);
  margin-bottom: var(--vav-space-4);
}

.selection__reason {
  cursor: pointer;
}

.selection__reason:focus-visible {
  outline: var(--vav-focus-ring-width) solid var(--vav-color-focus-ring);
  outline-offset: 2px;
}

.selection__note {
  width: 100%;
  padding: var(--vav-space-3);
  border: var(--vav-border-width) solid var(--vav-color-border-default);
  border-radius: var(--vav-radius-sm);
  background: var(--vav-color-surface-default);
  color: var(--vav-color-text-primary);
  font: inherit;
  resize: vertical;
}

.selection__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--vav-space-3);
  margin-top: var(--vav-space-6);
}
</style>
