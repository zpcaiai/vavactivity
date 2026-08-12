<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { VAlert, VCard, VDescriptionList, VPageState, VStatusBadge } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { safetyApi } from "@/features/trust-safety/api";
import { useSafetyShell, useSafetyState } from "@/features/trust-safety/composables/useSafetyShell";

const { sections, breadcrumbs, localePath, t } = useSafetyShell("restrictions");
const { busy, error, guard } = useSafetyState();

const restrictions = ref<Record<string, unknown>>({});

/**
 * The endpoint returns a free-form document. Rather than dumping raw JSON at
 * the member — which the previous page did — surface the scalar fields as a
 * description list and keep the rest behind a details disclosure.
 */
const facts = computed(() =>
  Object.entries(restrictions.value)
    .filter(([, value]) => ["string", "number", "boolean"].includes(typeof value))
    .map(([term, value]) => ({ term, value: String(value) }))
);

const complex = computed(() =>
  Object.fromEntries(
    Object.entries(restrictions.value).filter(
      ([, value]) => !["string", "number", "boolean"].includes(typeof value)
    )
  )
);

const active = computed(() => facts.value.length > 0 || Object.keys(complex.value).length > 0);

async function load() {
  const value = await guard(() => safetyApi.restrictions());
  if (value) restrictions.value = value;
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('safety.eyebrow')"
    :title="t('safety.restrictions.title')"
    :description="t('safety.restrictions.description')"
    :breadcrumbs="breadcrumbs"
    :sections="sections"
    :sections-label="t('safety.sectionsLabel')"
  >
    <VAlert
      v-if="error"
      tone="danger"
      :title="t('common.loadFailed')"
    >
      {{ error }}
    </VAlert>

    <VPageState
      v-if="busy"
      state="loading"
      :title="t('common.loading')"
      :message="t('common.pleaseWait')"
    />

    <VCard v-else-if="active">
      <template #title>
        <h2>{{ t("safety.restrictions.currentTitle") }}</h2>
      </template>
      <template #actions>
        <VStatusBadge
          status="warning"
          :label="t('safety.restrictions.active')"
        />
      </template>
      <VDescriptionList
        v-if="facts.length"
        :items="facts"
      />
      <details v-if="Object.keys(complex).length">
        <summary>{{ t("safety.restrictions.details") }}</summary>
        <pre>{{ JSON.stringify(complex, null, 2) }}</pre>
      </details>
      <template #footer>
        <RouterLink :to="localePath('account/safety/appeals')">
          {{ t("safety.restrictions.appeal") }}
        </RouterLink>
      </template>
    </VCard>

    <VPageState
      v-else
      state="empty"
      :title="t('safety.restrictions.emptyTitle')"
      :message="t('safety.restrictions.emptyMessage')"
    />
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
summary { cursor: pointer; font-size: var(--vav-font-size-sm); font-weight: var(--vav-font-weight-semibold); }
pre { background: var(--vav-color-surface-soft); border-radius: var(--vav-radius-sm); max-block-size: 18rem; overflow: auto; padding: var(--vav-space-3); }
</style>
