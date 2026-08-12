<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { VAlert, VAvatar, VCard, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import {
  PREVIEW_CONTEXTS,
  useDatingProfile
} from "@/features/dating-profile/composables/useDatingProfile";

const {
  preview,
  busy,
  error,
  exists,
  steps,
  breadcrumbs,
  localePath,
  t,
  ensureLoaded,
  loadPreview
} = useDatingProfile();

const context = ref<string>("profile_detail");

onMounted(async () => {
  await ensureLoaded();
  if (exists.value) await loadPreview(context.value);
});

watch(context, (value) => {
  if (exists.value) void loadPreview(value);
});
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('ia.groups.matchmaking')"
    :title="t('dating.steps.preview')"
    :description="t('dating.preview.description')"
    :breadcrumbs="breadcrumbs('preview')"
    :sections="steps"
    :sections-label="t('dating.stepsLabel')"
  >
    <VAlert
      v-if="error"
      tone="danger"
      :title="t('common.loadFailed')"
    >
      {{ error }}
    </VAlert>

    <VPageState
      v-if="!exists && !busy"
      state="empty"
      :title="t('dating.emptyTitle')"
      :message="t('dating.emptyMessage')"
    >
      <RouterLink :to="localePath('account/dating-profile')">
        {{ t("dating.goToOverview") }}
      </RouterLink>
    </VPageState>

    <template v-else>
      <label class="preview-context">
        <span>{{ t("dating.preview.context") }}</span>
        <select v-model="context">
          <option
            v-for="item in PREVIEW_CONTEXTS"
            :key="item"
            :value="item"
          >
            {{ t(`dating.preview.contexts.${item}`) }}
          </option>
        </select>
      </label>

      <VCard
        v-if="preview"
        tone="soft"
      >
        <template #title>
          <div class="preview-head">
            <VAvatar
              size="large"
              :name="preview.display_name"
            />
            <div>
              <h2>{{ preview.display_name }}</h2>
              <p>
                {{ preview.age_display ?? t("dating.preview.ageHidden") }} ·
                {{ preview.city_display ?? t("dating.preview.cityHidden") }}
              </p>
            </div>
          </div>
        </template>
        <p>{{ preview.self_introduction ?? t("dating.preview.introHidden") }}</p>
        <template #footer>
          <small>
            {{
              t("dating.preview.fieldSummary", {
                visible: Object.keys(preview.visible_fields).length,
                withheld: preview.withheld_field_count
              })
            }}
            ·
            {{ preview.contact_details_available ? t("dating.preview.contactVisible") : t("dating.preview.contactHidden") }}
          </small>
        </template>
      </VCard>

      <VPageState
        v-else-if="!busy"
        state="empty"
        :title="t('dating.preview.emptyTitle')"
        :message="t('dating.preview.emptyMessage')"
      />
    </template>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-lg); }
p { color: var(--vav-color-text-muted); margin: 0; }
small { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-xs); }
.preview-head { align-items: center; display: flex; gap: var(--vav-space-3); }
.preview-context { display: grid; gap: var(--vav-space-1); max-inline-size: 20rem; }
.preview-context span { font-size: var(--vav-font-size-sm); font-weight: var(--vav-font-weight-semibold); }

.preview-context select {
  background: var(--vav-color-surface-raised);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-component-input-radius);
  color: var(--vav-color-text);
  font: inherit;
  min-block-size: var(--vav-component-input-height);
  padding-inline: var(--vav-component-input-padding-inline);
}
</style>
