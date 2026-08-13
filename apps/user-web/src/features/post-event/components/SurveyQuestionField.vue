<script setup lang="ts">
import { VChip, VFormField } from "@vav/ui-core";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { SurveyAnswer, SurveyQuestion } from "@/features/post-event/types";

const props = defineProps<{
  question: SurveyQuestion;
  answer?: SurveyAnswer;
  subjectUserId?: string | null;
  subjectName?: string;
  disabled: boolean;
}>();

const emit = defineEmits<{ (event: "update", answer: SurveyAnswer): void }>();

const { t } = useI18n();

const fieldId = computed(
  () => `q-${props.question.question_code}-${props.subjectUserId ?? "event"}`
);

const scale = computed(() => {
  const min = props.question.config.scale_min ?? 1;
  const max = props.question.config.scale_max ?? 5;
  return Array.from({ length: max - min + 1 }, (_, index) => min + index);
});

const options = computed(() => props.question.config.options ?? []);
const maxLength = computed(() => props.question.config.max_length ?? 2000);
const maxChoices = computed(() =>
  props.question.question_type === "single_choice"
    ? 1
    : (props.question.config.max_selections ?? options.value.length)
);

const chosen = computed(() => props.answer?.choice_values ?? []);
const textValue = computed(() => props.answer?.text_value ?? "");
const remaining = computed(() => maxLength.value - textValue.value.length);

function base(): SurveyAnswer {
  return {
    question_code: props.question.question_code,
    subject_user_id: props.subjectUserId ?? null
  };
}

function setRating(value: number) {
  emit("update", { ...base(), rating_value: value });
}

function setBoolean(value: boolean) {
  emit("update", { ...base(), boolean_value: value });
}

function setText(event: Event) {
  emit("update", { ...base(), text_value: (event.target as HTMLTextAreaElement).value });
}

function toggleChoice(option: string) {
  if (props.question.question_type === "single_choice") {
    emit("update", { ...base(), choice_values: [option] });
    return;
  }
  const next = chosen.value.includes(option)
    ? chosen.value.filter((item) => item !== option)
    : [...chosen.value, option];
  // Refuse a pick that would exceed the configured ceiling rather than letting
  // the server reject the whole submission later.
  if (next.length > maxChoices.value) return;
  emit("update", { ...base(), choice_values: next });
}
</script>

<template>
  <VFormField
    :id="fieldId"
    :label="subjectName ? `${question.prompt} · ${subjectName}` : question.prompt"
    :hint="question.help_text ?? undefined"
    :required="question.is_required"
  >
    <div
      v-if="question.question_type === 'rating' || question.question_type === 'segment_rating'"
      class="survey-field__scale"
      role="radiogroup"
      :aria-label="question.prompt"
    >
      <button
        v-for="value in scale"
        :key="value"
        type="button"
        role="radio"
        class="survey-field__scale-button"
        :aria-checked="answer?.rating_value === value"
        :data-active="answer?.rating_value === value ? 'true' : 'false'"
        :disabled="disabled"
        @click="setRating(value)"
      >
        {{ value }}
      </button>
    </div>

    <div
      v-else-if="question.question_type === 'boolean'"
      class="survey-field__row"
    >
      <button
        v-for="option in [true, false]"
        :key="String(option)"
        type="button"
        class="survey-field__choice"
        :data-active="answer?.boolean_value === option ? 'true' : 'false'"
        :aria-pressed="answer?.boolean_value === option"
        :disabled="disabled"
        @click="setBoolean(option)"
      >
        {{ option ? t("common.yes") : t("common.no") }}
      </button>
    </div>

    <div
      v-else-if="question.question_type === 'single_choice' || question.question_type === 'multi_choice'"
      class="survey-field__row"
    >
      <button
        v-for="option in options"
        :key="option"
        type="button"
        class="survey-field__choice"
        :data-active="chosen.includes(option) ? 'true' : 'false'"
        :aria-pressed="chosen.includes(option)"
        :disabled="disabled"
        @click="toggleChoice(option)"
      >
        {{ option }}
      </button>
    </div>

    <template v-else>
      <textarea
        :id="fieldId"
        class="survey-field__textarea"
        rows="4"
        :maxlength="maxLength"
        :value="textValue"
        :disabled="disabled"
        @input="setText"
      />
      <VChip
        class="survey-field__counter"
        :tone="remaining < 50 ? 'warning' : 'neutral'"
        :label="t('postEvent.survey.charactersLeft', { count: remaining })"
      />
    </template>
  </VFormField>
</template>

<style scoped>
.survey-field__scale,
.survey-field__row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--vav-space-2);
}

.survey-field__scale-button,
.survey-field__choice {
  min-width: 3rem;
  min-height: 3rem;
  padding: 0 var(--vav-space-3);
  border: var(--vav-border-width) solid var(--vav-color-border-default);
  border-radius: var(--vav-radius-sm);
  background: var(--vav-color-surface-default);
  color: var(--vav-color-text-primary);
  cursor: pointer;
}

.survey-field__scale-button[data-active="true"],
.survey-field__choice[data-active="true"] {
  border-color: var(--vav-color-brand-border);
  background: var(--vav-color-brand-surface);
  color: var(--vav-color-brand-text);
}

.survey-field__scale-button:disabled,
.survey-field__choice:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.survey-field__scale-button:focus-visible,
.survey-field__choice:focus-visible,
.survey-field__textarea:focus-visible {
  outline: var(--vav-focus-ring-width) solid var(--vav-color-focus-ring);
  outline-offset: 2px;
}

.survey-field__textarea {
  width: 100%;
  padding: var(--vav-space-3);
  border: var(--vav-border-width) solid var(--vav-color-border-default);
  border-radius: var(--vav-radius-sm);
  background: var(--vav-color-surface-default);
  color: var(--vav-color-text-primary);
  font: inherit;
  resize: vertical;
}

.survey-field__counter {
  align-self: flex-end;
  margin-top: var(--vav-space-2);
}
</style>
