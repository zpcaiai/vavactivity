<script setup lang="ts">
import { VAlert, VButton, VCard, VChip, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { discoveryApiClient } from "@/features/discovery/api";
import type { ShareCard, VenueLocation } from "@/features/discovery/types";

const route = useRoute();
const { t, te } = useI18n();

const activityId = computed(() => String(route.params.activityId ?? ""));

const venue = ref<VenueLocation | null>(null);
const share = ref<ShareCard | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const shareUnavailableCode = ref<string | null>(null);
const copied = ref(false);

/**
 * A failed or skipped geocode is a normal outcome, not an error: MAP-001 keeps
 * the operator's typed address and degrades to a search link. Showing "no
 * location" would be wrong — the address is right there.
 */
const hasPin = computed(() => venue.value?.geocode_status === "resolved" && Boolean(venue.value?.place));

const geocodeNote = computed(() => {
  const status = venue.value?.geocode_status;
  if (!status || status === "resolved") return null;
  const code = venue.value?.failure_code;
  const key = code ? `discovery.geocodeFailure.${code}` : `discovery.geocodeStatus.${status}`;
  return te(key) ? t(key) : t(`discovery.geocodeStatus.${status}`);
});

async function load() {
  loading.value = true;
  error.value = null;
  shareUnavailableCode.value = null;
  try {
    venue.value = await discoveryApiClient.venueLocation(activityId.value);
  } catch (caught) {
    // 404 means no location has been recorded yet — a state, not a failure.
    const code = (caught as Error & { code?: string }).code;
    if (code === "VENUE_LOCATION_NOT_FOUND") {
      venue.value = null;
    } else {
      error.value = (caught as Error).message;
    }
  }
  try {
    share.value = await discoveryApiClient.shareCard(activityId.value);
  } catch (caught) {
    // Sharing is refused for unpublished or non-shareable events. That is a
    // deliberate rule, so it is reported as a state rather than an error.
    share.value = null;
    shareUnavailableCode.value = (caught as Error & { code?: string }).code ?? "SHARE_UNAVAILABLE";
  }
  loading.value = false;
}

async function copyLink() {
  const url = share.value?.canonical_url;
  if (!url) return;
  try {
    await navigator.clipboard.writeText(url);
    copied.value = true;
    window.setTimeout(() => {
      copied.value = false;
    }, 2000);
  } catch {
    // Clipboard permission is not guaranteed. The URL is rendered as text
    // right below, so a failure here costs the member nothing.
    copied.value = false;
  }
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    :title="t('discovery.location.title')"
    :description="t('discovery.location.description')"
    :eyebrow="t('discovery.eyebrow')"
  >
    <VPageState
      v-if="loading"
      state="loading"
      :title="t('common.loading')"
      :message="t('discovery.location.loadingMessage')"
    />

    <VPageState
      v-else-if="error"
      state="error"
      :title="t('common.errorTitle')"
      :message="error"
      @action="load"
    />

    <template v-else>
      <VPageState
        v-if="!venue"
        state="empty"
        :title="t('discovery.location.noneTitle')"
        :message="t('discovery.location.noneMessage')"
      />

      <VCard v-else>
        <h2 class="location__heading">
          {{ t("discovery.location.addressHeading") }}
        </h2>
        <p class="location__address">
          {{ venue.display_address }}
        </p>

        <VChip
          :tone="hasPin ? 'success' : 'warning'"
          :label="t(`discovery.geocodeStatus.${venue.geocode_status}`)"
        />

        <!--
          The typed address is authoritative when geocoding did not resolve.
          Naming that explicitly stops a member from assuming the map is simply
          missing.
        -->
        <VAlert
          v-if="geocodeNote"
          tone="info"
          :title="t('discovery.location.approximateTitle')"
        >
          {{ geocodeNote }}
        </VAlert>

        <p
          v-if="hasPin && venue.place"
          class="location__coords"
        >
          {{
            t("discovery.location.coordinates", {
              lat: venue.place.latitude,
              lon: venue.place.longitude
            })
          }}
        </p>

        <a
          v-if="venue.display_link"
          class="location__map-link"
          :href="venue.display_link"
          target="_blank"
          rel="noopener noreferrer"
        >
          {{ hasPin ? t("discovery.location.openMap") : t("discovery.location.searchMap") }}
        </a>
      </VCard>

      <VCard>
        <h2 class="location__heading">
          {{ t("discovery.share.heading") }}
        </h2>

        <VAlert
          v-if="!share"
          tone="info"
          :title="t('discovery.share.unavailableTitle')"
        >
          {{
            shareUnavailableCode && te(`discovery.share.errors.${shareUnavailableCode}`)
              ? t(`discovery.share.errors.${shareUnavailableCode}`)
              : t("discovery.share.unavailableMessage")
          }}
        </VAlert>

        <template v-else>
          <img
            v-if="share.card.cover_image_url"
            class="location__cover"
            :src="share.card.cover_image_url"
            :alt="share.card.title"
          >
          <p
            v-if="share.cover_is_fallback"
            class="location__note"
          >
            {{ t("discovery.share.fallbackCover") }}
          </p>

          <p class="location__card-title">
            {{ share.card.title }}
          </p>
          <p
            v-if="share.card.subtitle"
            class="location__note"
          >
            {{ share.card.subtitle }}
          </p>

          <p class="location__url">
            {{ share.canonical_url }}
          </p>

          <div class="location__actions">
            <VButton @click="copyLink">
              {{ copied ? t("discovery.share.copied") : t("discovery.share.copyLink") }}
            </VButton>
            <a
              class="location__map-link"
              :href="share.qr_target"
              target="_blank"
              rel="noopener noreferrer"
            >
              {{ t("discovery.share.openQrTarget") }}
            </a>
          </div>
        </template>
      </VCard>
    </template>
  </UserPageLayout>
</template>

<style scoped>
.location__heading {
  margin: 0 0 var(--vav-space-2);
  font-size: var(--vav-font-size-lg);
  color: var(--vav-color-text-primary);
}

.location__address,
.location__card-title {
  margin: 0 0 var(--vav-space-2);
  font-weight: var(--vav-font-weight-medium);
  color: var(--vav-color-text-primary);
}

.location__coords,
.location__note,
.location__url {
  margin: var(--vav-space-2) 0 0;
  color: var(--vav-color-text-secondary);
  word-break: break-all;
}

.location__map-link {
  display: inline-block;
  margin-top: var(--vav-space-2);
  color: var(--vav-color-text-brand);
}

.location__cover {
  display: block;
  width: 100%;
  max-width: 32rem;
  border-radius: var(--vav-radius-md);
}

.location__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--vav-space-3);
  margin-top: var(--vav-space-3);
}
</style>
