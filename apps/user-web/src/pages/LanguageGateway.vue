<script setup lang="ts">
const languages = [
  { code: "zh-CN", label: "简体中文", promise: "认真认识，安心同行" },
  { code: "zh-TW", label: "繁體中文", promise: "認真認識，安心同行" },
  { code: "en", label: "English", promise: "Meet thoughtfully. Walk forward safely." }
] as const;
</script>

<template>
  <main
    id="main-content"
    class="language-gateway"
    tabindex="-1"
  >
    <div class="gateway-card">
      <span
        class="brand-mark gateway-mark"
        aria-hidden="true"
      >V</span>
      <p class="eyebrow">
        VAV relationship services
      </p>
      <h1>Choose your language<br>选择你的语言</h1>
      <p class="gateway-note">
        正式首发语言尚待业务确认；这里仅提供已经建立的界面语言能力。
      </p>
      <div class="language-grid">
        <RouterLink
          v-for="language in languages"
          :key="language.code"
          :to="`/${language.code}/`"
          class="language-card"
        >
          <strong>{{ language.label }}</strong>
          <span>{{ language.promise }}</span>
          <span aria-hidden="true">→</span>
        </RouterLink>
      </div>
    </div>
  </main>
</template>
