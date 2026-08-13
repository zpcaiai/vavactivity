<script setup lang="ts">
import { VAlert, VButton, VCard, VChip, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute } from "vue-router";

import { useDiscoveryFeed } from "@/features/discovery/composables/useDiscoveryFeed";
import type { DiscoveryItem } from "@/features/discovery/types";

const route = useRoute();
const { t, te } = useI18n();

const locale = computed(() => String(route.params.locale ?? "zh-CN"));
const cityInput = ref("");

const {
  feed,
  preference,
  items,
  loading,
  saving,
  error,
  showsUnconfirmedCity,
  suggestedSwitch,
  fellBackToNational,
  hasMore,
  load,
  loadMore,
  confirmCity,
  setIpSuggestionAllowed
} = useDiscoveryFeed();

onMounted(() => load());

function cityLabel(code: string | null | undefined): string {
  if (!code) return t("discovery.cityUnknown");
  const key = `discovery.cities.${code}`;
  return te(key) ? t(key) : code;
}

/**
 * The server's machine reason for falling back to national results. GEO-001
 * asks the member to be told *why*, so an unmapped code still says something
 * rather than nothing.
 */
function fallbackMessage(): string {
  const reason = feed.value?.fallback_reason ?? "not_applied";
  const key = `discovery.fallback.${reason}`;
  return te(key) ? t(key) : t("discovery.fallback.local_results_empty");
}

function startsAtLabel(item: DiscoveryItem): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(item.starts_at));
}

function onApplyCity() {
  const value = cityInput.value.trim();
  void confirmCity(value.length ? value : null);
}
</script>

<template>
  <UserPageLayout
    :title="t('discovery.title')"
    :description="t('discovery.description')"
    :eyebrow="t('discovery.eyebrow')"
    width="wide"
  >
    <VPageState
      v-if="loading && !items.length"
      state="loading"
      :title="t('common.loading')"
      :message="t('discovery.loadingMessage')"
    />

    <VPageState
      v-else-if="error && !items.length"
      state="error"
      :title="t('common.errorTitle')"
      :message="error"
      @action="load()"
    />

    <template v-else>
      <!--
        An IP-derived city is a guess, not a choice. Saying so — and offering
        the correction inline — is the difference between a helpful default and
        a filter the member never agreed to.
      -->
      <VAlert
        v-if="showsUnconfirmedCity"
        tone="info"
        :title="t('discovery.ipSuggestionTitle')"
      >
        <p>{{ t("discovery.ipSuggestionMessage", { city: cityLabel(feed?.city_code) }) }}</p>
        <div class="discovery__actions">
          <VButton
            :loading="saving"
            @click="confirmCity(feed?.city_code ?? null)"
          >
            {{ t("discovery.confirmCity", { city: cityLabel(feed?.city_code) }) }}
          </VButton>
          <VButton
            variant="secondary"
            :loading="saving"
            @click="setIpSuggestionAllowed(false)"
          >
            {{ t("discovery.disableIpSuggestion") }}
          </VButton>
        </div>
      </VAlert>

      <VAlert
        v-if="suggestedSwitch"
        tone="info"
        :title="t('discovery.switchCityTitle')"
      >
        <p>{{ t("discovery.switchCityMessage", { city: cityLabel(suggestedSwitch) }) }}</p>
        <VButton
          variant="secondary"
          :loading="saving"
          @click="confirmCity(suggestedSwitch)"
        >
          {{ t("discovery.switchCity", { city: cityLabel(suggestedSwitch) }) }}
        </VButton>
      </VAlert>

      <VAlert
        v-if="fellBackToNational"
        tone="warning"
        :title="t('discovery.nationalFallbackTitle')"
      >
        {{ fallbackMessage() }}
      </VAlert>

      <VAlert
        v-if="error"
        tone="danger"
        :title="t('common.errorTitle')"
      >
        {{ error }}
      </VAlert>

      <VCard class="discovery__controls">
        <label
          class="discovery__label"
          for="discovery-city"
        >
          {{ t("discovery.cityLabel") }}
        </label>
        <div class="discovery__control-row">
          <input
            id="discovery-city"
            v-model="cityInput"
            class="discovery__input"
            type="text"
            :placeholder="preference?.city_code ?? t('discovery.cityPlaceholder')"
          >
          <VButton
            :loading="saving"
            @click="onApplyCity"
          >
            {{ t("discovery.applyCity") }}
          </VButton>
          <VButton
            v-if="preference?.city_code"
            variant="secondary"
            :loading="saving"
            @click="confirmCity(null)"
          >
            {{ t("discovery.clearCity") }}
          </VButton>
        </div>
        <p class="discovery__scope">
          {{
            t("discovery.scopeSummary", {
              scope: t(`discovery.scope.${feed?.scope ?? "national"}`),
              city: cityLabel(feed?.city_code),
              count: feed?.local_count ?? 0
            })
          }}
        </p>
      </VCard>

      <VPageState
        v-if="!items.length"
        state="empty"
        :title="t('discovery.emptyTitle')"
        :message="t('discovery.emptyMessage')"
      />

      <ul
        v-else
        class="discovery__list"
      >
        <li
          v-for="item in items"
          :key="item.id"
        >
          <VCard>
            <div class="discovery__item">
              <div class="discovery__item-main">
                <RouterLink
                  class="discovery__item-link"
                  :to="`/${locale}/activities/${item.id}`"
                >
                  {{ item.title ?? t("discovery.untitled") }}
                </RouterLink>
                <p class="discovery__item-meta">
                  {{ startsAtLabel(item) }}
                </p>
                <p
                  v-if="item.display_address"
                  class="discovery__item-meta"
                >
                  {{ item.display_address }}
                </p>
              </div>
              <VChip
                v-if="item.city_code"
                tone="neutral"
                :label="cityLabel(item.city_code)"
              />
            </div>
          </VCard>
        </li>
      </ul>

      <VButton
        v-if="hasMore"
        variant="secondary"
        @click="loadMore()"
      >
        {{ t("discovery.loadMore") }}
      </VButton>
    </template>
  </UserPageLayout>
</template>

<style scoped>
.discovery__actions,
.discovery__control-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--vav-space-2);
  margin-top: var(--vav-space-2);
}

.discovery__label {
  display: block;
  font-weight: var(--vav-font-weight-medium);
  color: var(--vav-color-text-primary);
}

.discovery__input {
  flex: 1 1 12rem;
  min-width: 0;
  padding: var(--vav-space-2) var(--vav-space-3);
  border: 1px solid var(--vav-color-border-default);
  border-radius: var(--vav-radius-md);
  background: var(--vav-color-surface-default);
  color: var(--vav-color-text-primary);
}

.discovery__scope {
  margin: var(--vav-space-2) 0 0;
  color: var(--vav-color-text-secondary);
}

.discovery__list {
  display: grid;
  gap: var(--vav-space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.discovery__item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--vav-space-4);
}

.discovery__item-link {
  font-weight: var(--vav-font-weight-medium);
  color: var(--vav-color-text-primary);
}

.discovery__item-meta {
  margin: var(--vav-space-1) 0 0;
  color: var(--vav-color-text-secondary);
}
</style>
