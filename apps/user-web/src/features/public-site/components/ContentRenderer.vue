<script setup lang="ts">
import type { Component } from "vue";

import CallToActionBlock from "./CallToActionBlock.vue";
import CollectionBlock from "./CollectionBlock.vue";
import HeroBlock from "./HeroBlock.vue";
import ImageBlock from "./ImageBlock.vue";
import QuoteBlock from "./QuoteBlock.vue";
import RichTextBlock from "./RichTextBlock.vue";
import type { ContentBlock } from "../types";

defineProps<{ blocks: ContentBlock[]; preview?: boolean }>();

const blockRegistry: Record<string, Component> = {
  hero: HeroBlock,
  rich_text: RichTextBlock,
  image: ImageBlock,
  quote: QuoteBlock,
  call_to_action: CallToActionBlock,
  feature_grid: CollectionBlock,
  article_list: CollectionBlock,
  story_list: CollectionBlock,
  activity_list: CollectionBlock,
  course_list: CollectionBlock,
  counseling_list: CollectionBlock,
  faq: CollectionBlock,
  divider: CollectionBlock
};
</script>

<template>
  <template
    v-for="block in blocks"
    :key="block.id"
  >
    <component
      :is="blockRegistry[block.type]"
      v-if="blockRegistry[block.type]"
      :data="block.data"
      :type="block.type"
    />
    <div
      v-else-if="preview"
      class="unsupported-block"
      role="alert"
    >
      Unsupported block: {{ block.type }}
    </div>
  </template>
</template>
