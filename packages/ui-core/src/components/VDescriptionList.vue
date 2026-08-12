<script setup lang="ts">
export interface VDescriptionItem {
  term: string;
  value: string;
  hint?: string;
}

withDefaults(defineProps<{ items: VDescriptionItem[]; columns?: 1 | 2 }>(), { columns: 2 });
</script>

<template>
  <dl
    class="v-description-list"
    :data-columns="columns"
  >
    <div
      v-for="item in items"
      :key="item.term"
    >
      <dt>{{ item.term }}</dt>
      <dd>
        {{ item.value }}
        <small v-if="item.hint">{{ item.hint }}</small>
      </dd>
    </div>
  </dl>
</template>
