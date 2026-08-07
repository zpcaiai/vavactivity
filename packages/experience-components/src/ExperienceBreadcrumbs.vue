<script setup lang="ts">defineProps<{ items: Array<{ label: string; href: string }> }>();</script>
<template><nav aria-label="面包屑"><ol><li v-for="(item,index) in items" :key="item.href"><a v-if="index < items.length - 1" :href="item.href">{{ item.label }}</a><span v-else aria-current="page">{{ item.label }}</span></li></ol></nav></template>
<style scoped>ol{display:flex;flex-wrap:wrap;gap:.5rem;list-style:none;padding:0}li:not(:last-child)::after{content:"/";margin-inline-start:.5rem}</style>
