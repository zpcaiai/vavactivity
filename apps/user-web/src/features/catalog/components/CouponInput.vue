<script setup lang="ts">
defineProps<{
  modelValue: string;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: string];
  apply: [];
}>();
</script>

<template>
  <div class="coupon-input">
    <label>
      <span>优惠码</span>
      <input
        :value="modelValue"
        :disabled="disabled"
        autocomplete="off"
        placeholder="如有优惠码，请在此输入"
        @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      >
    </label>
    <button
      type="button"
      :disabled="disabled || !modelValue.trim()"
      @click="emit('apply')"
    >
      应用
    </button>
  </div>
</template>
