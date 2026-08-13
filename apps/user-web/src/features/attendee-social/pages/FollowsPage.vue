<script setup lang="ts">
import { VAlert, VButton, VCard, VChip, VPageState, VSection } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { socialApiClient } from "@/features/attendee-social/api";
import type { FollowEdge, SocialNotificationPreferences } from "@/features/attendee-social/types";

const { t } = useI18n();

const following = ref<FollowEdge[]>([]);
const followers = ref<FollowEdge[]>([]);
const preferences = ref<SocialNotificationPreferences | null>(null);
const loading = ref(true);
const busy = ref(false);
const error = ref<string | null>(null);
const preferenceError = ref<string | null>(null);
const notice = ref<string | null>(null);
const busyUserId = ref<string | null>(null);

function followedAtLabel(edge: FollowEdge): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(
    new Date(edge.followed_at)
  );
}

async function loadPreferences() {
  preferenceError.value = null;
  try {
    preferences.value = await socialApiClient.notificationPreferences();
  } catch (caught) {
    preferences.value = null;
    preferenceError.value = (caught as Error).message;
  }
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const [out, back] = await Promise.all([
      socialApiClient.following(200),
      socialApiClient.followers(200)
    ]);
    following.value = out.items;
    followers.value = back.items;
    await loadPreferences();
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    loading.value = false;
  }
}

async function unfollow(edge: FollowEdge) {
  busyUserId.value = edge.user_id;
  error.value = null;
  try {
    await socialApiClient.unfollow(edge.user_id);
    following.value = following.value.filter((item) => item.user_id !== edge.user_id);
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    busyUserId.value = null;
  }
}

async function followBack(edge: FollowEdge) {
  busyUserId.value = edge.user_id;
  error.value = null;
  try {
    await socialApiClient.follow(edge.user_id);
    await load();
  } catch (caught) {
    error.value = (caught as Error).message;
  } finally {
    busyUserId.value = null;
  }
}

async function toggleNotification() {
  if (!preferences.value) return;
  const previous = preferences.value;
  const next = { followed_user_registered: !previous.followed_user_registered };
  preferences.value = next;
  busy.value = true;
  try {
    preferences.value = await socialApiClient.setNotificationPreferences(next);
    notice.value = t("common.saved");
  } catch (caught) {
    preferences.value = previous;
    error.value = (caught as Error).message;
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    :title="t('social.follows.title')"
    :description="t('social.follows.description')"
    :eyebrow="t('social.eyebrow')"
    width="wide"
  >
    <VPageState
      v-if="loading"
      state="loading"
      :title="t('common.loading')"
      :message="t('social.follows.loadingMessage')"
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

      <VCard v-if="preferences">
        <h2 class="follows__heading">
          {{ t("social.follows.notificationHeading") }}
        </h2>
        <label class="follows__switch">
          <input
            type="checkbox"
            :checked="preferences.followed_user_registered"
            :disabled="busy"
            @change="toggleNotification"
          >
          <span>{{ t("social.follows.notifyOnRegistration") }}</span>
        </label>
        <p class="follows__note">
          {{ t("social.follows.notifyHint") }}
        </p>
      </VCard>
      <VAlert
        v-else-if="preferenceError"
        tone="danger"
        :title="t('social.follows.preferenceLoadFailed')"
      >
        <p>{{ preferenceError }}</p>
        <VButton
          variant="secondary"
          :loading="busy"
          @click="loadPreferences"
        >
          {{ t("common.retry") }}
        </VButton>
      </VAlert>

      <VSection
        :level="2"
        :title="t('social.follows.followingHeading')"
      >
        <template #actions>
          <VChip
            tone="neutral"
            :label="String(following.length)"
          />
        </template>

        <p
          v-if="!following.length"
          class="follows__note"
        >
          {{ t("social.follows.followingEmpty") }}
        </p>
        <ul
          v-else
          class="follows__list"
        >
          <li
            v-for="edge in following"
            :key="edge.user_id"
          >
            <VCard>
              <div class="follows__row">
                <div>
                  <p class="follows__id">
                    {{ edge.user_id }}
                  </p>
                  <p class="follows__note">
                    {{ t("social.follows.since", { date: followedAtLabel(edge) }) }}
                  </p>
                </div>
                <VButton
                  variant="secondary"
                  :disabled="busyUserId === edge.user_id"
                  @click="unfollow(edge)"
                >
                  {{ t("social.unfollow") }}
                </VButton>
              </div>
            </VCard>
          </li>
        </ul>
      </VSection>

      <VSection
        :level="2"
        :title="t('social.follows.followersHeading')"
      >
        <template #actions>
          <VChip
            tone="neutral"
            :label="String(followers.length)"
          />
        </template>

        <p
          v-if="!followers.length"
          class="follows__note"
        >
          {{ t("social.follows.followersEmpty") }}
        </p>
        <ul
          v-else
          class="follows__list"
        >
          <li
            v-for="edge in followers"
            :key="edge.user_id"
          >
            <VCard>
              <div class="follows__row">
                <div>
                  <p class="follows__id">
                    {{ edge.user_id }}
                  </p>
                  <p class="follows__note">
                    {{ t("social.follows.since", { date: followedAtLabel(edge) }) }}
                  </p>
                </div>
                <div class="follows__actions">
                  <VChip
                    v-if="edge.is_mutual"
                    tone="success"
                    :label="t('social.follows.mutual')"
                  />
                  <VButton
                    v-else
                    variant="secondary"
                    :disabled="busyUserId === edge.user_id"
                    @click="followBack(edge)"
                  >
                    {{ t("social.follows.followBack") }}
                  </VButton>
                </div>
              </div>
            </VCard>
          </li>
        </ul>
      </VSection>
    </template>
  </UserPageLayout>
</template>

<style scoped>
.follows__heading {
  margin: 0 0 var(--vav-space-2);
  font-size: var(--vav-font-size-lg);
  color: var(--vav-color-text-primary);
}

.follows__note {
  margin: var(--vav-space-1) 0 0;
  color: var(--vav-color-text-secondary);
}

.follows__list {
  display: grid;
  gap: var(--vav-space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.follows__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--vav-space-4);
}

.follows__id {
  margin: 0;
  font-weight: var(--vav-font-weight-medium);
  color: var(--vav-color-text-primary);
  word-break: break-all;
}

.follows__actions {
  display: flex;
  align-items: center;
  gap: var(--vav-space-2);
  flex-shrink: 0;
}

.follows__switch {
  display: flex;
  align-items: center;
  gap: var(--vav-space-2);
  margin-top: var(--vav-space-2);
  color: var(--vav-color-text-primary);
}
</style>
