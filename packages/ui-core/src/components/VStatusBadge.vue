<script setup lang="ts">
const props = defineProps<{ status: "success" | "warning" | "danger" | "info"; label: string }>();
const icons = { success: "✓", warning: "!", danger: "×", info: "i" } as const;
</script>

<template><span class="v-status" :class="`v-status--${status}`"><span aria-hidden="true">{{ icons[props.status] }}</span><span>{{ label }}</span></span></template>
