<script setup lang="ts">
export interface TableColumn {
  key: string;
  label: string;
  width?: string;
}

defineProps<{
  columns: TableColumn[];
  rows: Array<Record<string, unknown>>;
  loading?: boolean;
}>();
</script>

<template>
  <el-table
    v-loading="loading"
    :data="rows"
    empty-text="当前没有可显示的数据"
  >
    <el-table-column
      v-for="column in columns"
      :key="column.key"
      :prop="column.key"
      :label="column.label"
      :width="column.width"
    />
    <slot />
  </el-table>
</template>

