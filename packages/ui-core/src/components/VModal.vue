<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from "vue";
const props = defineProps<{ open: boolean; title: string; closeLabel?: string; dangerous?: boolean }>();
const emit = defineEmits<{ close: []; confirm: [] }>();
const panel = ref<HTMLElement | null>(null);
let returnTarget: HTMLElement | null = null;
function close() { emit("close"); }
function keydown(event: KeyboardEvent) {
  if (event.key === "Escape") close();
  if (event.key !== "Tab" || !panel.value) return;
  const items = Array.from(panel.value.querySelectorAll<HTMLElement>("button,[href],input,select,textarea,[tabindex]:not([tabindex='-1'])")).filter((item) => !item.hasAttribute("disabled"));
  if (!items.length) return;
  const first = items[0]; const last = items.at(-1)!;
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}
watch(() => props.open, async (open) => { if (open) { returnTarget = document.activeElement as HTMLElement | null; await nextTick(); panel.value?.querySelector<HTMLElement>("button,[href],input,select,textarea,[tabindex]:not([tabindex='-1'])")?.focus(); } else returnTarget?.focus(); });
onBeforeUnmount(() => returnTarget?.focus());
</script>

<template><Teleport to="body"><div v-if="open" class="v-modal-backdrop"><section ref="panel" class="v-modal" role="dialog" aria-modal="true" :aria-labelledby="`${$attrs.id ?? 'v-modal'}-title`" @keydown="keydown"><header><h2 :id="`${$attrs.id ?? 'v-modal'}-title`">{{ title }}</h2><button type="button" :aria-label="closeLabel ?? '关闭对话框'" @click="close">×</button></header><div><slot /></div><footer><button type="button" @click="close">取消</button><button type="button" :class="{ danger: dangerous }" @click="$emit('confirm')"><slot name="confirm">确认</slot></button></footer></section></div></Teleport></template>
