<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  expiresAt?: string | null;
  availableFrom?: string | null;
  status?: string;
}>();

function formatMoment(value?: string | null) {
  if (!value) return "";
  const moment = new Date(value);
  if (Number.isNaN(moment.getTime())) return "";
  return moment.toLocaleString("zh-CN", { dateStyle: "medium", timeStyle: "short" });
}

const expiresText = computed(() => formatMoment(props.expiresAt));
const availableText = computed(() => formatMoment(props.availableFrom));
</script>

<template>
  <p class="exposure-notice">
    <span v-if="availableText">推荐时间 {{ availableText }}</span>
    <span v-if="expiresText">· 有效期至 {{ expiresText }}</span>
    <span>· 浏览记录只用于控制曝光次数和推荐质量，对方不会收到你查看过的通知。</span>
  </p>
</template>

<style scoped>
.exposure-notice { display: flex; flex-wrap: wrap; gap: 0.35rem; font-size: 0.78rem; opacity: 0.7; line-height: 1.6; margin: 0; }
</style>
