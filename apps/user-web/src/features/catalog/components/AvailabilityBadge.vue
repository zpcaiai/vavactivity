<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  status: string;
  quantity: number | null;
}>();

const label = computed(() => {
  if (props.status === "sold_out") {
    return "名额已满";
  }
  if (props.status === "low_stock") {
    return props.quantity === null ? "名额有限" : `仅余 ${props.quantity}`;
  }
  return "可购买";
});
</script>

<template>
  <span :class="['availability-badge', status]">{{ label }}</span>
</template>
