<script setup lang="ts">
import { onMounted, ref } from "vue";
import { VAlert, VCard, VDescriptionList, VMetric, VPageState, VStatusBadge } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { membershipApi, type MembershipSummary } from "@/features/memberships/api";
import {
  useMembershipShell,
  useMembershipState
} from "@/features/memberships/composables/useMembershipShell";

const { sections, breadcrumbs, localePath, t } = useMembershipShell("overview");
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
    width="wide"
    :eyebrow="t('membership.eyebrow')"
    :title="t('membership.accountTitle')"
    :description="t('membership.accountDescription')"
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

    <template v-else-if="current">
      <VCard tone="brand">
        <template #title>
          <h2>{{ current.plan_name }}</h2>
        </template>
        <template #actions>
          <VStatusBadge
            :status="current.status === 'active' ? 'success' : 'info'"
            :label="current.status"
          />
        </template>
        <VDescriptionList
          :items="[
            { term: t('membership.planCode'), value: current.plan_code },
            { term: t('membership.startsAt'), value: current.starts_at },
            { term: t('membership.cycleEnds'), value: current.current_cycle_ends_at ?? t('membership.openEnded') },
            {
              term: t('membership.cancelScheduled'),
              value: current.cancel_at_period_end ? t('common.yes') : t('common.no')
            }
          ]"
        />
      </VCard>

      <div class="membership-metrics">
        <VMetric
          :label="t('membership.sections.benefits')"
          :value="current.benefits.length"
          :to="localePath('account/membership/benefits')"
        />
        <VMetric
          :label="t('membership.sections.usage')"
          :value="current.quotas.length"
          :to="localePath('account/membership/usage')"
        />
        <VMetric
          :label="t('membership.sections.manage')"
          :value="'→'"
          :to="localePath('account/membership/manage')"
        />
        <VMetric
          :label="t('membership.sections.history')"
          :value="'→'"
          :to="localePath('account/membership/history')"
        />
      </div>

      <VAlert
        tone="info"
        :title="t('membership.retentionTitle')"
      >
        {{ t("membership.retention") }}
      </VAlert>
    </template>

    <VPageState
      v-else-if="!busy"
      state="empty"
      :title="t('membership.noneTitle')"
      :message="t('membership.noneMessage')"
    >
      <RouterLink
        class="membership-cta"
        :to="localePath('membership/plans')"
      >
        {{ t("membership.viewPlans") }}
      </RouterLink>
    </VPageState>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-lg); }
.membership-metrics { display: grid; gap: var(--vav-space-4); grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); }

.membership-cta {
  align-items: center;
  background: var(--vav-color-action-primary);
  border-radius: var(--vav-radius-pill);
  color: var(--vav-color-on-action);
  display: inline-flex;
  font-weight: var(--vav-font-weight-semibold);
  min-block-size: var(--vav-component-button-height);
  padding-inline: var(--vav-space-4);
  text-decoration: none;
}
</style>
