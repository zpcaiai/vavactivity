<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { VAlert, VButton, VCard, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import ProfileProgress from "@/features/dating-profile/components/ProfileProgress.vue";
import {
  FIELD_GROUPS,
  NARRATIVE_FIELDS,
  useDatingProfile
} from "@/features/dating-profile/composables/useDatingProfile";
import type { FieldDefinition } from "@/features/dating-profile/api";

const {
  profile,
  completeness,
  fieldValues,
  narrativeValues,
  busy,
  error,
  notice,
  exists,
  completionPercent,
  missingRequired,
  steps,
  breadcrumbs,
  localePath,
  t,
  ensureLoaded,
  fieldsForGroup,
  taxonomyFor,
  saveFields,
  saveNarratives
} = useDatingProfile();

const group = ref(FIELD_GROUPS[0].key);
const aiAssisted = ref(false);
const aiConfirmed = ref(false);

const fields = computed(() => fieldsForGroup(group.value));
const isNarrative = computed(() => group.value === "narratives");

function labelFor(field: FieldDefinition) {
  return field.field_code.split(".").slice(1).join(".");
}

function textValue(fieldCode: string) {
  const value = fieldValues[fieldCode];
  return typeof value === "string" ? value : "";
}

function setText(fieldCode: string, event: Event) {
  fieldValues[fieldCode] = (event.target as HTMLInputElement | HTMLTextAreaElement).value;
}

onMounted(() => void ensureLoaded());
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('ia.groups.matchmaking')"
    :title="t('dating.steps.edit')"
    :description="t('dating.editDescription')"
    :breadcrumbs="breadcrumbs('edit')"
    :sections="steps"
    :sections-label="t('dating.stepsLabel')"
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

    <VPageState
      v-if="busy && !profile"
      state="loading"
      :title="t('common.loading')"
      :message="t('common.pleaseWait')"
    />

    <VPageState
      v-else-if="!exists"
      state="empty"
      :title="t('dating.emptyTitle')"
      :message="t('dating.emptyMessage')"
    >
      <RouterLink :to="localePath('account/dating-profile')">
        {{ t("dating.goToOverview") }}
      </RouterLink>
    </VPageState>

    <template v-else>
      <ProfileProgress
        :profile="profile"
        :completeness="completeness"
        :percent="completionPercent"
        :missing-count="missingRequired.length"
        :measure-note="t('dating.measureNote')"
        :missing-label="t('dating.missingRequired')"
        :number-label="t('dating.number')"
        :status-label="t('dating.status')"
        :review-label="t('dating.review')"
        :approved-label="t('dating.approvedVersion')"
        :progress-label="t('dating.completeness')"
      />

      <nav
        class="group-nav"
        :aria-label="t('dating.groupsLabel')"
      >
        <button
          v-for="item in FIELD_GROUPS"
          :key="item.key"
          type="button"
          :data-active="group === item.key || undefined"
          @click="group = item.key"
        >
          {{ t(`dating.groups.${item.key}`) }}
        </button>
      </nav>

      <VCard v-if="isNarrative">
        <template #title>
          <h2>{{ t("dating.groups.narratives") }}</h2>
        </template>
        <template #description>
          {{ t("dating.narrativeBoundary") }}
        </template>
        <form
          class="profile-form"
          @submit.prevent="saveNarratives(aiAssisted, aiConfirmed)"
        >
          <label
            v-for="key in NARRATIVE_FIELDS"
            :key="key"
            class="profile-form__field"
          >
            <span>{{ t(`dating.narratives.${key}`) }}</span>
            <textarea
              v-model="narrativeValues[key]"
              rows="4"
            />
            <small>{{ t(`dating.narrativeHints.${key}`) }}</small>
          </label>

          <label class="profile-form__check">
            <input
              v-model="aiAssisted"
              type="checkbox"
            >
            <span>{{ t("dating.aiAssisted") }}</span>
          </label>
          <label
            v-if="aiAssisted"
            class="profile-form__check"
          >
            <input
              v-model="aiConfirmed"
              type="checkbox"
            >
            <span>{{ t("dating.aiConfirmed") }}</span>
          </label>

          <VButton
            type="submit"
            :loading="busy"
          >
            {{ t("dating.saveNarratives") }}
          </VButton>
        </form>
      </VCard>

      <VCard v-else-if="fields.length">
        <template #title>
          <h2>{{ t(`dating.groups.${group}`) }}</h2>
        </template>
        <form
          class="profile-form"
          @submit.prevent="saveFields(fields)"
        >
          <div
            v-for="field in fields"
            :key="field.field_code"
            class="profile-form__field"
          >
            <label :for="field.field_code">
              <span>{{ labelFor(field) }}</span>
              <small
                v-if="field.required_for_submission"
                class="profile-form__required"
              >{{ t("dating.required") }}</small>
              <small>{{ field.sensitivity }}</small>
            </label>

            <select
              v-if="field.field_type === 'enum' && taxonomyFor(field).length"
              :id="field.field_code"
              v-model="fieldValues[field.field_code]"
            >
              <option value="">
                {{ t("dating.notFilled") }}
              </option>
              <option
                v-for="value in taxonomyFor(field)"
                :key="value.code"
                :value="value.code"
              >
                {{ value.label }}
              </option>
            </select>

            <select
              v-else-if="field.field_type === 'enum_set'"
              :id="field.field_code"
              v-model="fieldValues[field.field_code]"
              multiple
            >
              <option
                v-for="value in taxonomyFor(field)"
                :key="value.code"
                :value="value.code"
              >
                {{ value.label }}
              </option>
            </select>

            <input
              v-else-if="field.field_type === 'boolean'"
              :id="field.field_code"
              v-model="fieldValues[field.field_code]"
              type="checkbox"
            >

            <input
              v-else-if="field.field_type === 'integer' || field.field_type === 'scale'"
              :id="field.field_code"
              v-model.number="fieldValues[field.field_code]"
              type="number"
            >

            <textarea
              v-else-if="field.field_type === 'encrypted_text'"
              :id="field.field_code"
              :value="textValue(field.field_code)"
              rows="3"
              @input="setText(field.field_code, $event)"
            />

            <input
              v-else
              :id="field.field_code"
              :value="textValue(field.field_code)"
              type="text"
              @input="setText(field.field_code, $event)"
            >

            <small
              v-if="missingRequired.includes(field.field_code)"
              class="profile-form__missing"
            >
              {{ t("dating.requiredForSubmission") }}
            </small>
          </div>

          <VButton
            type="submit"
            :loading="busy"
          >
            {{ t("dating.saveSection") }}
          </VButton>
        </form>
      </VCard>

      <VPageState
        v-else
        state="empty"
        :title="t('dating.noFieldsTitle')"
        :message="t('dating.noFieldsMessage')"
      />
    </template>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
.group-nav { display: flex; flex-wrap: wrap; gap: var(--vav-space-2); }

.group-nav button {
  background: var(--vav-color-surface-raised);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-radius-pill);
  color: var(--vav-color-text);
  cursor: pointer;
  font: inherit;
  font-size: var(--vav-font-size-sm);
  min-block-size: var(--vav-component-nav-item-height);
  padding-inline: var(--vav-space-4);
}

.group-nav button[data-active] { background: var(--vav-color-interactive-selected); border-color: var(--vav-color-action-primary); color: var(--vav-color-action-primary); font-weight: var(--vav-font-weight-semibold); }
.profile-form { display: grid; gap: var(--vav-space-4); }
.profile-form__field { display: grid; gap: var(--vav-space-1); }
.profile-form__field > label, .profile-form__field > span { align-items: center; display: flex; flex-wrap: wrap; gap: var(--vav-space-2); font-weight: var(--vav-font-weight-semibold); font-size: var(--vav-font-size-sm); }
.profile-form__field small { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-xs); font-weight: var(--vav-font-weight-regular); }
.profile-form__required, .profile-form__missing { color: var(--vav-color-danger) !important; }
.profile-form__check { align-items: center; display: flex; gap: var(--vav-space-2); }

.profile-form :where(input:not([type="checkbox"]), select, textarea) {
  background: var(--vav-color-surface-raised);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-component-input-radius);
  color: var(--vav-color-text);
  font: inherit;
  min-block-size: var(--vav-component-input-height);
  padding: var(--vav-space-2) var(--vav-component-input-padding-inline);
}
</style>
