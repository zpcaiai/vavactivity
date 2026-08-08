<script setup lang="ts">
defineProps<{ page: number; pageSize: number; total: number }>();
const emit = defineEmits<{
  "update:page": [page: number];
  "update:pageSize": [pageSize: number];
}>();
</script>

<template>
  <div class="pagination-bar">
    <span>共 {{ total }} 条</span>
    <el-pagination
      background
      layout="sizes, prev, pager, next"
      :current-page="page"
      :page-size="pageSize"
      :page-sizes="[20, 50, 100]"
      :total="total"
      @update:current-page="emit('update:page', $event)"
      @update:page-size="emit('update:pageSize', $event)"
    />
  </div>
</template>
