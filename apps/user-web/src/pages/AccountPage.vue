<script setup lang="ts">
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const { t } = useI18n();
const { isAuthenticated, accountName } = storeToRefs(useAuthStore());
const locale = computed(() => String(route.params.locale));
</script>

<template>
  <section class="account-page">
    <p class="eyebrow">
      VAV ACCOUNT
    </p>
    <h1>{{ t("account.title") }}</h1>
    <p v-if="isAuthenticated">
      {{ accountName }}
    </p>
    <nav
      v-if="isAuthenticated"
      class="commerce-actions"
      aria-label="账户功能"
    >
      <RouterLink
        class="primary-button"
        :to="`/${locale}/account/courses`"
      >
        我的课程
      </RouterLink>
      <RouterLink :to="`/${locale}/account/orders`">
        我的订单
      </RouterLink>
      <RouterLink :to="`/${locale}/account/privacy`">
        隐私与数据中心
      </RouterLink>
      <RouterLink :to="`/${locale}/account/matchmaking/matches`">
        互选与认识邀请
      </RouterLink>
    </nav>
    <EmptyState
      v-else
      :title="t('account.title')"
      :description="t('account.signedOut')"
    >
      <RouterLink
        class="primary-button"
        :to="`/${locale}/login`"
      >
        {{ t("account.login") }}
      </RouterLink>
    </EmptyState>
  </section>
</template>
