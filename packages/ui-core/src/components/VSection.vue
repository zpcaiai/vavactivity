<script setup lang="ts">
defineProps<{ title: string; description?: string; level?: 2 | 3 }>();
</script>

<template>
  <section class="v-section">
    <header class="v-section__header">
      <div>
        <component
          :is="`h${level ?? 2}`"
          class="v-section__title"
        >
          {{ title }}
        </component>
        <p
          v-if="description"
          class="v-section__description"
        >
          {{ description }}
        </p>
      </div>
      <div
        v-if="$slots.actions"
        class="v-section__actions"
      >
        <slot name="actions" />
      </div>
    </header>
    <slot />
  </section>
</template>
