<script setup lang="ts">
import { VBreadcrumbs, VTabs } from "@vav/ui-core";
import type { VBreadcrumbItem, VTabItem } from "@vav/ui-core";

withDefaults(
  defineProps<{
    title: string;
    description?: string;
    width?: "reading" | "standard" | "wide";
    eyebrow?: string;
    breadcrumbs?: VBreadcrumbItem[];
    sections?: VTabItem[];
    sectionsLabel?: string;
  }>(),
  { width: "standard", sectionsLabel: "分区导航" }
);
</script>

<template>
  <section
    class="v-user-page"
    :data-width="width"
  >
    <VBreadcrumbs
      v-if="breadcrumbs && breadcrumbs.length"
      :items="breadcrumbs"
    />

    <header class="v-user-page__header">
      <div class="v-user-page__titles">
        <p
          v-if="eyebrow"
          class="v-user-page__eyebrow"
        >
          {{ eyebrow }}
        </p>
        <h1 tabindex="-1">
          {{ title }}
        </h1>
        <p
          v-if="description"
          class="v-user-page__description"
        >
          {{ description }}
        </p>
      </div>
      <div
        v-if="$slots.actions"
        class="v-user-page__actions"
      >
        <slot name="actions" />
      </div>
    </header>

    <VTabs
      v-if="sections && sections.length"
      :items="sections"
      :label="sectionsLabel"
    />

    <div class="v-user-page__content">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.v-user-page {
  inline-size: min(100%, var(--vav-layout-content-standard));
  margin-inline: auto;
  display: grid;
  gap: var(--vav-density-page-gap);
  align-content: start;
}

.v-user-page[data-width="reading"] { max-inline-size: var(--vav-layout-content-reading); }
.v-user-page[data-width="wide"] { inline-size: min(100%, var(--vav-layout-content-wide)); }

.v-user-page__header {
  display: flex;
  flex-wrap: wrap;
  gap: var(--vav-space-4);
  align-items: flex-end;
  justify-content: space-between;
}

.v-user-page__titles { display: grid; gap: var(--vav-space-2); }
.v-user-page__titles h1 { margin: 0; font-size: var(--vav-font-size-xl); line-height: var(--vav-line-height-tight); }
.v-user-page__titles h1:focus-visible { outline: 3px solid var(--vav-color-focus); outline-offset: 4px; }

.v-user-page__eyebrow {
  margin: 0;
  color: var(--vav-color-action-primary);
  font-size: var(--vav-font-size-xs);
  font-weight: var(--vav-font-weight-bold);
  letter-spacing: var(--vav-letter-spacing-wide);
  text-transform: uppercase;
}

.v-user-page__description { margin: 0; color: var(--vav-color-text-muted); max-inline-size: 68ch; }
.v-user-page__actions { display: flex; flex-wrap: wrap; gap: var(--vav-space-2); }
.v-user-page__content { display: grid; gap: var(--vav-density-section-gap); align-content: start; }

@media (max-width: 48rem) {
  .v-user-page__header { align-items: flex-start; }
  .v-user-page__actions { inline-size: 100%; }
}
</style>
