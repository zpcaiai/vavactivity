<script setup lang="ts">
import { VAlert, VButton, VCard, VChip, VFormField, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { matchmakingAccessApiClient } from "@/features/matchmaking-access/api";
import type {
  RelationshipStatus,
  RelationshipStatusValue
} from "@/features/matchmaking-access/types";

const { t } = useI18n();

const current = ref<RelationshipStatus | null>(null);
const draft = ref<RelationshipStatusValue>("undisclosed");
const reason = ref("");
const loading = ref(true);
const saving = ref(false);
const error = ref<string | null>(null);
const errorCode = ref<string | null>(null);
const saved = ref(false);

const options: RelationshipStatusValue[] = [
  "single",
  "dating",
  "engaged",
  "married",
  "separated",
  "widowed",
  "undisclosed"
];

/**
 * A status written by a confirmed partner binding cannot be self-declared away
 * — the member has to unbind first. Showing the control as locked is kinder
 * than letting them press it and collecting a 409.
 */
const lockedByBinding = computed(() => current.value?.source === "couple_binding");

const changed = computed(() => draft.value !== current.value?.status);

const canSave = computed(() => changed.value && !lockedByBinding.value && !saving.value);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const result = await matchmakingAccessApiClient.relationshipStatus();
    current.value = result;
    draft.value = result.status;
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    loading.value = false;
  }
}

async function save() {
  saving.value = true;
  error.value = null;
  errorCode.value = null;
  saved.value = false;
  try {
    const result = await matchmakingAccessApiClient.setRelationshipStatus(
      draft.value,
      reason.value.trim() || undefined
    );
    current.value = result;
    draft.value = result.status;
    reason.value = "";
    saved.value = true;
  } catch (caught) {
    error.value = (caught as Error).message;
    errorCode.value = (caught as Error & { code?: string }).code ?? null;
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    :title="t('matchmakingAccess.status.title')"
    :description="t('matchmakingAccess.status.description')"
    :eyebrow="t('matchmakingAccess.eyebrow')"
    width="reading"
  >
    <VPageState
      v-if="loading"
      state="loading"
      :title="t('common.loading')"
      :message="t('matchmakingAccess.status.loadingMessage')"
    />

    <template v-else-if="current">
      <VAlert
        :tone="current.matchmaking_available ? 'success' : 'info'"
        :title="
          current.matchmaking_available
            ? t('matchmakingAccess.status.openTitle')
            : t('matchmakingAccess.status.closedTitle')
        "
      >
        {{
          current.matchmaking_available
            ? t("matchmakingAccess.status.openMessage")
            : t("matchmakingAccess.status.closedMessage")
        }}
      </VAlert>

      <VAlert
        v-if="lockedByBinding"
        tone="warning"
        :title="t('matchmakingAccess.status.lockedTitle')"
      >
        {{ t("matchmakingAccess.status.lockedMessage") }}
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
        v-else-if="saved"
        tone="success"
        live
        :title="t('matchmakingAccess.status.savedTitle')"
      >
        {{ t("matchmakingAccess.status.savedMessage") }}
      </VAlert>

      <VCard>
        <VFormField
          :label="t('matchmakingAccess.status.fieldLabel')"
          :hint="t('matchmakingAccess.status.fieldHint')"
        >
          <div class="status__options">
            <VChip
              v-for="option in options"
              :key="option"
              :tone="draft === option ? 'brand' : 'neutral'"
              :label="t(`matchmakingAccess.status.values.${option}`)"
              class="status__option"
              role="button"
              tabindex="0"
              :aria-pressed="draft === option"
              @click="lockedByBinding ? undefined : (draft = option)"
              @keydown.enter.prevent="lockedByBinding ? undefined : (draft = option)"
              @keydown.space.prevent="lockedByBinding ? undefined : (draft = option)"
            />
          </div>
        </VFormField>

        <VFormField
          v-if="changed"
          :label="t('matchmakingAccess.status.reasonLabel')"
          :hint="t('matchmakingAccess.status.reasonHint')"
        >
          <input
            v-model="reason"
            class="status__reason"
            type="text"
            maxlength="500"
            :disabled="lockedByBinding"
          >
        </VFormField>

        <div class="status__actions">
          <VButton
            :loading="saving"
            :disabled="!canSave"
            @click="save"
          >
            {{ t("common.save") }}
          </VButton>
        </div>
      </VCard>
    </template>

    <VPageState
      v-else
      state="error"
      :title="t('common.errorTitle')"
      :message="error ?? t('common.unknownError')"
      @action="load"
    />
  </UserPageLayout>
</template>

<style scoped>
.status__options {
  display: flex;
  flex-wrap: wrap;
  gap: var(--vav-space-2);
}

.status__option {
  cursor: pointer;
}

.status__option:focus-visible {
  outline: var(--vav-focus-ring-width) solid var(--vav-color-focus-ring);
  outline-offset: 2px;
}

.status__reason {
  width: 100%;
  padding: var(--vav-space-3);
  border: var(--vav-border-width) solid var(--vav-color-border-default);
  border-radius: var(--vav-radius-sm);
  background: var(--vav-color-surface-default);
  color: var(--vav-color-text-primary);
  font: inherit;
}

.status__actions {
  display: flex;
  justify-content: flex-end;
  margin-top: var(--vav-space-5);
}
</style>
