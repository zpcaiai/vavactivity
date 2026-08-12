<script setup lang="ts">
import { onMounted, ref } from "vue";
import { VAlert, VButton, VCard, VPageState, VStatusBadge } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { safetyApi } from "@/features/trust-safety/api";
import { useSafetyShell, useSafetyState } from "@/features/trust-safety/composables/useSafetyShell";

const { sections, breadcrumbs, t } = useSafetyShell("appeals");
const { busy, error, notice, guard } = useSafetyState();

const appeals = ref<Array<Record<string, unknown>>>([]);
const restrictionId = ref("");
const reason = ref("");

async function load() {
  const value = await guard(() => safetyApi.appeals());
  if (value) appeals.value = value;
}

async function submit() {
  if (reason.value.trim().length < 10) {
    error.value = t("safety.appeals.reasonTooShort");
    return;
  }
  await guard(
    () => safetyApi.appeal(restrictionId.value.trim(), reason.value.trim()),
    t("safety.appeals.submitted")
  );
  reason.value = "";
  await load();
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('safety.eyebrow')"
    :title="t('safety.appeals.title')"
    :description="t('safety.appeals.description')"
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
    <VAlert
      v-if="notice"
      tone="success"
      :title="t('common.done')"
      live
    >
      {{ notice }}
    </VAlert>

    <VCard>
      <template #title>
        <h2>{{ t("safety.appeals.formTitle") }}</h2>
      </template>
      <template #description>
        {{ t("safety.appeals.formDescription") }}
      </template>
      <form
        class="appeal-form"
        @submit.prevent="submit"
      >
        <label>
          <span>{{ t("safety.appeals.restrictionId") }}</span>
          <input
            v-model="restrictionId"
            autocomplete="off"
            required
          >
        </label>
        <label>
          <span>{{ t("safety.appeals.reason") }}</span>
          <textarea
            v-model="reason"
            maxlength="5000"
            minlength="10"
            required
          />
        </label>
        <VButton
          type="submit"
          :loading="busy"
        >
          {{ t("safety.appeals.submit") }}
        </VButton>
      </form>
    </VCard>

    <VPageState
      v-if="busy && !appeals.length"
      state="loading"
      :title="t('common.loading')"
      :message="t('common.pleaseWait')"
    />

    <VCard
      v-else-if="appeals.length"
      padding="compact"
    >
      <template #title>
        <h2>{{ t("safety.appeals.listTitle") }}</h2>
      </template>
      <ul class="appeal-list">
        <li
          v-for="item in appeals"
          :key="String(item.id)"
        >
          <div>
            <strong>{{ item.appeal_number }}</strong>
            <small>{{ item.outcome ?? t("safety.appeals.pending") }}</small>
          </div>
          <VStatusBadge
            :status="String(item.status) === 'resolved' ? 'success' : 'info'"
            :label="String(item.status ?? '')"
          />
        </li>
      </ul>
    </VCard>

    <VPageState
      v-else
      state="empty"
      :title="t('safety.appeals.emptyTitle')"
      :message="t('safety.appeals.emptyMessage')"
    />
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
small { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-xs); }
.appeal-form { display: grid; gap: var(--vav-space-3); }
.appeal-form label { display: grid; gap: var(--vav-space-1); }
.appeal-form label span { font-size: var(--vav-font-size-sm); font-weight: var(--vav-font-weight-semibold); }

.appeal-form :where(input, textarea) {
  background: var(--vav-color-surface-raised);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-component-input-radius);
  color: var(--vav-color-text);
  font: inherit;
  min-block-size: var(--vav-component-input-height);
  padding: var(--vav-space-2) var(--vav-component-input-padding-inline);
}

.appeal-form textarea { min-block-size: 7rem; }
.appeal-list { display: grid; gap: var(--vav-space-3); list-style: none; margin: 0; padding: 0; }
.appeal-list li { align-items: center; border-block-end: 1px solid var(--vav-color-border); display: flex; gap: var(--vav-space-3); justify-content: space-between; padding-block-end: var(--vav-space-2); }
.appeal-list li div { display: grid; }
</style>
