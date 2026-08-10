<script setup lang="ts">
import type { CatalogSku } from "../types";

defineProps<{
  modelValue: string;
  skus: CatalogSku[];
}>();

const emit = defineEmits<{
  "update:modelValue": [value: string];
}>();
</script>

<template>
  <fieldset class="sku-selector">
    <legend>选择方案</legend>
    <label
      v-for="sku in skus"
      :key="sku.id"
      :class="{ selected: sku.id === modelValue }"
    >
      <input
        type="radio"
        name="sku"
        :value="sku.id"
        :checked="sku.id === modelValue"
        @change="emit('update:modelValue', sku.id)"
      >
      <span>
        <strong>{{ sku.sku_code }}</strong>
        <small v-if="sku.service_quantity">
          {{ sku.service_quantity }} {{ sku.service_unit }}
        </small>
      </span>
    </label>
  </fieldset>
</template>
