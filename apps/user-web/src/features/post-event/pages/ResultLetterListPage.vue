<script setup lang="ts">
import { VCard, VChip, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, RouterLink } from "vue-router";

import { postEventApiClient } from "@/features/post-event/api";
import type { LetterOutcome, ResultLetterSummary } from "@/features/post-event/types";

const route = useRoute();
const { t, d } = useI18n();

const letters = ref<ResultLetterSummary[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

const locale = computed(() => String(route.params.locale ?? "zh-CN"));

const toneFor: Record<LetterOutcome, "success" | "neutral" | "info"> = {
  mutual_match: "success",
  no_match: "neutral",
  not_eligible: "info"
};

async function load() {
  loading.value = true;
  error.value = null;
  try {
    letters.value = (await postEventApiClient.resultLetters()).items;
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
    :title="t('postEvent.letters.title')"
    :description="t('postEvent.letters.description')"
    :eyebrow="t('postEvent.eyebrow')"
    width="reading"
  >
    <VPageState
      v-if="loading"
      state="loading"
      :title="t('common.loading')"
      :message="t('postEvent.letters.loadingMessage')"
    />

    <VPageState
      v-else-if="error"
      state="error"
      :title="t('common.errorTitle')"
      :message="error"
      @action="load"
    />

    <VPageState
      v-else-if="letters.length === 0"
      state="empty"
      :title="t('postEvent.letters.emptyTitle')"
      :message="t('postEvent.letters.emptyMessage')"
    />

    <ul
      v-else
      class="letter-list"
    >
      <li
        v-for="letter in letters"
        :key="letter.id"
      >
        <VCard>
          <div class="letter-list__row">
            <div>
              <RouterLink
                class="letter-list__link"
                :to="`/${locale}/account/result-letters/${letter.id}`"
              >
                {{ t(`postEvent.letters.outcome.${letter.outcome}`) }}
              </RouterLink>
              <p class="letter-list__meta">
                {{
                  letter.published_at
                    ? t("postEvent.letters.publishedAt", {
                      time: d(new Date(letter.published_at), "long")
                    })
                    : ""
                }}
              </p>
            </div>
            <VChip
              :tone="letter.read_at ? toneFor[letter.outcome] : 'warning'"
              :label="
                letter.read_at ? t('postEvent.letters.read') : t('postEvent.letters.unread')
              "
            />
          </div>
        </VCard>
      </li>
    </ul>
  </UserPageLayout>
</template>

<style scoped>
.letter-list {
  display: grid;
  gap: var(--vav-space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.letter-list__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--vav-space-4);
}

.letter-list__link {
  font-weight: var(--vav-font-weight-medium);
  color: var(--vav-color-text-primary);
}

.letter-list__meta {
  margin: var(--vav-space-1) 0 0;
  color: var(--vav-color-text-secondary);
}
</style>
