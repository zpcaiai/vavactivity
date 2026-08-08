<script setup lang="ts">withDefaults(defineProps<{ message: string; assertive?: boolean }>(), { assertive: false });</script>
<template><div class="v-live-region" :role="assertive ? 'alert' : 'status'" :aria-live="assertive ? 'assertive' : 'polite'" aria-atomic="true">{{ message }}</div></template>
