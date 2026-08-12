<script setup lang="ts">
import { onMounted, ref } from "vue";
import { VAlert, VCard, VPageState, VProgress } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { membershipApi, type MembershipSummary } from "@/features/memberships/api";
import {
  quotaPercent,
  useMembershipShell,
  useMembershipState
} from "@/features/memberships/composables/useMembershipShell";

const { sections, breadcrumbs, t } = useMembershipShell("usage");
const { busy, error, guard } = useMembershipState();

const current = ref<MembershipSummary>();

async function load() {
  const value = await guard(() => membershipApi.current());
  if (value) current.value = value;
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('membership.eyebrow')"
    :title="t('membership.usageTitle')"
    :description="t('membership.usageDescription')"
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
      v-if="busy && !current"
      state="loading"
      :title="t('common.loading')"
      :message="t('common.pleaseWait')"
    />

    <div
      v-else-if="current?.quotas.length"
      class="quota-grid"
    >
      <VCard
        v-for="quota in current.quotas"
        :key="quota.id"
        padding="compact"
        :tone="quota.remaining_quantity === 0 ? 'warning' : 'default'"
      >
        <template #title>
          <h2>{{ quota.benefit_code }}</h2>
        </template>
        <VProgress
          :value="quota.consumed_quantity + quota.reserved_quantity"
          :max="quota.allocated_quantity"
          :label="t('membership.consumed')"
        />
        <p>
          {{ t("membership.remaining", { remaining: quota.remaining_quantity, allocated: quota.allocated_quantity }) }}
          <span v-if="quota.reserved_quantity">
            · {{ t("membership.reserved", { reserved: quota.reserved_quantity }) }}
          </span>
          · {{ quotaPercent(quota) }}%
        </p>
      </VCard>
    </div>

    <VPageState
      v-else-if="!busy"
      state="empty"
      :title="t('membership.usageEmptyTitle')"
      :message="t('membership.usageEmptyMessage')"
    />
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
p { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); margin: 0; }
.quota-grid { display: grid; gap: var(--vav-space-4); grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); }
</style>
