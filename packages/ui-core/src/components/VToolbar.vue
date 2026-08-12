<script setup lang="ts">
defineProps<{ label: string }>();
</script>

<template>
  <div
    class="v-toolbar"
    role="group"
    :aria-label="label"
  >
    <div class="v-toolbar__main">
      <slot />
    </div>
    <div
      v-if="$slots.end"
      class="v-toolbar__end"
    >
      <slot name="end" />
    </div>
  </div>
</template>
