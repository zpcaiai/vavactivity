<script setup lang="ts">
import { VAlert, VButton, VCard, VChip, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { profileMediaApiClient } from "@/features/profile-media/api";
import { useMediaUpload } from "@/features/profile-media/composables/useMediaUpload";
import type {
  MediaAsset,
  MediaKind,
  ProfileMediaView,
  ShareConsent
} from "@/features/profile-media/types";

const { t, te } = useI18n();

const view = ref<ProfileMediaView | null>(null);
const consent = ref<ShareConsent | null>(null);
const loading = ref(true);
const busy = ref(false);
const error = ref<string | null>(null);
const notice = ref<string | null>(null);

const mbti = ref("");
const intro = ref("");
const cityCode = ref("");

const { uploading, progressPercent, error: uploadError, upload } = useMediaUpload();

/**
 * Fetchable URLs, keyed by asset id.
 *
 * `media_path` is the asset's identity, not a URL — private media is only
 * readable through a short-lived viewer-bound grant. Binding the path to a
 * `src` was the original mistake here and produced broken images.
 */
const mediaUrls = ref<Record<string, string>>({});

async function loadMediaUrls(assets: MediaAsset[]) {
  const entries = await Promise.all(
    assets.map(async (asset) => {
      try {
        const grant = await profileMediaApiClient.grant(asset.asset_id);
        return [asset.asset_id, grant.media_url] as const;
      } catch {
        // A grant that cannot be issued leaves the tile without an image
        // rather than rendering a dead `src`; the asset's own state is still
        // shown, which is what the member needs to act on.
        return null;
      }
    })
  );
  mediaUrls.value = Object.fromEntries(entries.filter((entry) => entry !== null));
}

async function onFileSelected(event: Event, kind: MediaKind) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  const updated = await upload(file, kind);
  // Reset the input so re-picking the same file fires `change` again.
  input.value = "";
  if (updated) {
    view.value = updated;
    notice.value = t("profileMedia.uploadDone");
    await loadMediaUrls(updated.assets);
  }
}

const photos = computed(() => (view.value?.assets ?? []).filter((a) => a.kind === "photo"));
const video = computed(() => (view.value?.assets ?? []).find((a) => a.kind === "video") ?? null);

const moderationTone: Record<string, "neutral" | "success" | "warning" | "danger"> = {
  pending: "warning",
  approved: "success",
  rejected: "danger"
};

/**
 * Consent is per field, and every switch defaults to off. Turning the master
 * switch off must visibly disable the rest rather than silently keep values
 * that no longer have any effect.
 */
const sharingOn = computed(() => consent.value?.share_enabled === true);

const consentFields = [
  "share_photos",
  "share_video",
  "share_mbti",
  "share_intro",
  "share_city"
] as const;

function missingLabel(code: string): string {
  const key = `profileMedia.missing.${code}`;
  return te(key) ? t(key) : code;
}

function rejectionLabel(asset: MediaAsset): string | null {
  if (!asset.rejection_reason_code) return null;
  const key = `profileMedia.rejection.${asset.rejection_reason_code}`;
  return te(key) ? t(key) : asset.rejection_reason_code;
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    view.value = await profileMediaApiClient.media();
    await loadMediaUrls(view.value.assets);
    mbti.value = view.value.mbti ?? "";
    intro.value = view.value.intro ?? "";
    cityCode.value = view.value.city_code ?? "";
    consent.value = await profileMediaApiClient.shareConsent().catch(() => null);
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    loading.value = false;
  }
}

async function saveTags() {
  busy.value = true;
  error.value = null;
  notice.value = null;
  try {
    view.value = await profileMediaApiClient.setTags({
      mbti: mbti.value.trim() || null,
      intro: intro.value.trim() || null,
      city_code: cityCode.value.trim() || null
    });
    notice.value = t("profileMedia.tagsSaved");
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    busy.value = false;
  }
}

async function removeAsset(asset: MediaAsset) {
  busy.value = true;
  error.value = null;
  try {
    view.value = await profileMediaApiClient.remove(asset.asset_id);
    await loadMediaUrls(view.value.assets);
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    busy.value = false;
  }
}

