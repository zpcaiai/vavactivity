<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ status: 403 | 404 | 500 }>();
const content = computed(() => {
  if (props.status === 403) {
    return { title: "没有访问权限", body: "当前账户没有执行此操作所需的服务端权限。" };
  }
  if (props.status === 500) {
    return { title: "服务暂时不可用", body: "错误已进入结构化日志，请稍后再试。" };
  }
  return { title: "页面不存在", body: "该运营页面可能已移动或尚未开放。" };
});
</script>

<template>
  <main class="admin-error-page">
    <span>{{ status }}</span>
    <h1>{{ content.title }}</h1>
    <p>{{ content.body }}</p>
    <RouterLink to="/admin/dashboard">
      返回工作台
    </RouterLink>
  </main>
</template>

