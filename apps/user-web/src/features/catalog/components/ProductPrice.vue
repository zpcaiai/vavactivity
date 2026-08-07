<script setup lang="ts">
const props = defineProps<{
  amountMinor: number;
  currency: string;
  exponent?: number;
}>();

function format() {
  const exponent = props.exponent ?? (props.currency === "TWD" ? 0 : 2);
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: props.currency,
    minimumFractionDigits: exponent,
    maximumFractionDigits: exponent
  }).format(props.amountMinor / 10 ** exponent);
}
</script>

<template>
  <span class="product-price">{{ format() }}</span>
</template>
