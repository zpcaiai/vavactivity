<script setup lang="ts">defineProps<{ label?: string }>();</script>
<template><aside class="v-sticky-actions" :aria-label="label ?? '页面操作'"><slot /></aside></template>
<style scoped>.v-sticky-actions{position:sticky;bottom:0;z-index:10;display:flex;gap:var(--vav-space-3);padding:var(--vav-space-3);padding-bottom:calc(var(--vav-space-3) + var(--vav-layout-safe-area-bottom));background:var(--vav-color-surface-raised);border-top:1px solid var(--vav-color-border)}@media(max-width:48rem){.v-sticky-actions{display:grid;grid-template-columns:1fr}}</style>
