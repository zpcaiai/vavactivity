<script setup lang="ts">
import { onMounted, ref } from "vue";
import { VAlert, VButton, VCard, VPageState, VStatusBadge } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { privacyApi, type MemoryItem } from "@/features/privacy/api";
import {
  usePrivacyShell,
  usePrivacyState,
  type MemoryPreferences
} from "@/features/privacy/composables/usePrivacyShell";

const { sections, breadcrumbs, t } = usePrivacyShell("memory");
const { busy, error, notice, guard } = usePrivacyState();

const preferences = ref<MemoryPreferences>();
const items = ref<MemoryItem[]>([]);

const toggles = [
  { key: "allow_profile_facts", labelKey: "privacy.memory.profileFacts" },
  { key: "allow_service_history", labelKey: "privacy.memory.serviceHistory" },
  { key: "allow_relationship_context", labelKey: "privacy.memory.relationshipContext" },
  { key: "allow_cross_conversation_use", labelKey: "privacy.memory.crossConversation" }
] as const;

async function load() {
  const [preferenceValue, itemValue] = await Promise.all([
    guard(() => privacyApi<MemoryPreferences>("/account/ai-memory/preferences")),
    guard(() => privacyApi<{ items: MemoryItem[] }>("/account/ai-memory/items"))
  ]);
  if (preferenceValue) preferences.value = preferenceValue;
  if (itemValue) items.value = itemValue.items;
}

async function savePreferences() {
  const current = preferences.value;
  if (!current) return;
  const result = await guard(
    () =>
      privacyApi<{ settings_version: number }>("/account/ai-memory/preferences", {
        method: "PUT",
        body: JSON.stringify({ ...current, delete_existing_when_disabled: false })
      }),
    t("privacy.memory.saved")
  );
  if (result) current.settings_version = result.settings_version;
}

async function act(item: MemoryItem, action: "approve" | "reject" | "delete") {
  await guard(() =>
    privacyApi(`/account/ai-memory/items/${item.id}${action === "delete" ? "" : `/${action}`}`, {
      method: action === "delete" ? "DELETE" : "POST"
    })
  );
  await load();
}

async function clearAll() {
  if (!window.confirm(t("privacy.memory.clearConfirm"))) return;
  await guard(
    () => privacyApi("/account/ai-memory/clear-all", { method: "POST" }),
    t("privacy.memory.cleared")
  );
  await load();
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('ia.groups.account')"
    :title="t('privacy.memory.title')"
    :description="t('privacy.memory.description')"
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
      v-if="busy && !preferences"
      state="loading"
      :title="t('common.loading')"
      :message="t('common.pleaseWait')"
    />

    <template v-else-if="preferences">
      <VCard :tone="preferences.long_term_memory_enabled ? 'default' : 'soft'">
        <template #title>
          <h2>{{ t("privacy.memory.switchTitle") }}</h2>
        </template>
        <template #description>
          {{ t("privacy.memory.switchDescription") }}
        </template>
        <template #actions>
          <VStatusBadge
            :status="preferences.long_term_memory_enabled ? 'info' : 'success'"
            :label="preferences.long_term_memory_enabled ? t('privacy.memory.on') : t('privacy.memory.off')"
          />
        </template>
        <label class="memory-toggle">
          <input
            v-model="preferences.long_term_memory_enabled"
            type="checkbox"
          >
          <span>{{ t("privacy.memory.enable") }}</span>
        </label>

        <ul class="memory-toggles">
          <li
            v-for="toggle in toggles"
            :key="toggle.key"
          >
            <label>
              <input
                v-model="preferences[toggle.key]"
                type="checkbox"
                :disabled="!preferences.long_term_memory_enabled"
              >
              <span>{{ t(toggle.labelKey) }}</span>
            </label>
          </li>
        </ul>

        <template #footer>
          <VButton
            :loading="busy"
            @click="savePreferences"
          >
            {{ t("privacy.memory.save") }}
          </VButton>
          <VButton
            variant="danger"
            @click="clearAll"
          >
            {{ t("privacy.memory.clear") }}
          </VButton>
        </template>
      </VCard>

      <VCard padding="compact">
        <template #title>
          <h2>{{ t("privacy.memory.itemsTitle") }}</h2>
        </template>
        <template #description>
          {{ t("privacy.memory.itemsDescription") }}
        </template>
        <ul
          v-if="items.length"
          class="memory-items"
        >
          <li
            v-for="item in items"
            :key="item.id"
          >
            <div>
              <strong>{{ item.memory_type }}</strong>
              <p>{{ item.content }}</p>
              <small>{{ item.certainty }} · {{ item.status }}</small>
            </div>
            <div class="memory-items__actions">
              <VButton
                v-if="item.status === 'user_approval_required'"
                @click="act(item, 'approve')"
              >
                {{ t("privacy.memory.approve") }}
              </VButton>
              <VButton
                v-if="item.status === 'user_approval_required'"
                variant="secondary"
                @click="act(item, 'reject')"
              >
                {{ t("privacy.memory.reject") }}
              </VButton>
              <VButton
                variant="danger"
                @click="act(item, 'delete')"
              >
                {{ t("privacy.memory.delete") }}
              </VButton>
            </div>
          </li>
        </ul>
        <VPageState
          v-else
          state="empty"
          :title="t('privacy.memory.emptyTitle')"
          :message="t('privacy.memory.emptyMessage')"
        />
      </VCard>
    </template>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
p { margin: 0; }
small { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-xs); }
.memory-toggle, .memory-toggles label { align-items: center; display: flex; gap: var(--vav-space-2); }
.memory-toggles { display: grid; gap: var(--vav-space-2); list-style: none; margin: 0; padding-inline-start: var(--vav-space-6); }
.memory-items { display: grid; gap: var(--vav-space-3); list-style: none; margin: 0; padding: 0; }

.memory-items li {
  align-items: flex-start;
  border-block-start: 1px solid var(--vav-color-border);
  display: flex;
  flex-wrap: wrap;
  gap: var(--vav-space-3);
  justify-content: space-between;
  padding-block-start: var(--vav-space-3);
}

.memory-items__actions { display: flex; flex-wrap: wrap; gap: var(--vav-space-2); }
</style>
