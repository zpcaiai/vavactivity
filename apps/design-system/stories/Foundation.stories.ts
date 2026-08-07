import type { Meta, StoryObj } from "@storybook/vue3-vite";
import { defineComponent } from "vue";

const Foundation = defineComponent({ name: "FoundationTokenStory", template: '<section><h1>语义 token</h1><div class="swatches"><article><span class="swatch primary"></span><strong>主要操作</strong></article><article><span class="swatch success"></span><strong>成功</strong></article><article><span class="swatch warning"></span><strong>警告</strong></article><article><span class="swatch danger"></span><strong>危险</strong></article></div></section>' });
const meta = { title: "Foundation/Tokens", component: Foundation, tags: ["autodocs"] } satisfies Meta<typeof Foundation>;
export default meta;
export const SemanticColors: StoryObj<typeof meta> = {};
