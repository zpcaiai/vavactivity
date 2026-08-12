<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { VAlert, VCard, VChip, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { membershipApi, type MembershipPlan } from "@/features/memberships/api";
import { useMembershipState } from "@/features/memberships/composables/useMembershipShell";
import { useLocalePath } from "@/composables/useAppNavigation";
import { useI18n } from "vue-i18n";

const route = useRoute();
const { t } = useI18n();
const { localePath, locale } = useLocalePath();
const { busy, error, guard } = useMembershipState();

const plans = ref<MembershipPlan[]>([]);
const plan = ref<MembershipPlan>();
const planCode = computed(() => String(route.params.planCode ?? ""));

async function load() {
  const list = await guard(() => membershipApi.plans(locale.value));
  if (list) plans.value = list;
  plan.value = planCode.value
    ? await guard(() => membershipApi.plan(planCode.value, locale.value))
    : undefined;
}

onMounted(load);
watch(() => [planCode.value, locale.value], load);
</script>

<template>
  <UserPageLayout
    width="wide"
    :eyebrow="t('membership.eyebrow')"
    :title="plan ? plan.name : t('membership.plansTitle')"
    :description="plan ? plan.short_description : t('membership.plansDescription')"
    :breadcrumbs="
      plan
        ? [
          { label: t('membership.plansTitle'), to: localePath('membership/plans') },
          { label: plan.name }
        ]
        : [{ label: t('membership.plansTitle') }]
    "
  >
    <VAlert
      v-if="error"
      tone="danger"
      :title="t('common.loadFailed')"
    >
      {{ error }}
    </VAlert>

    <VPageState
      v-if="busy && !plans.length"
      state="loading"
      :title="t('common.loading')"
      :message="t('common.pleaseWait')"
    />

    <VCard v-else-if="plan">
      <template #title>
        <h2>{{ t("membership.benefitsTitle") }}</h2>
      </template>
      <template #description>
        {{ t("membership.benefitsBoundary") }}
      </template>
      <ul class="plan-benefits">
        <li
          v-for="benefit in plan.benefits ?? []"
          :key="benefit.benefit_code"
        >
          <strong>{{ benefit.benefit_code }}</strong>
          <VChip
            tone="neutral"
            :label="benefit.benefit_type"
          />
        </li>
      </ul>
      <template #footer>
        <RouterLink :to="localePath('membership/plans')">
          {{ t("membership.backToPlans") }}
        </RouterLink>
      </template>
    </VCard>

    <div
      v-else
      class="plan-grid"
    >
      <VCard
        v-for="item in plans"
        :key="item.plan_code"
      >
        <template #title>
          <h2>{{ item.name }}</h2>
        </template>
        <template #actions>
          <VChip
            tone="brand"
            :label="item.plan_type"
          />
        </template>
        <p>{{ item.short_description }}</p>
        <template #footer>
          <RouterLink
            class="plan-cta"
            :to="localePath(`membership/plans/${item.plan_code}`)"
          >
            {{ t("membership.viewPlan") }}
          </RouterLink>
        </template>
      </VCard>
    </div>

    <VAlert
      tone="info"
      :title="t('membership.entitlementTitle')"
    >
      {{ t("membership.entitlementBoundary") }}
    </VAlert>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-lg); }
p { margin: 0; color: var(--vav-color-text-muted); }
.plan-grid { display: grid; gap: var(--vav-space-4); grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); }
.plan-benefits { display: grid; gap: var(--vav-space-2); list-style: none; margin: 0; padding: 0; }
.plan-benefits li { align-items: center; display: flex; gap: var(--vav-space-3); justify-content: space-between; }

.plan-cta {
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
