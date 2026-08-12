<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { VAlert, VButton, VCard, VDescriptionList, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import {
  membershipApi,
  type MembershipPlan,
  type MembershipSummary
} from "@/features/memberships/api";
import {
  useMembershipShell,
  useMembershipState
} from "@/features/memberships/composables/useMembershipShell";

const { sections, breadcrumbs, locale, t } = useMembershipShell("manage");
const { busy, error, notice, guard } = useMembershipState();

const current = ref<MembershipSummary>();
const plans = ref<MembershipPlan[]>([]);
const selected = ref("");
const preview = ref<Record<string, unknown>>();

const alternatives = computed(() =>
  plans.value.filter((item) => item.plan_code !== current.value?.plan_code)
);

async function load() {
  const [summary, list] = await Promise.all([
    guard(() => membershipApi.current()),
    guard(() => membershipApi.plans(locale.value))
  ]);
  if (summary) current.value = summary;
  if (list) plans.value = list;
  if (!selected.value) selected.value = alternatives.value[0]?.plan_code ?? "";
}

async function generatePreview() {
  if (!selected.value) return;
  preview.value = await guard(() => membershipApi.preview(selected.value, "upgrade"));
}

async function confirm() {
  if (!selected.value || !window.confirm(t("membership.changeConfirm"))) return;
  const request = await guard(() => membershipApi.requestChange(selected.value, "upgrade"));
  if (!request) return;
  await guard(
    () => membershipApi.confirmChange(String(request.id), Number(request.version)),
    t("membership.changeConfirmed")
  );
  preview.value = undefined;
  await load();
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('membership.eyebrow')"
    :title="t('membership.manageTitle')"
    :description="t('membership.manageDescription')"
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
    <VAlert
      v-if="notice"
      tone="success"
      :title="t('common.done')"
      live
    >
      {{ notice }}
    </VAlert>

    <VPageState
      v-if="busy && !current"
      state="loading"
      :title="t('common.loading')"
      :message="t('common.pleaseWait')"
    />

    <template v-else>
      <VCard>
        <template #title>
          <h2>{{ t("membership.changeTitle") }}</h2>
        </template>
        <template #description>
          {{ t("membership.changeDescription") }}
        </template>
        <label class="manage-field">
          <span>{{ t("membership.targetPlan") }}</span>
          <select v-model="selected">
            <option
              v-for="item in alternatives"
              :key="item.plan_code"
              :value="item.plan_code"
            >
              {{ item.name }}
            </option>
          </select>
        </label>
        <template #footer>
          <VButton
            variant="secondary"
            :disabled="!selected"
            :loading="busy"
            @click="generatePreview"
          >
            {{ t("membership.generatePreview") }}
          </VButton>
        </template>
      </VCard>

      <VCard
        v-if="preview"
        tone="info"
      >
        <template #title>
          <h2>{{ t("membership.previewTitle") }}</h2>
        </template>
        <VDescriptionList
          :columns="1"
          :items="[
            {
              term: t('membership.effectivePolicy'),
              value: String(preview.effective_policy ?? '-')
            }
          ]"
        />
        <p>{{ t("membership.priceBoundary") }}</p>
        <template #footer>
          <VButton
            :loading="busy"
            @click="confirm"
          >
            {{ t("membership.confirmChange") }}
          </VButton>
        </template>
      </VCard>

      <VAlert
        tone="warning"
        :title="t('membership.hardConstraintTitle')"
      >
        {{ t("membership.hardConstraint") }}
      </VAlert>
    </template>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
p { color: var(--vav-color-text-muted); font-size: var(--vav-font-size-sm); margin: 0; }
.manage-field { display: grid; gap: var(--vav-space-1); }
.manage-field span { font-size: var(--vav-font-size-sm); font-weight: var(--vav-font-weight-semibold); }

.manage-field select {
  background: var(--vav-color-surface-raised);
  border: 1px solid var(--vav-color-border);
  border-radius: var(--vav-component-input-radius);
  color: var(--vav-color-text);
  font: inherit;
  min-block-size: var(--vav-component-input-height);
  padding-inline: var(--vav-component-input-padding-inline);
}
</style>
