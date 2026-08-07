<script setup lang="ts">
import { onErrorCaptured, ref } from "vue";

const failed = ref(false);

onErrorCaptured(() => {
  failed.value = true;
  return false;
});
</script>

<template>
  <section
    v-if="failed"
    class="state-panel"
    role="alert"
  >
    <span class="eyebrow">VAV</span>
    <h1>页面暂时无法显示</h1>
    <p>请刷新页面；如果问题持续发生，请稍后再试。</p>
    <button
      class="primary-button"
      type="button"
      @click="failed = false"
    >
      重试
    </button>
  </section>
  <slot v-else />
</template>

