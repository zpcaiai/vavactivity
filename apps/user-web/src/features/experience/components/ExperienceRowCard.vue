<script setup lang="ts">
import { VCard, VStatusBadge } from "@vav/ui-core";

import type { ExperienceRow } from "@/features/experience/api";
import { useExperienceRoutes } from "@/features/experience/composables/useExperienceRoutes";

defineProps<{ row: ExperienceRow; actionLabel: string; tone?: "default" | "danger" | "warning" }>();

const { pathFor, titleOf, descriptionOf } = useExperienceRoutes();

function statusOf(row: ExperienceRow) {
  const state = String(row.state ?? "");
  if (state === "blocked") return "warning" as const;
  if (state === "failed" || state === "overdue") return "danger" as const;
  if (state === "completed" || state === "done") return "success" as const;
  return "info" as const;
}
</script>

<template>
  <VCard
    :tone="tone === 'danger' ? 'danger' : tone === 'warning' ? 'warning' : 'default'"
    padding="compact"
  >
    <template #title>
      <h3>{{ titleOf(row) }}</h3>
    </template>
    <template #actions>
      <VStatusBadge
        :status="statusOf(row)"
        :label="String(row.state ?? row.category ?? row.source_module ?? '')"
      />
    </template>
    <p v-if="descriptionOf(row)">
      {{ descriptionOf(row) }}
    </p>
    <template #footer>
      <RouterLink
        class="experience-row-card__action"
        :to="pathFor(row)"
      >
        {{ actionLabel }}
      </RouterLink>
    </template>
  </VCard>
</template>

<style scoped>
h3 { margin: 0; font-size: var(--vav-font-size-md); }
p { margin: 0; color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); }

.experience-row-card__action {
  display: inline-flex;
  align-items: center;
  min-block-size: var(--vav-component-nav-item-height);
  padding-inline: var(--vav-space-3);
  border-radius: var(--vav-radius-pill);
  background: var(--vav-color-action-primary);
  color: var(--vav-color-on-action);
  text-decoration: none;
  font-size: var(--vav-font-size-sm);
  font-weight: var(--vav-font-weight-semibold);
}
</style>
