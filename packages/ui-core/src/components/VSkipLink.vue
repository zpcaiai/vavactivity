<script setup lang="ts">withDefaults(defineProps<{ target?: string }>(), { target: "main-content" });</script>
<template><a class="v-skip-link" :href="`#${target}`"><slot>跳到主要内容</slot></a></template>
