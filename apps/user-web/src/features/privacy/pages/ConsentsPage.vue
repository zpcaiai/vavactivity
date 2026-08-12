<script setup lang="ts">
import { onMounted, ref } from "vue";
import { VAlert, VButton, VCard, VPageState, VStatusBadge } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { privacyApi, type Consent } from "@/features/privacy/api";
import { usePrivacyShell, usePrivacyState } from "@/features/privacy/composables/usePrivacyShell";

const { sections, breadcrumbs, t } = usePrivacyShell("consents");
const { busy, error, notice, guard } = usePrivacyState();

const consents = ref<Consent[]>([]);

async function load() {
  const value = await guard(() => privacyApi<{ items: Consent[] }>("/account/consents"));
  if (value) consents.value = value.items;
}

async function change(item: Consent) {
  const grant = item.status !== "granted";
  await guard(
    () =>
      privacyApi(`/account/consents/${item.consent_code}/${grant ? "grant" : "withdraw"}`, {
        method: "POST",
        body: grant
          ? JSON.stringify({ release_id: item.release_id, evidence: { source: "user_privacy_web" } })
          : undefined
      }),
    grant ? t("privacy.consents.granted") : t("privacy.consents.withdrawn")
  );
  await load();
}
onMounted(load);
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('ia.groups.account')"
    :title="t('privacy.consents.title')"
    :description="t('privacy.consents.description')"
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
      v-if="busy && !consents.length"
      state="loading"
      :title="t('common.loading')"
      :message="t('common.pleaseWait')"
    />

    <div
      v-else-if="consents.length"
      class="consent-list"
    >
      <VCard
        v-for="item in consents"
        :key="item.consent_code"
        padding="compact"
      >
        <template #title>
          <h2>{{ item.title }}</h2>
        </template>
        <template #actions>
          <VStatusBadge
            :status="item.status === 'granted' ? 'success' : 'info'"
            :label="t(`privacy.consents.status.${item.status === 'granted' ? 'granted' : 'notGranted'}`)"
          />
        </template>
        <p>{{ item.summary }}</p>
        <small>
          {{ t("privacy.consents.release", { version: item.semantic_version }) }}
          <template v-if="item.required_for_service"> · {{ t("privacy.consents.required") }}</template>
        </small>
        <template #footer>
          <VButton
            v-if="item.withdrawable || item.status !== 'granted'"
            :variant="item.status === 'granted' ? 'secondary' : 'primary'"
            @click="change(item)"
          >
            {{ item.status === "granted" ? t("privacy.consents.withdraw") : t("privacy.consents.grant") }}
          </VButton>
          <small v-else>{{ t("privacy.consents.notWithdrawable") }}</small>
        </template>
      </VCard>
    </div>

    <VPageState
      v-else
      state="empty"
      :title="t('privacy.consents.emptyTitle')"
      :message="t('privacy.consents.emptyMessage')"
    />

    <VAlert
      tone="info"
      :title="t('privacy.consents.boundaryTitle')"
    >
      {{ t("privacy.consents.boundary") }}
    </VAlert>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
p { margin: 0; }
small { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-xs); }
.consent-list { display: grid; gap: var(--vav-space-3); }
</style>
