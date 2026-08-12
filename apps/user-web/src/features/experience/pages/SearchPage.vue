<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { VAlert, VButton, VCard, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { experienceApi, type ExperienceRow } from "@/features/experience/api";
import { useExperienceRoutes } from "@/features/experience/composables/useExperienceRoutes";
import { useAuthStore } from "@/stores/auth";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const { pathFor, titleOf, descriptionOf } = useExperienceRoutes();

const query = ref(String(route.query.q ?? ""));
const rows = ref<ExperienceRow[]>([]);
const busy = ref(false);
const searched = ref(false);
const error = ref("");

async function submit() {
  const value = query.value.trim();
  await router.replace({ query: value ? { q: value } : {} });
  if (!value) {
    rows.value = [];
    searched.value = false;
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    rows.value = await experienceApi.search(value, Boolean(auth.user));
    searched.value = true;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("search.error");
  } finally {
    busy.value = false;
  }
}

onMounted(() => {
  if (query.value.trim()) void submit();
});
</script>

<template>
  <UserPageLayout
    width="standard"
    :title="t('search.title')"
    :description="t('search.description')"
  >
    <form
      class="search-form"
      role="search"
      @submit.prevent="submit"
    >
      <label for="experience-query">{{ t("search.label") }}</label>
      <div class="search-form__row">
        <input
          id="experience-query"
          v-model="query"
          maxlength="200"
          autocomplete="off"
          :placeholder="t('search.placeholder')"
        >
        <VButton
          type="submit"
          :loading="busy"
        >
          {{ t("search.submit") }}
        </VButton>
      </div>
      <p class="search-form__hint">
        {{ t("search.permissionNote") }}
      </p>
    </form>

    <VAlert
      v-if="error"
      tone="danger"
      :title="t('common.loadFailed')"
    >
      {{ error }}
    </VAlert>

    <div
      v-if="rows.length"
      class="search-results"
      aria-live="polite"
    >
      <VCard
        v-for="row in rows"
        :key="String(row.id ?? row.route_code ?? titleOf(row))"
        padding="compact"
      >
        <template #title>
          <h2>{{ titleOf(row) }}</h2>
        </template>
        <p v-if="descriptionOf(row)">
          {{ descriptionOf(row) }}
        </p>
        <template #footer>
          <RouterLink :to="pathFor(row)">
            {{ t("search.open") }}
          </RouterLink>
        </template>
      </VCard>
    </div>

    <VPageState
      v-else-if="searched && !busy"
      state="filtered-empty"
      :title="t('search.emptyTitle')"
      :message="t('search.emptyMessage')"
    />
  </UserPageLayout>
</template>

<style scoped>
.search-form { display: grid; gap: var(--vav-space-2); }
.search-form__row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: var(--vav-space-2); }
.search-form__hint { margin: 0; color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); }

.search-form input {
  min-block-size: var(--vav-component-input-height);
  padding-inline: var(--vav-component-input-padding-inline);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-component-input-radius);
  background: var(--vav-color-surface-raised);
  color: var(--vav-color-text);
  font: inherit;
}

.search-results { display: grid; gap: var(--vav-space-3); }
.search-results h2 { margin: 0; font-size: var(--vav-font-size-md); }
.search-results p { margin: 0; color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); }

@media (max-width: 48rem) {
  .search-form__row { grid-template-columns: minmax(0, 1fr); }
}
</style>
