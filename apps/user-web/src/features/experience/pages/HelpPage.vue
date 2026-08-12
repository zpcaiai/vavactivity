<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { VAlert, VCard, VPageState, VSection } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { experienceApi, type ExperienceRow } from "@/features/experience/api";
import { useExperienceRoutes } from "@/features/experience/composables/useExperienceRoutes";
import { useAppNavigation } from "@/composables/useAppNavigation";
import { useAuthStore } from "@/stores/auth";

const { t } = useI18n();
const auth = useAuthStore();
const { locale, localePath } = useAppNavigation();
const { titleOf, descriptionOf } = useExperienceRoutes();

const busy = ref(true);
const error = ref("");
const rows = ref<ExperienceRow[]>([]);

async function load() {
  busy.value = true;
  error.value = "";
  try {
    rows.value = await experienceApi.help(undefined, locale.value, Boolean(auth.user));
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("help.loadError");
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="standard"
    :title="t('help.title')"
    :description="t('help.description')"
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
      :title="t('help.loadingTitle')"
      :message="t('common.pleaseWait')"
    />

    <VSection
      v-else-if="rows.length"
      :title="t('help.articlesTitle')"
      :description="t('help.articlesDescription')"
    >
      <div class="help-grid">
        <VCard
          v-for="row in rows"
          :key="String(row.id ?? row.document_code ?? titleOf(row))"
          padding="compact"
        >
          <template #title>
            <h3>{{ titleOf(row) }}</h3>
          </template>
          <p v-if="descriptionOf(row)">
            {{ descriptionOf(row) }}
          </p>
        </VCard>
      </div>
    </VSection>

    <VPageState
      v-else
      state="empty"
      :title="t('help.emptyTitle')"
      :message="t('help.emptyMessage')"
    />

    <VCard tone="soft">
      <template #title>
        <h2>{{ t("help.stillStuckTitle") }}</h2>
      </template>
      <template #description>
        {{ t("help.stillStuckDescription") }}
      </template>
      <template #footer>
        <RouterLink :to="localePath('contact')">
          {{ t("help.contactSupport") }}
        </RouterLink>
        <RouterLink :to="localePath('safety-support')">
          {{ t("help.safetySupport") }}
        </RouterLink>
      </template>
    </VCard>
  </UserPageLayout>
</template>

<style scoped>
.help-grid { display: grid; gap: var(--vav-space-4); grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); }
.help-grid h3, h2 { margin: 0; font-size: var(--vav-font-size-md); }
.help-grid p { margin: 0; color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); }
</style>
