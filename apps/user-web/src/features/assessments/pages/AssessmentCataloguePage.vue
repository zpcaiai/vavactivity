<script setup lang="ts">
import { VAlert, VButton, VCard, VChip, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute } from "vue-router";

import { assessmentsApiClient } from "@/features/assessments/api";
import type { CatalogueEntry, Entitlement } from "@/features/assessments/types";

const route = useRoute();
const { t, te, n } = useI18n();

const locale = computed(() => String(route.params.locale ?? "zh-CN"));

const catalogue = ref<CatalogueEntry[]>([]);
const entitlements = ref<Entitlement[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

/** Versions the member already owns an active entitlement for. */
const ownedVersionIds = computed(
  () =>
    new Set(
      entitlements.value
        .filter((item) => item.status === "active")
        .map((item) => item.version_id)
    )
);

function titleFor(entry: CatalogueEntry): string {
  const key = `assessments.titles.${entry.title_code}`;
  return te(key) ? t(key) : entry.title_code;
}

function categoryFor(entry: CatalogueEntry): string {
  const key = `assessments.categories.${entry.category_code}`;
  return te(key) ? t(key) : entry.category_code;
}

/**
 * The API carries minor units so no rounding happens on the wire. The division
 * belongs here, at the display edge, and nowhere else.
 */
function priceFor(entry: CatalogueEntry): string {
  return n(entry.price_minor_units / 100, {
    style: "currency",
    currency: entry.currency
  });
}

function remainingAttempts(item: Entitlement): number {
  return Math.max(0, item.attempts_granted - item.attempts_consumed);
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const [list, owned] = await Promise.all([
      assessmentsApiClient.catalogue(),
      assessmentsApiClient.entitlements().catch(() => ({ items: [] as Entitlement[] }))
    ]);
    catalogue.value = list.items;
    entitlements.value = owned.items;
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    :title="t('assessments.title')"
    :description="t('assessments.description')"
    :eyebrow="t('assessments.eyebrow')"
    width="wide"
  >
    <VPageState
      v-if="loading"
      state="loading"
      :title="t('common.loading')"
      :message="t('assessments.loadingMessage')"
    />

    <VPageState
      v-else-if="error"
      state="error"
      :title="t('common.errorTitle')"
      :message="error"
      @action="load"
    />

    <template v-else>
      <VAlert
        v-if="entitlements.length"
        tone="info"
        :title="t('assessments.owned.heading')"
      >
        <ul class="assess__owned">
          <li
            v-for="item in entitlements"
            :key="item.id"
          >
            <RouterLink :to="`/${locale}/account/assessments/entitlements/${item.id}`">
              {{ item.product_code }} · {{ item.semantic_version }}
            </RouterLink>
            <span class="assess__note">
              {{
                t("assessments.owned.attempts", {
                  remaining: remainingAttempts(item),
                  granted: item.attempts_granted
                })
              }}
            </span>
          </li>
        </ul>
      </VAlert>

      <VPageState
        v-if="!catalogue.length"
        state="empty"
        :title="t('assessments.emptyTitle')"
        :message="t('assessments.emptyMessage')"
      />

      <ul
        v-else
        class="assess__grid"
      >
        <li
          v-for="entry in catalogue"
          :key="entry.id"
        >
          <VCard>
            <p class="assess__title">
              {{ titleFor(entry) }}
            </p>
            <div class="assess__chips">
              <VChip
                tone="neutral"
                :label="categoryFor(entry)"
              />
              <VChip
                tone="brand"
                :label="entry.semantic_version"
              />
              <!--
                Where the content came from is stated, not implied. A licensed
                instrument and an in-house questionnaire are different things
                and a member is entitled to know which they are buying.
              -->
              <VChip
                tone="info"
                :label="t(`assessments.contentSource.${entry.content_source}`)"
              />
            </div>
            <p class="assess__note">
              {{ t("assessments.questionCount", { count: entry.question_count }) }}
            </p>
            <p class="assess__price">
              {{ priceFor(entry) }}
            </p>

            <VChip
              v-if="ownedVersionIds.has(entry.id)"
              tone="success"
              :label="t('assessments.alreadyOwned')"
            />
            <VButton
              v-else
              disabled
            >
              {{ t("assessments.purchaseViaCheckout") }}
            </VButton>
            <p
              v-if="!ownedVersionIds.has(entry.id)"
              class="assess__note"
            >
              {{ t("assessments.purchaseHint") }}
            </p>
          </VCard>
        </li>
      </ul>
    </template>
  </UserPageLayout>
</template>

<style scoped>
.assess__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(18rem, 1fr));
  gap: var(--vav-space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.assess__owned {
  display: grid;
  gap: var(--vav-space-1);
  margin: var(--vav-space-2) 0 0;
  padding: 0;
  list-style: none;
}

.assess__title {
  margin: 0;
  font-weight: var(--vav-font-weight-medium);
  color: var(--vav-color-text-primary);
}

.assess__chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--vav-space-2);
  margin-top: var(--vav-space-2);
}

.assess__note {
  margin: var(--vav-space-2) 0 0;
  color: var(--vav-color-text-secondary);
}

.assess__price {
  margin: var(--vav-space-2) 0;
  font-size: var(--vav-font-size-xl);
  font-weight: var(--vav-font-weight-bold);
  color: var(--vav-color-text-primary);
}
</style>
