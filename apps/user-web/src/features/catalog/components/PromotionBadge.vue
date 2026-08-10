<script setup lang="ts">
defineProps<{
  code: string;
}>();
</script>

<template>
  <span class="promotion-badge">{{ code }}</span>
</template>