async function toggleConsent(field: (typeof consentFields)[number] | "share_enabled") {
  if (!consent.value) return;
  const next: ShareConsent = { ...consent.value, [field]: !consent.value[field] };
  // Turning the master switch off is not a partial state: the per-field flags
  // go with it, so the stored record cannot claim consent for a card that is
  // not shared at all.
  if (field === "share_enabled" && !next.share_enabled) {
    for (const key of consentFields) next[key] = false;
  }
  busy.value = true;
  const previous = consent.value;
  consent.value = next;
  try {
    consent.value = await profileMediaApiClient.setShareConsent(next);
  } catch (caught) {
    consent.value = previous;
    error.value = (caught as Error).message;
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    :title="t('profileMedia.title')"
    :description="t('profileMedia.description')"
    :eyebrow="t('profileMedia.eyebrow')"
    width="wide"
  >
    <VPageState
      v-if="loading"
      state="loading"
      :title="t('common.loading')"
      :message="t('profileMedia.loadingMessage')"
    />

    <VPageState
      v-else-if="error && !view"
      state="error"
      :title="t('common.errorTitle')"
      :message="error"
      @action="load"
    />

    <template v-else-if="view">
      <VAlert
        v-if="error"
        tone="danger"
        :title="t('common.errorTitle')"
      >
        {{ error }}
      </VAlert>
      <VAlert
        v-if="notice"
        tone="success"
        :title="t('common.saved')"
      >
        {{ notice }}
      </VAlert>

      <VCard>
        <h2 class="media__heading">
          {{ t("profileMedia.completeness.heading") }}
        </h2>
        <p class="media__percent">
          {{ view.completeness_percent }}%
        </p>
        <ul
          v-if="view.completeness_missing.length"
          class="media__missing"
        >
          <li
            v-for="code in view.completeness_missing"
            :key="code"
          >
            {{ missingLabel(code) }}
          </li>
        </ul>
        <VChip
          :tone="view.is_published ? 'success' : 'neutral'"
          :label="
            view.is_published
              ? t('profileMedia.published')
              : t('profileMedia.notPublished')
          "
        />
      </VCard>

      <VCard>
        <h2 class="media__heading">
          {{ t("profileMedia.photos.heading") }}
        </h2>
        <p
          v-if="!photos.length"
          class="media__note"
        >
          {{ t("profileMedia.photos.empty") }}
        </p>
        <ul
          v-else
          class="media__grid"
        >
          <li
            v-for="asset in photos"
            :key="asset.asset_id"
          >
            <div class="media__asset">
              <img
                v-if="mediaUrls[asset.asset_id]"
                class="media__thumb"
                :src="mediaUrls[asset.asset_id]"
                :alt="t('profileMedia.photoAlt')"
              >
              <p
                v-else
                class="media__note"
              >
                {{ t("profileMedia.previewUnavailable") }}
              </p>
              <VChip
                :tone="moderationTone[asset.moderation_state] ?? 'neutral'"
                :label="t(`profileMedia.moderation.${asset.moderation_state}`)"
              />
              <p
                v-if="rejectionLabel(asset)"
                class="media__note"
              >
                {{ rejectionLabel(asset) }}
              </p>
              <VButton
                variant="secondary"
                :loading="busy"
                @click="removeAsset(asset)"
              >
                {{ t("profileMedia.remove") }}
              </VButton>
            </div>
          </li>
        </ul>

        <h2 class="media__heading">
          {{ t("profileMedia.video.heading") }}
        </h2>
        <p
          v-if="!video"
          class="media__note"
        >
          {{ t("profileMedia.video.empty") }}
        </p>
        <div
          v-else
          class="media__asset"
        >
          <video
            v-if="mediaUrls[video.asset_id]"
            class="media__video"
            :src="mediaUrls[video.asset_id]"
            controls
            preload="metadata"
          />
          <p
            v-else
            class="media__note"
          >
            {{ t("profileMedia.previewUnavailable") }}
          </p>
          <VChip
            :tone="moderationTone[video.moderation_state] ?? 'neutral'"
            :label="t(`profileMedia.moderation.${video.moderation_state}`)"
          />
          <VButton
            variant="secondary"
            :loading="busy"
            @click="removeAsset(video)"
          >
            {{ t("profileMedia.remove") }}
          </VButton>
        </div>

        <div class="media__upload">
          <label class="media__upload-control">
            <span>{{ t("profileMedia.addPhoto") }}</span>
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp,image/heic,image/heif"
              :disabled="uploading || photos.length >= 3"
              @change="onFileSelected($event, 'photo')"
            >
          </label>
          <label class="media__upload-control">
            <span>{{ t("profileMedia.addVideo") }}</span>
            <input
              type="file"
              accept="video/mp4,video/quicktime"
              :disabled="uploading || Boolean(video)"
              @change="onFileSelected($event, 'video')"
            >
          </label>
        </div>

        <!--
          The limits shown here are the server's; storage enforces them too, so
          this text is a courtesy rather than the control.
        -->
        <p class="media__note">
          {{ t("profileMedia.uploadLimits") }}
        </p>

        <p
          v-if="uploading"
          class="media__note"
        >
          {{ t("profileMedia.uploadProgress", { percent: progressPercent }) }}
        </p>

        <VAlert
          v-if="uploadError"
          tone="danger"
          :title="t('profileMedia.uploadFailed')"
        >
          {{ uploadError }}
        </VAlert>

        <p
          v-if="view.pending_assets.length"
          class="media__note"
        >
          {{ t("profileMedia.pending", { count: view.pending_assets.length }) }}
        </p>
      </VCard>

      <VCard>
        <h2 class="media__heading">
          {{ t("profileMedia.tags.heading") }}
        </h2>

        <label
          class="media__label"
          for="mbti"
        >{{ t("profileMedia.tags.mbtiLabel") }}</label>
        <input
          id="mbti"
          v-model="mbti"
          class="media__input"
          type="text"
          maxlength="4"
        >

        <label
          class="media__label"
          for="intro"
        >{{ t("profileMedia.tags.introLabel") }}</label>
        <textarea
          id="intro"
          v-model="intro"
          class="media__input"
          rows="3"
          maxlength="500"
        />

        <label
          class="media__label"
          for="city"
        >{{ t("profileMedia.tags.cityLabel") }}</label>
        <input
          id="city"
          v-model="cityCode"
          class="media__input"
          type="text"
          maxlength="32"
        >

        <VButton
          :loading="busy"
          @click="saveTags"
        >
          {{ t("common.save") }}
        </VButton>
      </VCard>

      <VCard v-if="consent">
        <h2 class="media__heading">
          {{ t("profileMedia.share.heading") }}
        </h2>
        <p class="media__note">
          {{ t("profileMedia.share.explanation") }}
        </p>

        <label class="media__switch">
          <input
            type="checkbox"
            :checked="consent.share_enabled"
            :disabled="busy"
            @change="toggleConsent('share_enabled')"
          >
          <span>{{ t("profileMedia.share.enabled") }}</span>
        </label>

        <label
          v-for="field in consentFields"
          :key="field"
          class="media__switch"
        >
          <input
            type="checkbox"
            :checked="consent[field]"
            :disabled="busy || !sharingOn"
            @change="toggleConsent(field)"
          >
          <span>{{ t(`profileMedia.share.${field}`) }}</span>
        </label>

        <p
          v-if="!sharingOn"
          class="media__note"
        >
          {{ t("profileMedia.share.disabledHint") }}
        </p>
      </VCard>
    </template>
  </UserPageLayout>
</template>

<style scoped>
.media__heading {
  margin: var(--vav-space-4) 0 var(--vav-space-2);
  font-size: var(--vav-font-size-lg);
  color: var(--vav-color-text-primary);
}

.media__heading:first-child {
  margin-top: 0;
}

.media__percent {
  margin: 0;
  font-size: var(--vav-font-size-3xl);
  font-weight: var(--vav-font-weight-bold);
  color: var(--vav-color-text-primary);
}

.media__note {
  margin: var(--vav-space-2) 0 0;
  color: var(--vav-color-text-secondary);
}

.media__missing {
  margin: var(--vav-space-2) 0;
  padding-left: var(--vav-space-4);
  color: var(--vav-color-text-secondary);
}

.media__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr));
  gap: var(--vav-space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.media__asset {
  display: grid;
  gap: var(--vav-space-2);
  justify-items: start;
}

.media__thumb,
.media__video {
  width: 100%;
  border-radius: var(--vav-radius-md);
}

.media__label {
  display: block;
  margin-top: var(--vav-space-3);
  font-weight: var(--vav-font-weight-medium);
  color: var(--vav-color-text-primary);
}

.media__input {
  width: 100%;
  margin-top: var(--vav-space-1);
  margin-bottom: var(--vav-space-2);
  padding: var(--vav-space-2) var(--vav-space-3);
  border: 1px solid var(--vav-color-border-default);
  border-radius: var(--vav-radius-md);
  background: var(--vav-color-surface-default);
  color: var(--vav-color-text-primary);
  font: inherit;
}

.media__upload {
  display: flex;
  flex-wrap: wrap;
  gap: var(--vav-space-3);
  margin-top: var(--vav-space-3);
}

.media__upload-control {
  display: grid;
  gap: var(--vav-space-1);
  color: var(--vav-color-text-primary);
}

.media__switch {
  display: flex;
  align-items: center;
  gap: var(--vav-space-2);
  margin-top: var(--vav-space-2);
  color: var(--vav-color-text-primary);
}
</style>
