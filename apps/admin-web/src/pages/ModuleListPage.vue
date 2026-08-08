<script setup lang="ts">
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { useRoute } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import FilterBar from "@/components/FilterBar.vue";
import PaginationBar from "@/components/PaginationBar.vue";

const route = useRoute();
const query = ref("");
const page = ref(1);
const pageSize = ref(20);
const title = computed(() => String(route.meta.title));
const description = computed(() => String(route.meta.description));
const columns = [
  { key: "id", label: "编号", width: "180" },
  { key: "name", label: "名称" },
  { key: "status", label: "状态", width: "140" },
  { key: "updatedAt", label: "更新时间", width: "180" }
];
const rows: Array<Record<string, unknown>> = [];

function search(value: string) {
  query.value = value;
  ElMessage.info(
    value ? `已准备查询“${value}”；数据 API 将在对应业务批次接入。` : "请输入查询条件"
  );
}
</script>

<template>
  <section class="module-page">
    <div class="module-intro">
      <div>
        <p class="admin-kicker">
          MODULE FOUNDATION
        </p>
        <h2>{{ title }}</h2>
        <p>{{ description }}</p>
      </div>
      <el-tag
        type="info"
        effect="plain"
      >
        NOT ENABLED
      </el-tag>
    </div>

    <div class="table-panel">
      <FilterBar
        @search="search"
        @reset="query = ''"
      >
        <el-select
          placeholder="全部状态"
          aria-label="状态筛选"
          style="width: 160px"
        >
          <el-option
            label="全部状态"
            value=""
          />
        </el-select>
      </FilterBar>
      <DataTable
        :columns="columns"
        :rows="rows"
      />
      <PaginationBar
        v-model:page="page"
        v-model:page-size="pageSize"
        :total="0"
      />
    </div>
  </section>
</template>
