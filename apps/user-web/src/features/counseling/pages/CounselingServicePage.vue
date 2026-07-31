<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { counselingApi, type CounselingService } from "../api";

const route = useRoute();
const service = ref<CounselingService>();
const error = ref("");

onMounted(async () => {
  try {
    service.value = await counselingApi.service(
      String(route.params.slug),
      String(route.params.locale)
    );
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "咨询服务加载失败";
  }
});
</script>

<template>
  <section class="content-page counseling-detail">
    <p
      v-if="error"
      class="form-error"
      role="alert"
    >
      {{ error }}
    </p>
    <template v-if="service">
      <p class="eyebrow">
        VAV HUMAN SUPPORT
      </p>
      <h1>{{ service.name }}</h1>
      <p>{{ service.summary }}</p>
      <p>{{ service.delivery_mode }} · {{ service.duration_minutes }} 分钟</p>
      <div
        v-for="(block, index) in service.description_blocks"
        :key="index"
      >
        <p>{{ block.text }}</p>
      </div>
      <aside
        class="scope-notice"
        data-testid="counseling-scope-notice"
      >
        <strong>服务边界</strong>
        <p>{{ service.scope_notice }}</p>
      </aside>
      <RouterLink
        class="primary-button"
        :to="`/${String(route.params.locale)}/counseling/${service.slug}/book`"
      >
        选择预约时间
      </RouterLink>
    </template>
  </section>
</template>
