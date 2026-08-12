<script setup lang="ts">
withDefaults(
  defineProps<{
    tone?: "default" | "soft" | "brand" | "success" | "warning" | "danger" | "info";
    padding?: "default" | "compact" | "none";
    interactive?: boolean;
    as?: string;
  }>(),
  { tone: "default", padding: "default", interactive: false, as: "article" }
);
</script>

<template>
  <component
    :is="as"
    class="v-card"
    :data-tone="tone"
    :data-padding="padding"
    :data-interactive="interactive || undefined"
  >
    <header
      v-if="$slots.title || $slots.actions"
      class="v-card__header"
    >
      <div class="v-card__titles">
        <slot name="title" />
        <p
          v-if="$slots.description"
          class="v-card__description"
        >
          <slot name="description" />
        </p>
      </div>
      <div
        v-if="$slots.actions"
        class="v-card__actions"
      >
        <slot name="actions" />
      </div>
    </header>
    <div class="v-card__body">
      <slot />
    </div>
    <footer
      v-if="$slots.footer"
      class="v-card__footer"
    >
      <slot name="footer" />
    </footer>
  </component>
</template>
