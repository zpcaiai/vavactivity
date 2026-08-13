<script setup lang="ts">
import { VCard, VPageState } from "@vav/ui-core";
import { UserPageLayout } from "@vav/ui-user";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { postEventApiClient } from "@/features/post-event/api";
import type { ResultLetterDetail } from "@/features/post-event/types";

const route = useRoute();
const { t, d } = useI18n();

const letter = ref<ResultLetterDetail | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const errorCode = ref<string | null>(null);

const letterId = computed(() => String(route.params.letterId ?? ""));

/**
 * An unpublished or revoked letter is indistinguishable from a missing one by
 * design — the server filters on status inside the WHERE clause, so there is
 * no state here that leaks "it exists but you may not read it".
 */
const notFound = computed(() => errorCode.value === "LETTER_NOT_FOUND");

/** Paragraphs, not v-html: the body is member-facing text, never markup. */
const paragraphs = computed(() =>
  (letter.value?.body ?? "")
    .split(/\n{2,}/u)
    .map((block) => block.trim())
    .filter(Boolean)
);

async function load() {
  loading.value = true;
  error.value = null;
  errorCode.value = null;
  try {
    letter.value = await postEventApiClient.resultLetter(letterId.value);
  } catch (caught) {
    error.value = (caught as Error).message;
    errorCode.value = (caught as Error & { code?: string }).code ?? null;
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <UserPageLayout
    :title="letter?.subject ?? t('postEvent.letters.detailTitle')"
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
      v-else-if="notFound"
      state="empty"
      :title="t('postEvent.letters.notFoundTitle')"
      :message="t('postEvent.letters.notFoundMessage')"
    />

    <VPageState
      v-else-if="error"
      state="error"
      :title="t('common.errorTitle')"
      :message="error"
      @action="load"
    />

    <VCard v-else-if="letter">
      <p
        v-if="letter.published_at"
        class="letter__meta"
      >
        {{
          t("postEvent.letters.publishedAt", { time: d(new Date(letter.published_at), "long") })
        }}
      </p>
      <p
        v-for="(paragraph, index) in paragraphs"
        :key="index"
        class="letter__paragraph"
      >
        {{ paragraph }}
      </p>
    </VCard>
  </UserPageLayout>
</template>

<style scoped>
.letter__meta {
  margin: 0 0 var(--vav-space-4);
  color: var(--vav-color-text-secondary);
}

.letter__paragraph {
  margin: 0 0 var(--vav-space-4);
  line-height: var(--vav-line-height-relaxed, 1.7);
  white-space: pre-line;
}
</style>
