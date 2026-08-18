<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ data: Record<string, unknown> }>();

/**
 * The API stores rich text as a ProseMirror document. The previous
 * implementation collected *every* string in that tree, so the node type names
 * came out as content: a one-paragraph document rendered as
 * "doc" / "paragraph" / "text" / the actual sentence. Only `text` nodes carry
 * text; everything else is structure.
 */
interface RichNode {
  type?: string;
  text?: string;
  content?: RichNode[];
}

function textOf(node: RichNode): string {
  if (typeof node?.text === "string" && (node.type === "text" || node.type === undefined)) {
    return node.text;
  }
  return (node?.content ?? []).map(textOf).join("");
}

const HEADINGS = new Set(["heading", "title"]);

const blocks = computed(() => {
  const document = props.data.document;
  if (typeof document === "string") {
    return document.trim() ? [{ heading: false, text: document }] : [];
  }
  const root = document as RichNode | RichNode[] | undefined;
  const nodes = Array.isArray(root) ? root : root?.content ?? (root ? [root] : []);
  return nodes
    .map((node) => ({ heading: HEADINGS.has(node?.type ?? ""), text: textOf(node).trim() }))
    .filter((block) => block.text.length > 0);
});
</script>

<template>
  <div class="cms-rich-text">
    <template
      v-for="(block, index) in blocks"
      :key="index"
    >
      <h3 v-if="block.heading">
        {{ block.text }}
      </h3>
      <p v-else>
        {{ block.text }}
      </p>
    </template>
  </div>
</template>
