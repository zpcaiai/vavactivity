<script setup lang="ts">
import type { CatalogCurrency } from "../composables/useCurrency";

defineProps<{
  modelValue: CatalogCurrency;
  currencies: readonly CatalogCurrency[];
}>();

const emit = defineEmits<{
  "update:modelValue": [value: CatalogCurrency];
}>();
</script>

<template>
  <label class="currency-selector">
    <span>币种</span>
    <select
      :value="modelValue"
      @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value as CatalogCurrency)"
    >
      <option
        v-for="item in currencies"
        :key="item"
        :value="item"
      >
        {{ item }}
      </option>
    </select>
  </label>
</template>
