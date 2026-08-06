<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
const props = defineProps<{ errors: Array<{ field: string; message: string }> }>();
const summary = ref<HTMLElement | null>(null);
watch(() => props.errors, async (value) => { if (value.length) { await nextTick(); summary.value?.focus(); } }, { deep: true });
</script>

<template><section v-if="errors.length" ref="summary" class="v-error-summary" role="alert" tabindex="-1" aria-labelledby="v-error-summary-title"><h2 id="v-error-summary-title">请修正以下问题</h2><ul><li v-for="error in errors" :key="error.field"><a :href="`#${error.field}`">{{ error.message }}</a></li></ul></section></template>
