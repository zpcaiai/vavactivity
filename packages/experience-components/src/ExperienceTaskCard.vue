<script setup lang="ts">defineProps<{ title: string; description: string; state: string; href: string }>();</script>
<template><article><p>{{ state }}</p><h2>{{ title }}</h2><p>{{ description }}</p><a :href="href">继续或查看状态</a></article></template>
