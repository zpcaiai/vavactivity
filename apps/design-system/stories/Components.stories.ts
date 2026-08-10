import type { Meta, StoryObj } from "@storybook/vue3-vite";
import { VAlert, VButton, VStatusBadge } from "@vav/ui-core";
import { defineComponent } from "vue";

const Gallery = defineComponent({ name: "FoundationComponentStory", components: { VAlert, VButton, VStatusBadge }, template: '<section><h1>基础组件</h1><div class="row"><VButton>主要操作</VButton><VButton variant="secondary">次要操作</VButton><VStatusBadge status="warning" label="需复核" /></div><VAlert title="可访问状态" tone="success">颜色之外同时提供文字和图标。</VAlert></section>' });
const meta = { title: "Components/Foundation", component: Gallery, tags: ["autodocs"] } satisfies Meta<typeof Gallery>;
export default meta;
export const Default: StoryObj<typeof meta> = {};
