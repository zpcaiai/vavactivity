<script setup lang="ts">
import { VAlert, VAvatar, VButton, VCard, VChip, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { socialApiClient } from "@/features/attendee-social/api";
import type {
  AttendeePreview,
  AttendeePreviewItem,
  PreviewConsent
} from "@/features/attendee-social/types";

const route = useRoute();
const { t } = useI18n();

const activityId = computed(() => String(route.params.activityId ?? ""));
/** Optional: present when the viewer is themselves registered for this event. */
const registrationId = computed(() => {
  const value = route.query.registrationId;
  return typeof value === "string" && value.length ? value : null;
});

const preview = ref<AttendeePreview | null>(null);
const consent = ref<PreviewConsent | null>(null);
const introDraft = ref("");
const loading = ref(true);
const saving = ref(false);
const error = ref<string | null>(null);
const notice = ref<string | null>(null);
const busyUserId = ref<string | null>(null);
const followed = ref<Set<string>>(new Set());
const metWanted = ref<Set<string>>(new Set());

/**
 * `not_asked` is a refusal, not a pending state. Treating it as "we will show
 * you once you decide" would be accurate; treating it as "you are listed" would
 * be a disclosure the member never agreed to.
 */
const isListed = computed(() => consent.value?.consent_state === "granted");
const canGrant = computed(
  () => consent.value !== null && consent.value.consent_state !== "granted"
);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    preview.value = await socialApiClient.attendeePreview(activityId.value, { limit: 12 });
  } catch (caught) {
    error.value = (caught as Error).message;
  }
  if (registrationId.value) {
    try {
      consent.value = await socialApiClient.consent(registrationId.value);
      introDraft.value = consent.value.intro_line ?? "";
    } catch {
      // A viewer who is not the owner of that registration simply gets no
      // consent panel; the preview itself is unaffected.
      consent.value = null;
    }
  }
  const existing = await socialApiClient.following(200).catch(() => ({ items: [] }));
  followed.value = new Set(existing.items.map((edge) => edge.user_id));
  loading.value = false;
}

async function decide(decision: "granted" | "declined" | "withdrawn") {
  if (!registrationId.value) return;
  saving.value = true;
  error.value = null;
  notice.value = null;
  try {
    consent.value = await socialApiClient.setConsent(registrationId.value, { decision });
    notice.value = t(`social.consent.saved.${decision}`);
    await load();
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    saving.value = false;
  }
}

async function saveIntro() {
  if (!registrationId.value) return;
  saving.value = true;
  try {
    const value = introDraft.value.trim();
    consent.value = await socialApiClient.setIntro(registrationId.value, value.length ? value : null);
    notice.value = t("social.consent.introSaved");
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    saving.value = false;
  }
}

async function toggleFollow(item: AttendeePreviewItem) {
  busyUserId.value = item.user_id;
  error.value = null;
  try {
    if (followed.value.has(item.user_id)) {
      await socialApiClient.unfollow(item.user_id);
      followed.value.delete(item.user_id);
    } else {
      await socialApiClient.follow(item.user_id);
      followed.value.add(item.user_id);
    }
    followed.value = new Set(followed.value);
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    busyUserId.value = null;
  }
}

