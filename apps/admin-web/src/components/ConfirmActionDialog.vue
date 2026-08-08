<script setup lang="ts">
defineProps<{
  modelValue: boolean;
  title: string;
  description: string;
  destructive?: boolean;
}>();
const emit = defineEmits<{
  "update:modelValue": [value: boolean];
  confirm: [];
}>();
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="480px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <p>{{ description }}</p>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">
        取消
      </el-button>
      <el-button
        :type="destructive ? 'danger' : 'primary'"
        @click="emit('confirm'); emit('update:modelValue', false)"
      >
        确认
      </el-button>
    </template>
  </el-dialog>
</template>
