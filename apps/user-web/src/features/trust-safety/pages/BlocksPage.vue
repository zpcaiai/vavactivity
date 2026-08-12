<script setup lang="ts">
import { onMounted, ref } from "vue";
import { VAlert, VButton, VCard, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { safetyApi, type SafetyBlock } from "@/features/trust-safety/api";
import { useSafetyShell, useSafetyState } from "@/features/trust-safety/composables/useSafetyShell";

const { sections, breadcrumbs, t } = useSafetyShell("blocks");
const { busy, error, notice, guard } = useSafetyState();

const blocks = ref<SafetyBlock[]>([]);
const newUserId = ref("");

async function load() {
  const value = await guard(() => safetyApi.blocks());
  if (value) blocks.value = value;
}

async function block() {
  if (!newUserId.value.trim()) {
    error.value = t("safety.blocks.userRequired");
    return;
  }
  await guard(
    () => safetyApi.block(newUserId.value.trim(), "user_initiated"),
    t("safety.blocks.blocked")
  );
  newUserId.value = "";
  await load();
}

async function unblock(userId: string) {
  if (!window.confirm(t("safety.blocks.unblockConfirm"))) return;
  await guard(() => safetyApi.unblock(userId), t("safety.blocks.unblocked"));
  await load();
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('safety.eyebrow')"
    :title="t('safety.blocks.title')"
    :description="t('safety.blocks.description')"
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
        <h2>{{ t("safety.blocks.addTitle") }}</h2>
      </template>
      <template #description>
        {{ t("safety.blocks.addDescription") }}
      </template>
      <form
        class="block-form"
        @submit.prevent="block"
      >
        <label>
          <span>{{ t("safety.blocks.userId") }}</span>
          <input
            v-model="newUserId"
            autocomplete="off"
          >
        </label>
        <VButton
          type="submit"
          :loading="busy"
        >
          {{ t("safety.blocks.block") }}
        </VButton>
      </form>
    </VCard>

    <VPageState
      v-if="busy && !blocks.length"
      state="loading"
      :title="t('common.loading')"
      :message="t('common.pleaseWait')"
    />

    <VCard
      v-else-if="blocks.length"
      padding="compact"
    >
      <template #title>
        <h2>{{ t("safety.blocks.listTitle") }}</h2>
      </template>
      <ul class="block-list">
        <li
          v-for="item in blocks"
          :key="item.id"
        >
          <div>
            <strong>{{ item.blocked_user_id }}</strong>
            <small>{{ item.reason_code ?? t("safety.blocks.selfProtection") }} · {{ item.created_at }}</small>
          </div>
          <VButton
            variant="secondary"
            @click="unblock(item.blocked_user_id)"
          >
            {{ t("safety.blocks.unblock") }}
          </VButton>
        </li>
      </ul>
    </VCard>

    <VPageState
      v-else
      state="empty"
      :title="t('safety.blocks.emptyTitle')"
      :message="t('safety.blocks.emptyMessage')"
    />

    <VAlert
      tone="info"
      :title="t('safety.blocks.boundaryTitle')"
    >
      {{ t("safety.blocks.boundary") }}
    </VAlert>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
small { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-xs); }
.block-form { align-items: end; display: grid; gap: var(--vav-space-3); grid-template-columns: minmax(0, 1fr) auto; }
.block-form label { display: grid; gap: var(--vav-space-1); }
.block-form label span { font-size: var(--vav-font-size-sm); font-weight: var(--vav-font-weight-semibold); }

.block-form input {
  background: var(--vav-color-surface-raised);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-component-input-radius);
  color: var(--vav-color-text);
  font: inherit;
  min-block-size: var(--vav-component-input-height);
  padding-inline: var(--vav-component-input-padding-inline);
}

.block-list { display: grid; gap: var(--vav-space-3); list-style: none; margin: 0; padding: 0; }
.block-list li { align-items: center; border-block-end: 1px solid var(--vav-color-border); display: flex; flex-wrap: wrap; gap: var(--vav-space-3); justify-content: space-between; padding-block-end: var(--vav-space-2); }
.block-list li div { display: grid; }

@media (max-width: 48rem) {
  .block-form { grid-template-columns: minmax(0, 1fr); }
}
</style>
