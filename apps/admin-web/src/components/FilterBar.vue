<script setup lang="ts">
import { ref } from "vue";

const emit = defineEmits<{ search: [query: string]; reset: [] }>();
const query = ref("");

function reset() {
  query.value = "";
  emit("reset");
}
</script>

<template>
  <div class="filter-bar">
    <el-input
      v-model="query"
      clearable
      placeholder="输入编号、名称或关键词"
      aria-label="搜索关键词"
      @keyup.enter="emit('search', query)"
    />
    <slot />
    <el-button
      type="primary"
      @click="emit('search', query)"
    >
      查询
    </el-button>
    <el-button @click="reset">
      重置
    </el-button>
  </div>
</template>

