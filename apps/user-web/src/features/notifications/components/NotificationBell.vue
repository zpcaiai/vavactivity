<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { notificationApi } from "../api";

const route = useRoute();
const count = ref(0);
let timer: number | undefined;

async function refresh() {
  try {
    count.value = (await notificationApi.unread()).count;
  } catch {
    count.value = 0;
  }
}

onMounted(() => {
  void refresh();
  timer = window.setInterval(() => void refresh(), 30_000);
});
onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer);
});
</script>

<template>
  <RouterLink
    class="notification-bell"
    :to="`/${String(route.params.locale ?? 'zh-CN')}/account/notifications`"
    aria-label="Notifications"
  >
    <span aria-hidden="true">🔔</span>
    <span
      v-if="count"
      class="notification-badge"
    >{{ count > 99 ? "99+" : count }}</span>
  </RouterLink>
</template>
