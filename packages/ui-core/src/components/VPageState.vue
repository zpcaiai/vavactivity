<script setup lang="ts">
withDefaults(defineProps<{ state: "loading" | "empty" | "filtered-empty" | "partial" | "error" | "offline" | "forbidden" | "restricted" | "maintenance"; title: string; message: string; actionLabel?: string }>(), { actionLabel: "重试" });
defineEmits<{ action: [] }>();
</script>
<template><section class="v-page-state" :data-state="state" :aria-busy="state === 'loading' || undefined" :role="state === 'error' ? 'alert' : 'status'"><span aria-hidden="true">{{ state === 'error' ? '×' : state === 'loading' ? '…' : 'i' }}</span><h2>{{ title }}</h2><p>{{ message }}</p><button v-if="$attrs.onAction" type="button" @click="$emit('action')">{{ actionLabel }}</button><slot /></section></template>
