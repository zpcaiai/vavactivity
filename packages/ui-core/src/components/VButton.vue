<script setup lang="ts">
withDefaults(defineProps<{ variant?: "primary" | "secondary" | "danger"; loading?: boolean; disabled?: boolean; type?: "button" | "submit" | "reset" }>(), { variant: "primary", type: "button" });
defineEmits<{ click: [event: MouseEvent] }>();
</script>

<template>
  <button class="v-button" :class="`v-button--${variant}`" :type="type" :disabled="disabled || loading" :aria-busy="loading || undefined" @click="$emit('click', $event)">
    <span v-if="loading" class="v-button__spinner" aria-hidden="true" />
    <span><slot>{{ loading ? "处理中" : "确认" }}</slot></span>
  </button>
</template>
