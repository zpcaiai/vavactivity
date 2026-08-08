<script setup lang="ts">
withDefaults(defineProps<{ tone?: "info" | "success" | "warning" | "danger"; title: string; live?: boolean }>(), { tone: "info", live: false });
</script>

<template><section class="v-alert" :class="`v-alert--${tone}`" :role="tone === 'danger' ? 'alert' : 'status'" :aria-live="live ? 'polite' : undefined"><strong>{{ title }}</strong><div><slot /></div></section></template>
