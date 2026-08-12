<script setup lang="ts">
import { onMounted, ref } from "vue";
import { VAlert, VButton, VCard, VPageState, VStatusBadge } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { privacyApi } from "@/features/privacy/api";
import {
  usePrivacyShell,
  usePrivacyState,
  type PrivacySettings
} from "@/features/privacy/composables/usePrivacyShell";

const { sections, breadcrumbs, t } = usePrivacyShell("settings");
const { busy, error, notice, guard } = usePrivacyState();

const settings = ref<PrivacySettings>();

/** In strict mode the platform, not the form, decides exposure. */
const exposureToggles = [
  { key: "searchable_by_platform_users", labelKey: "privacy.settings.searchable" },
  { key: "visible_in_activity_directory", labelKey: "privacy.settings.activityDirectory" },
  { key: "visible_in_matchmaking", labelKey: "privacy.settings.matchmaking" },
  { key: "allow_contact_exchange_after_mutual_confirmation", labelKey: "privacy.settings.contactExchange" }
] as const;

const aiToggles = [
  { key: "allow_profile_use_by_ai", labelKey: "privacy.settings.aiProfile" },
  { key: "allow_service_history_use_by_ai", labelKey: "privacy.settings.aiHistory" }
] as const;

async function load() {
  const value = await guard(() => privacyApi<PrivacySettings>("/account/privacy/settings"));
  if (value) settings.value = value;
}

async function save() {
  const current = settings.value;
  if (!current) return;
  const result = await guard(
    () =>
      privacyApi<{ settings_version: number }>("/account/privacy/settings", {
        method: "PUT",
        body: JSON.stringify({ ...current, field_rules: current.field_rules ?? [] })
      }),
    t("privacy.settings.saved")
  );
  if (result) current.settings_version = result.settings_version;
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('ia.groups.account')"
    :title="t('privacy.settings.title')"
    :description="t('privacy.settings.description')"
    :breadcrumbs="breadcrumbs"
    :sections="sections"
    :sections-label="t('privacy.sectionsLabel')"
  >
    <VAlert
      v-if="error"
      tone="danger"
      :title="t('common.loadFailed')"
    >
      {{ error }}
    </VAlert>
    <VAlert
      v-if="notice"
      tone="success"
      :title="t('common.done')"
      live
    >
      {{ notice }}
    </VAlert>

    <VPageState
      v-if="busy && !settings"
      state="loading"
      :title="t('common.loading')"
      :message="t('common.pleaseWait')"
    />

    <form
      v-else-if="settings"
      class="privacy-settings"
      @submit.prevent="save"
    >
      <VCard>
        <template #title>
          <h2>{{ t("privacy.settings.modeTitle") }}</h2>
        </template>
        <template #description>
          {{ t("privacy.settings.modeDescription") }}
        </template>
        <template #actions>
          <VStatusBadge
            :status="settings.privacy_mode === 'strict' ? 'success' : 'info'"
            :label="t(`privacy.settings.mode.${settings.privacy_mode}`)"
          />
        </template>
        <div class="privacy-modes">
          <label
            v-for="mode in (['strict', 'balanced', 'custom'] as const)"
            :key="mode"
            :data-selected="settings.privacy_mode === mode || undefined"
          >
            <input
              v-model="settings.privacy_mode"
              type="radio"
              :value="mode"
            >
            <span>
              <strong>{{ t(`privacy.settings.mode.${mode}`) }}</strong>
              <small>{{ t(`privacy.settings.modeHint.${mode}`) }}</small>
            </span>
          </label>
        </div>
      </VCard>

      <VCard>
        <template #title>
          <h2>{{ t("privacy.settings.exposureTitle") }}</h2>
        </template>
        <template #description>
          {{ t("privacy.settings.exposureDescription") }}
        </template>
        <ul class="privacy-toggles">
          <li
            v-for="toggle in exposureToggles"
            :key="toggle.key"
          >
            <label>
              <input
                v-model="settings[toggle.key]"
                type="checkbox"
                :disabled="settings.privacy_mode === 'strict'"
              >
              <span>{{ t(toggle.labelKey) }}</span>
            </label>
          </li>
        </ul>
        <p v-if="settings.privacy_mode === 'strict'">
          {{ t("privacy.settings.strictLocked") }}
        </p>
      </VCard>

      <VCard>
        <template #title>
          <h2>{{ t("privacy.settings.aiTitle") }}</h2>
        </template>
        <template #description>
          {{ t("privacy.settings.aiDescription") }}
        </template>
        <ul class="privacy-toggles">
          <li
            v-for="toggle in aiToggles"
            :key="toggle.key"
          >
            <label>
              <input
                v-model="settings[toggle.key]"
                type="checkbox"
                :disabled="settings.privacy_mode === 'strict'"
              >
              <span>{{ t(toggle.labelKey) }}</span>
            </label>
          </li>
        </ul>
      </VCard>

      <div class="privacy-settings__actions">
        <VButton
          type="submit"
          :loading="busy"
        >
          {{ t("privacy.settings.save") }}
        </VButton>
        <small>{{ t("privacy.settings.versionHint", { version: settings.settings_version }) }}</small>
      </div>
    </form>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
p { margin: 0; color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); }
.privacy-settings { display: grid; gap: var(--vav-density-section-gap); }
.privacy-settings__actions { align-items: center; display: flex; flex-wrap: wrap; gap: var(--vav-space-3); }
.privacy-settings__actions small { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-xs); }
.privacy-modes { display: grid; gap: var(--vav-space-3); grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr)); }

.privacy-modes label {
  align-items: flex-start;
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-radius-md);
  cursor: pointer;
  display: flex;
  gap: var(--vav-space-2);
  padding: var(--vav-space-3);
}

.privacy-modes label[data-selected] { background: var(--vav-color-interactive-selected); border-color: var(--vav-color-action-primary); }
.privacy-modes span { display: grid; gap: 2px; }
.privacy-modes small { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-xs); }
.privacy-toggles { display: grid; gap: var(--vav-space-2); list-style: none; margin: 0; padding: 0; }
.privacy-toggles label { align-items: center; display: flex; gap: var(--vav-space-2); }
</style>
