<script setup lang="ts">
import { ref } from "vue";

import AuditReasonDialog from "./AuditReasonDialog.vue";

defineProps<{ permission: string; label?: string }>();
const emit = defineEmits<{ confirm: [reason: string] }>();
const visible = ref(false);
</script>

<template>
  <span v-permission="permission">
    <el-button
      type="primary"
      plain
      @click="visible = true"
    >
      {{ label ?? "审核" }}
    </el-button>
    <AuditReasonDialog
      v-model="visible"
      :action-label="label ?? '审核'"
      @confirm="emit('confirm', $event)"
    />
  </span>
</template>
