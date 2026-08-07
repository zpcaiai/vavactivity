<script setup lang="ts">
import { computed, useId } from "vue";
const props = defineProps<{ label: string; error?: string; hint?: string; required?: boolean; id?: string }>();
const generated = useId();
const fieldId = computed(() => props.id ?? `v-field-${generated}`);
const describedBy = computed(() => [props.hint && `${fieldId.value}-hint`, props.error && `${fieldId.value}-error`].filter(Boolean).join(" ") || undefined);
</script>

<template><div class="v-field" :class="{ 'v-field--invalid': error }"><label :for="fieldId">{{ label }}<span v-if="required" aria-hidden="true"> *</span></label><p v-if="hint" :id="`${fieldId}-hint`" class="v-field__hint">{{ hint }}</p><slot :id="fieldId" :described-by="describedBy" :invalid="Boolean(error)" /><p v-if="error" :id="`${fieldId}-error`" class="v-field__error" role="alert">{{ error }}</p></div></template>
