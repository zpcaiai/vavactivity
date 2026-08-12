<script setup lang="ts">
import { onMounted } from "vue";
import { VAlert, VButton, VCard, VChip, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";

import { datingProfileApi } from "@/features/dating-profile/api";
import { useDatingProfile } from "@/features/dating-profile/composables/useDatingProfile";

const {
  photos,
  busy,
  error,
  notice,
  exists,
  steps,
  breadcrumbs,
  localePath,
  t,
  guard,
  ensureLoaded,
  reloadPhotos
} = useDatingProfile();

async function upload(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  const result = await guard(async () => {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    for (let index = 0; index < bytes.byteLength; index += 1) binary += String.fromCharCode(bytes[index]);
    return datingProfileApi.uploadPhoto({
      filename: file.name,
      mime_type: file.type,
      content_base64: btoa(binary),
      photo_role: photos.value.some((photo) => photo.photo_role === "primary") ? "gallery" : "primary"
    });
  });
  if (result) {
    notice.value = result.exif_removed ? t("dating.photos.uploadedExif") : t("dating.photos.uploaded");
    await reloadPhotos();
  }
  input.value = "";
}

async function makePrimary(photoId: string) {
  await guard(() => datingProfileApi.makePrimary(photoId), t("dating.photos.primarySet"));
  await reloadPhotos();
}

async function remove(photoId: string) {
  if (!window.confirm(t("dating.photos.deleteConfirm"))) return;
  await guard(() => datingProfileApi.deletePhoto(photoId), t("dating.photos.deleted"));
  await reloadPhotos();
}

onMounted(() => void ensureLoaded());
</script>

<template>
  <UserPageLayout
    width="standard"
    :eyebrow="t('ia.groups.matchmaking')"
    :title="t('dating.steps.photos')"
    :description="t('dating.photos.description')"
    :breadcrumbs="breadcrumbs('photos')"
    :sections="steps"
    :sections-label="t('dating.stepsLabel')"
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
      v-if="!exists && !busy"
      state="empty"
      :title="t('dating.emptyTitle')"
      :message="t('dating.emptyMessage')"
    >
      <RouterLink :to="localePath('account/dating-profile')">
        {{ t("dating.goToOverview") }}
      </RouterLink>
    </VPageState>

    <template v-else>
      <VAlert
        tone="info"
        :title="t('dating.photos.storageTitle')"
      >
        {{ t("dating.photos.storage") }}
      </VAlert>

      <VCard>
        <template #title>
          <h2>{{ t("dating.photos.uploadTitle") }}</h2>
        </template>
        <label class="photo-upload">
          <span>{{ t("dating.photos.choose") }}</span>
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            @change="upload"
          >
        </label>
      </VCard>

      <VCard
        v-if="photos.length"
        padding="compact"
      >
        <template #title>
          <h2>{{ t("dating.photos.listTitle") }}</h2>
        </template>
        <ul class="photo-list">
          <li
            v-for="photo in photos"
            :key="photo.photo_id"
          >
            <div class="photo-list__meta">
              <VChip
                :tone="photo.photo_role === 'primary' ? 'brand' : 'neutral'"
                :label="photo.photo_role === 'primary' ? t('dating.photos.primary') : t('dating.photos.gallery')"
              />
              <VChip
                :tone="photo.status === 'approved' ? 'success' : 'info'"
                :label="photo.status"
              />
              <small v-if="photo.rejection_message_safe">{{ photo.rejection_message_safe }}</small>
            </div>
            <div class="photo-list__actions">
              <VButton
                v-if="photo.photo_role !== 'primary'"
                variant="secondary"
                @click="makePrimary(photo.photo_id)"
              >
                {{ t("dating.photos.makePrimary") }}
              </VButton>
              <VButton
                variant="danger"
                @click="remove(photo.photo_id)"
              >
                {{ t("dating.photos.delete") }}
              </VButton>
            </div>
          </li>
        </ul>
      </VCard>

      <VPageState
        v-else-if="!busy"
        state="empty"
        :title="t('dating.photos.emptyTitle')"
        :message="t('dating.photos.emptyMessage')"
      />
    </template>
  </UserPageLayout>
</template>

<style scoped>
h2 { margin: 0; font-size: var(--vav-font-size-md); }
small { color: var(--vav-color-danger); font-size: var(--vav-font-size-xs); }
.photo-upload { display: grid; gap: var(--vav-space-2); }
.photo-upload span { font-size: var(--vav-font-size-sm); font-weight: var(--vav-font-weight-semibold); }
.photo-list { display: grid; gap: var(--vav-space-3); list-style: none; margin: 0; padding: 0; }
.photo-list li { align-items: center; border-block-end: 1px solid var(--vav-color-border); display: flex; flex-wrap: wrap; gap: var(--vav-space-3); justify-content: space-between; padding-block-end: var(--vav-space-2); }
.photo-list__meta, .photo-list__actions { align-items: center; display: flex; flex-wrap: wrap; gap: var(--vav-space-2); }
</style>
