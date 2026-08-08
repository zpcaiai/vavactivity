<script setup lang="ts">
import { ref, watch } from "vue";

const props = defineProps<{
  modelValue: boolean;
  actionLabel: string;
}>();
const emit = defineEmits<{
  "update:modelValue": [value: boolean];
  confirm: [reason: string];
}>();
const reason = ref("");

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) reason.value = "";
  }
);

function confirm() {
  if (reason.value.trim().length < 5) return;
  emit("confirm", reason.value.trim());
  emit("update:modelValue", false);
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="`${actionLabel} · 审计原因`"
    width="520px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <p class="dialog-guidance">
      原因会进入只追加的审计记录，请写明事实与处理依据。
    </p>
    <el-input
      v-model="reason"
      type="textarea"
      :rows="4"
      minlength="5"
      maxlength="500"
      show-word-limit
      placeholder="至少 5 个字"
      aria-label="审计原因"
    />
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">
        取消
      </el-button>
      <el-button
        type="primary"
        :disabled="reason.trim().length < 5"
        @click="confirm"
      >
        确认并记录
      </el-button>
    </template>
  </el-dialog>
</template>
