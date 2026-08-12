<script setup lang="ts">
import { onMounted, ref } from "vue";
import { VAlert, VButton, VCard, VPageState, VStatusBadge } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { privacyApi, type PrivacyRequest } from "@/features/privacy/api";
import { usePrivacyShell, usePrivacyState } from "@/features/privacy/composables/usePrivacyShell";

const { sections, breadcrumbs, t } = usePrivacyShell("requests");
const { busy, error, notice, guard } = usePrivacyState();

const requests = ref<PrivacyRequest[]>([]);
const password = ref("");
const correctionField = ref("display_name");
const correctionValue = ref("");
const correctionReason = ref("");

async function load() {
  const value = await guard(() => privacyApi<{ items: PrivacyRequest[] }>("/account/privacy/requests"));
  if (value) requests.value = value.items;
}

async function inventory() {
  await guard(
    () => privacyApi("/account/privacy/data-inventory", { method: "POST" }),
    t("privacy.requests.inventoryDone")
  );
  await load();
}

async function exportData() {
  if (!password.value) {
    error.value = t("privacy.requests.passwordRequired");
    return;
  }
  await guard(
    () =>
      privacyApi("/account/privacy/exports", {
        method: "POST",
        body: JSON.stringify({ password: password.value, requested_format: "json", modules: [] })
      }),
    t("privacy.requests.exportDone")
  );
  password.value = "";
  await load();
}

async function correct() {
  if (!correctionValue.value.trim() || !correctionReason.value.trim()) {
    error.value = t("privacy.requests.correctionRequired");
    return;
  }
  await guard(
    () =>
      privacyApi("/account/privacy/corrections", {
        method: "POST",
        body: JSON.stringify({
          items: [
            {
              module_code: "identity",
              entity_reference_type: "profile",
              field_path: correctionField.value,
              requested_value: correctionValue.value,
              reason: correctionReason.value
            }
          ]
        })
      }),
    t("privacy.requests.correctionDone")
  );
  correctionValue.value = "";
  correctionReason.value = "";
  await load();
}

async function erase() {
  if (!password.value) {
    error.value = t("privacy.requests.passwordRequired");
    return;
  }
  if (!window.confirm(t("privacy.requests.erasureConfirm"))) return;
  await guard(
    () =>
      privacyApi("/account/privacy/erasures", {
        method: "POST",
        body: JSON.stringify({
          password: password.value,
          requested_scope: ["all"],
          confirmation: "REQUEST_ACCOUNT_ERASURE"
        })
      }),
    t("privacy.requests.erasureDone")
  );
  password.value = "";
  await load();
}

function statusTone(status: string) {
  if (status === "completed") return "success" as const;
  if (status === "failed" || status === "rejected") return "danger" as const;
  return "info" as const;
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="wide"
    :eyebrow="t('ia.groups.account')"
    :title="t('privacy.requests.title')"
    :description="t('privacy.requests.description')"
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

    <div class="request-grid">
      <VCard>
        <template #title>
          <h2>{{ t("privacy.requests.inventoryTitle") }}</h2>
        </template>
        <template #description>
          {{ t("privacy.requests.inventoryDescription") }}
        </template>
        <template #footer>
          <VButton
            variant="secondary"
            :loading="busy"
            @click="inventory"
          >
            {{ t("privacy.requests.inventoryAction") }}
          </VButton>
        </template>
      </VCard>

      <VCard>
        <template #title>
          <h2>{{ t("privacy.requests.exportTitle") }}</h2>
        </template>
        <template #description>
          {{ t("privacy.requests.exportDescription") }}
        </template>
        <label class="request-field">
          <span>{{ t("privacy.requests.password") }}</span>
          <input
            v-model="password"
            type="password"
            autocomplete="current-password"
          >
        </label>
        <template #footer>
          <VButton
            :loading="busy"
            @click="exportData"
          >
            {{ t("privacy.requests.exportAction") }}
          </VButton>
        </template>
      </VCard>

      <VCard>
        <template #title>
          <h2>{{ t("privacy.requests.correctionTitle") }}</h2>
        </template>
        <template #description>
          {{ t("privacy.requests.correctionDescription") }}
        </template>
        <label class="request-field">
          <span>{{ t("privacy.requests.correctionField") }}</span>
          <select v-model="correctionField">
            <option value="display_name">
              {{ t("privacy.profile.displayName") }}
            </option>
            <option value="city">
              {{ t("privacy.profile.city") }}
            </option>
            <option value="region">
              {{ t("privacy.profile.region") }}
            </option>
          </select>
        </label>
        <label class="request-field">
          <span>{{ t("privacy.requests.correctionValue") }}</span>
          <input
            v-model="correctionValue"
            maxlength="128"
          >
        </label>
        <label class="request-field">
          <span>{{ t("privacy.requests.correctionReason") }}</span>
          <input
            v-model="correctionReason"
            maxlength="256"
          >
        </label>
        <template #footer>
          <VButton
            variant="secondary"
            :loading="busy"
            @click="correct"
          >
            {{ t("privacy.requests.correctionAction") }}
          </VButton>
        </template>
      </VCard>

      <VCard tone="danger">
        <template #title>
          <h2>{{ t("privacy.requests.erasureTitle") }}</h2>
        </template>
        <template #description>
          {{ t("privacy.requests.erasureDescription") }}
        </template>
        <p>{{ t("privacy.requests.erasureBoundary") }}</p>
        <template #footer>
          <VButton
            variant="danger"
            :loading="busy"
            @click="erase"
          >
            {{ t("privacy.requests.erasureAction") }}
          </VButton>
        </template>
      </VCard>
    </div>

    <VCard padding="compact">
      <template #title>
        <h2>{{ t("privacy.requests.historyTitle") }}</h2>
      </template>
      <div
        v-if="requests.length"
        class="request-table"
      >
        <table>
          <caption class="sr-only">
            {{ t("privacy.requests.historyTitle") }}
          </caption>
          <thead>
            <tr>
              <th scope="col">
                {{ t("privacy.requests.number") }}
              </th>
              <th scope="col">
                {{ t("privacy.requests.type") }}
              </th>
              <th scope="col">
                {{ t("privacy.requests.status") }}
              </th>
              <th scope="col">
                {{ t("privacy.requests.submitted") }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in requests"
              :key="item.id"
            >
              <td>{{ item.request_number }}</td>
              <td>{{ item.request_type }}</td>
              <td>
                <VStatusBadge
                  :status="statusTone(item.status)"
                  :label="item.status"
                />
              </td>
              <td>{{ item.submitted_at }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <VPageState
        v-else
        state="empty"
        :title="t('privacy.requests.emptyTitle')"
        :message="t('privacy.requests.emptyMessage')"
      />
    </VCard>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
p { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); margin: 0; }
.request-grid { display: grid; gap: var(--vav-space-4); grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); }
.request-field { display: grid; gap: var(--vav-space-1); }
.request-field span { font-size: var(--vav-font-size-sm); font-weight: var(--vav-font-weight-semibold); }

.request-field :where(input, select) {
  background: var(--vav-color-surface-raised);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-component-input-radius);
  color: var(--vav-color-text);
  font: inherit;
  min-block-size: var(--vav-component-input-height);
  padding-inline: var(--vav-component-input-padding-inline);
}

.request-table { overflow-x: auto; }
table { border-collapse: collapse; inline-size: 100%; }
th, td { border-block-end: 1px solid var(--vav-color-border); padding: var(--vav-space-3); text-align: start; }
th { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); }
.sr-only { clip-path: inset(50%); block-size: 1px; inline-size: 1px; overflow: hidden; position: absolute; }
</style>
