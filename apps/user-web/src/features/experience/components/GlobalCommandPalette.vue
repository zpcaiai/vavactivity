<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { experienceApi, type ExperienceRow } from "@/features/experience/api";
import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const auth = useAuthStore();
const dialog = ref<HTMLDialogElement>();
const input = ref<HTMLInputElement>();
const query = ref("");
const results = ref<ExperienceRow[]>([]);
const busy = ref(false);

function keyHandler(event: KeyboardEvent) {
  const target = event.target as HTMLElement | null;
  if (event.key === "/" && !target?.matches("input,textarea,[contenteditable=true]")) {
    event.preventDefault();
    open();
  }
}

async function open() {
  dialog.value?.showModal();
  await nextTick();
  input.value?.focus();
}

async function search() {
  busy.value = true;
  try {
    results.value = query.value.trim()
      ? await experienceApi.search(query.value, Boolean(auth.user))
      : [];
  } finally {
    busy.value = false;
  }
}

function destination(row: ExperienceRow) {
  return String(row.route_path ?? `/${String(route.params.locale ?? "zh-CN")}/search`)
    .replace("{locale}", String(route.params.locale ?? "zh-CN"));
}

function close() {
  dialog.value?.close();
}

onMounted(() => window.addEventListener("keydown", keyHandler));
onBeforeUnmount(() => window.removeEventListener("keydown", keyHandler));
</script>

<template>
  <button
    class="palette-trigger"
    type="button"
    aria-keyshortcuts="/"
    @click="open"
  >
    搜索 <kbd>/</kbd>
  </button>
  <dialog
    ref="dialog"
    aria-labelledby="palette-title"
    @close="results = []"
  >
    <form
      method="dialog"
      class="dialog-close"
    >
      <button
        type="submit"
        aria-label="关闭搜索"
      >
        ×
      </button>
    </form>
    <h2 id="palette-title">
      全站搜索与快捷导航
    </h2>
    <form
      role="search"
      @submit.prevent="search"
    >
      <label for="palette-query">输入内容、服务、任务或帮助</label><div>
        <input
          id="palette-query"
          ref="input"
          v-model="query"
          maxlength="200"
          autocomplete="off"
        ><button
          type="submit"
          :disabled="busy"
        >
          {{ busy ? '搜索中' : '搜索' }}
        </button>
      </div>
    </form>
    <ul aria-live="polite">
      <li
        v-for="row in results"
        :key="String(row.id ?? row.document_code)"
      >
        <RouterLink
          :to="destination(row)"
          @click="close"
        >
          {{ row.title ?? row.document_code }}
        </RouterLink><small>{{ row.summary }}</small>
      </li>
    </ul>
    <p v-if="!busy && query && results.length === 0">
      没有可见结果。权限、隐私和安全过滤始终在后端执行。
    </p>
  </dialog>
</template>

<style scoped>.palette-trigger{min-height:var(--vav-control-min-height);border:1px solid var(--vav-color-border);border-radius:var(--vav-radius-pill);background:var(--vav-color-surface-raised);color:var(--vav-color-text);padding-inline:var(--vav-space-3)}kbd{font:inherit;border:1px solid var(--vav-color-border);border-radius:var(--vav-radius-sm);padding-inline:.3em}dialog{width:min(42rem,calc(100% - 2rem));max-height:80vh;border:1px solid var(--vav-color-border);border-radius:var(--vav-radius-lg);background:var(--vav-color-surface-raised);color:var(--vav-color-text);padding:var(--vav-space-5)}dialog::backdrop{background:rgb(0 0 0 / .55)}form{display:grid;gap:var(--vav-space-2)}form div{display:grid;grid-template-columns:1fr auto;gap:var(--vav-space-2)}input,button{min-height:var(--vav-control-min-height)}input{border:1px solid var(--vav-color-border);border-radius:var(--vav-radius-md);padding-inline:var(--vav-space-3)}.dialog-close{display:flex;justify-content:end}.dialog-close button{border:0;background:transparent;color:inherit;font-size:1.5rem}ul{display:grid;gap:var(--vav-space-2);list-style:none;padding:0}li{display:grid;padding:var(--vav-space-2);border-bottom:1px solid var(--vav-color-border)}</style>
