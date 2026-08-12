<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { VAlert, VButton, VCard, VFormField, VPageState, VProgress } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { privacyApi, type PrivacyProfile } from "@/features/privacy/api";
import { usePrivacyShell, usePrivacyState } from "@/features/privacy/composables/usePrivacyShell";

const { sections, breadcrumbs, t } = usePrivacyShell("profile");
const { busy, error, notice, guard } = usePrivacyState();

const profile = ref<PrivacyProfile>();
const form = reactive({ display_name: "", city: "", region: "", public_bio: "" });

function apply(value: PrivacyProfile) {
  profile.value = value;
  form.display_name = value.display_name ?? "";
  form.city = value.city ?? "";
  form.region = value.region ?? "";
  form.public_bio = value.public_bio ?? "";
}

async function load() {
  const value = await guard(() => privacyApi<PrivacyProfile>("/account/profile"));
  if (value) apply(value);
}

async function save() {
  if (!profile.value) return;
  const value = await guard(
    () =>
      privacyApi<PrivacyProfile>("/account/profile", {
        method: "PATCH",
        body: JSON.stringify({ ...form, version: profile.value?.version })
      }),
    t("privacy.profile.saved")
  );
  if (value) apply(value);
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('ia.groups.account')"
    :title="t('privacy.profile.title')"
    :description="t('privacy.profile.description')"
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
      v-if="busy && !profile"
      state="loading"
      :title="t('common.loading')"
      :message="t('common.pleaseWait')"
    />

    <template v-else-if="profile">
      <VCard tone="soft">
        <template #title>
          <h2>{{ t("privacy.profile.completenessTitle") }}</h2>
        </template>
        <VProgress
          :value="Math.round(profile.completeness_basis_points / 100)"
          :max="100"
          :label="t('privacy.profile.completeness')"
        />
        <p>{{ t("privacy.profile.version", { version: profile.version }) }}</p>
      </VCard>

      <VCard>
        <template #title>
          <h2>{{ t("privacy.profile.formTitle") }}</h2>
        </template>
        <template #description>
          {{ t("privacy.profile.formDescription") }}
        </template>
        <form
          class="privacy-form"
          @submit.prevent="save"
        >
          <VFormField
            id="privacy-display-name"
            :label="t('privacy.profile.displayName')"
          >
            <input
              id="privacy-display-name"
              v-model="form.display_name"
              maxlength="64"
            >
          </VFormField>
          <VFormField
            id="privacy-city"
            :label="t('privacy.profile.city')"
          >
            <input
              id="privacy-city"
              v-model="form.city"
              maxlength="64"
            >
          </VFormField>
          <VFormField
            id="privacy-region"
            :label="t('privacy.profile.region')"
          >
            <input
              id="privacy-region"
              v-model="form.region"
              maxlength="64"
            >
          </VFormField>
          <VFormField
            id="privacy-bio"
            :label="t('privacy.profile.bio')"
            class="privacy-form__wide"
          >
            <textarea
              id="privacy-bio"
              v-model="form.public_bio"
              maxlength="600"
            />
          </VFormField>
          <div class="privacy-form__actions">
            <VButton
              type="submit"
              :loading="busy"
            >
              {{ t("privacy.profile.save") }}
            </VButton>
          </div>
        </form>
      </VCard>

      <VCard tone="info">
        <template #title>
          <h2>{{ t("privacy.profile.contactTitle") }}</h2>
        </template>
        <p>{{ t("privacy.profile.contactBoundary") }}</p>
      </VCard>
    </template>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
p { margin: 0; color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); }
.privacy-form { display: grid; gap: var(--vav-space-4); grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr)); }
.privacy-form__wide, .privacy-form__actions { grid-column: 1 / -1; }

.privacy-form :where(input, textarea) {
  background: var(--vav-color-surface-raised);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-component-input-radius);
  color: var(--vav-color-text);
  font: inherit;
  min-block-size: var(--vav-component-input-height);
  padding: var(--vav-space-2) var(--vav-component-input-padding-inline);
  inline-size: 100%;
}

.privacy-form textarea { min-block-size: 7rem; }
</style>