async function wantToMeet(item: AttendeePreviewItem) {
  busyUserId.value = item.user_id;
  try {
    await socialApiClient.wantToMeet(item.user_id, activityId.value);
    metWanted.value.add(item.user_id);
    metWanted.value = new Set(metWanted.value);
    notice.value = t("social.wantToMeet.recorded");
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    busyUserId.value = null;
  }
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    :title="t('social.preview.title')"
    :description="t('social.preview.description')"
    :eyebrow="t('social.eyebrow')"
    width="wide"
  >
    <VPageState
      v-if="loading"
      state="loading"
      :title="t('common.loading')"
      :message="t('social.preview.loadingMessage')"
    />

    <template v-else>
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

      <VCard v-if="consent">
        <h2 class="social__heading">
          {{ t("social.consent.heading") }}
        </h2>
        <p class="social__note">
          {{ t("social.consent.explanation") }}
        </p>

        <VChip
          :tone="isListed ? 'success' : 'neutral'"
          :label="t(`social.consent.state.${consent.consent_state}`)"
        />

        <div class="social__actions">
          <VButton
            v-if="canGrant"
            :loading="saving"
            @click="decide('granted')"
          >
            {{ t("social.consent.grant") }}
          </VButton>
          <VButton
            v-if="consent.consent_state === 'not_asked'"
            variant="secondary"
            :loading="saving"
            @click="decide('declined')"
          >
            {{ t("social.consent.decline") }}
          </VButton>
          <VButton
            v-if="consent.consent_state === 'granted'"
            variant="danger"
            :loading="saving"
            @click="decide('withdrawn')"
          >
            {{ t("social.consent.withdraw") }}
          </VButton>
        </div>

        <template v-if="isListed">
          <label
            class="social__label"
            for="intro-line"
          >{{ t("social.consent.introLabel") }}</label>
          <input
            id="intro-line"
            v-model="introDraft"
            class="social__input"
            type="text"
            maxlength="60"
            :placeholder="t('social.consent.introPlaceholder')"
          >
          <p class="social__note">
            {{ t("social.consent.introHint", { max: 60 }) }}
          </p>
          <VButton
            variant="secondary"
            :loading="saving"
            @click="saveIntro"
          >
            {{ t("social.consent.saveIntro") }}
          </VButton>
        </template>
      </VCard>

      <VPageState
        v-if="!preview || !preview.items.length"
        state="empty"
        :title="t('social.preview.emptyTitle')"
        :message="t('social.preview.emptyMessage')"
      />

      <template v-else>
        <ul class="social__grid">
          <li
            v-for="item in preview.items"
            :key="item.user_id"
          >
            <VCard>
              <div class="social__attendee">
                <VAvatar
                  :src="item.avatar_url ?? undefined"
                  :name="item.display_name"
                  size="large"
                />
                <div class="social__attendee-main">
                  <p class="social__attendee-name">
                    {{ item.display_name }}
                  </p>
                  <p
                    v-if="item.intro_line"
                    class="social__note"
                  >
                    {{ item.intro_line }}
                  </p>
                </div>
              </div>
              <div class="social__actions">
                <VButton
                  variant="secondary"
                  :disabled="busyUserId === item.user_id"
                  @click="toggleFollow(item)"
                >
                  {{ followed.has(item.user_id) ? t("social.unfollow") : t("social.follow") }}
                </VButton>
                <VButton
                  variant="secondary"
                  :disabled="busyUserId === item.user_id || metWanted.has(item.user_id)"
                  @click="wantToMeet(item)"
                >
                  {{
                    metWanted.has(item.user_id)
                      ? t("social.wantToMeet.done")
                      : t("social.wantToMeet.action")
                  }}
                </VButton>
              </div>
            </VCard>
          </li>
        </ul>

        <!--
          Only consenting attendees are counted here. There is intentionally no
          "and N others who declined" — that number would let anyone infer the
          non-consenting headcount of a small event.
        -->
        <p
          v-if="preview.additional_visible_count > 0"
          class="social__note"
        >
          {{ t("social.preview.additional", { count: preview.additional_visible_count }) }}
        </p>
      </template>
    </template>
  </UserPageLayout>
</template>

<style scoped>
.social__heading {
  margin: 0 0 var(--vav-space-2);
  font-size: var(--vav-font-size-lg);
  color: var(--vav-color-text-primary);
}

.social__note {
  margin: var(--vav-space-2) 0 0;
  color: var(--vav-color-text-secondary);
}

.social__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--vav-space-2);
  margin-top: var(--vav-space-3);
}

.social__label {
  display: block;
  margin-top: var(--vav-space-3);
  font-weight: var(--vav-font-weight-medium);
  color: var(--vav-color-text-primary);
}

.social__input {
  width: 100%;
  margin-top: var(--vav-space-1);
  padding: var(--vav-space-2) var(--vav-space-3);
  border: 1px solid var(--vav-color-border-default);
  border-radius: var(--vav-radius-md);
  background: var(--vav-color-surface-default);
  color: var(--vav-color-text-primary);
}

.social__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
  gap: var(--vav-space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.social__attendee {
  display: flex;
  align-items: center;
  gap: var(--vav-space-3);
}

.social__attendee-main {
  min-width: 0;
}

.social__attendee-name {
  margin: 0;
  font-weight: var(--vav-font-weight-medium);
  color: var(--vav-color-text-primary);
}
</style>
