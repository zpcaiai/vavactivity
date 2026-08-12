<script setup lang="ts">
import { onMounted, ref } from "vue";
import { VAlert, VCard, VChip, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { membershipApi, type MembershipSummary } from "@/features/memberships/api";
import {
  useMembershipShell,
  useMembershipState
} from "@/features/memberships/composables/useMembershipShell";

const { sections, breadcrumbs, t } = useMembershipShell("benefits");
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
    :title="t('membership.benefitsTitle')"
    :description="t('membership.benefitsDescription')"
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

    <VCard v-else-if="current?.benefits.length">
      <template #title>
        <h2>{{ current.plan_name }}</h2>
      </template>
      <template #description>
        {{ t("membership.benefitsBoundary") }}
      </template>
      <ul class="benefit-list">
        <li
          v-for="benefit in current.benefits"
          :key="benefit.benefit_code"
        >
          <strong>{{ benefit.benefit_code }}</strong>
          <VChip
            tone="neutral"
            :label="benefit.benefit_type"
          />
        </li>
      </ul>
    </VCard>

    <VPageState
      v-else-if="!busy"
      state="empty"
      :title="t('membership.benefitsEmptyTitle')"
      :message="t('membership.benefitsEmptyMessage')"
    />
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
.benefit-list { display: grid; gap: var(--vav-space-2); list-style: none; margin: 0; padding: 0; }
.benefit-list li { align-items: center; border-block-end: 1px solid var(--vav-color-border); display: flex; gap: var(--vav-space-3); justify-content: space-between; padding-block-end: var(--vav-space-2); }
</style>
