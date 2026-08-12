<script setup lang="ts">
import { onMounted, ref } from "vue";
import { VAlert, VCard, VPageState, VStatusBadge } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { membershipApi } from "@/features/memberships/api";
import {
  useMembershipShell,
  useMembershipState
} from "@/features/memberships/composables/useMembershipShell";

const { sections, breadcrumbs, t } = useMembershipShell("history");
const { busy, error, guard } = useMembershipState();

const history = ref<Array<Record<string, unknown>>>([]);

async function load() {
  const value = await guard(() => membershipApi.history());
  if (value) history.value = value;
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('membership.eyebrow')"
    :title="t('membership.historyTitle')"
    :description="t('membership.historyDescription')"
    :breadcrumbs="breadcrumbs"
    :sections="sections"
    :sections-label="t('membership.sectionsLabel')"
  >
    <VAlert
      v-if="error"
      tone="danger"
      :title="t('common.loadFailed')"
    >
      {{ error }}
    </VAlert>

    <VPageState
      v-if="busy && !history.length"
      state="loading"
      :title="t('common.loading')"
      :message="t('common.pleaseWait')"
    />

    <ol
      v-else-if="history.length"
      class="history-list"
    >
      <li
        v-for="item in history"
        :key="String(item.id)"
      >
        <VCard padding="compact">
          <template #title>
            <h2>{{ item.plan_code }}</h2>
          </template>
          <template #actions>
            <VStatusBadge
              :status="String(item.status) === 'active' ? 'success' : 'info'"
              :label="String(item.status ?? '')"
            />
          </template>
          <p>{{ item.source_type }} · {{ item.starts_at ?? "" }}</p>
        </VCard>
      </li>
    </ol>

    <VPageState
      v-else
      state="empty"
      :title="t('membership.historyEmptyTitle')"
      :message="t('membership.historyEmptyMessage')"
    />

    <VAlert
      tone="info"
      :title="t('membership.retentionTitle')"
    >
      {{ t("membership.retention") }}
    </VAlert>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
p { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); margin: 0; }
.history-list { display: grid; gap: var(--vav-space-3); list-style: none; margin: 0; padding: 0; }
</style>
