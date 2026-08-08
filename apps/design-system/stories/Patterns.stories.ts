import type { Meta, StoryObj } from "@storybook/vue3-vite";
import { AdminDataTable } from "@vav/ui-admin";
import { VPageState } from "@vav/ui-core";
import { defineComponent } from "vue";

const Patterns = defineComponent({ name: "AdminPatternStory", components: { AdminDataTable, VPageState }, data: () => ({ rows: [{ id: "synthetic", name: "合成记录", status: "等待复核" }] }), template: '<section><h1>页面状态与数据表</h1><VPageState state="offline" title="当前离线" message="仍可查看最近同步的数据。" /><AdminDataTable caption="合成记录" :columns="[{key:\'name\',label:\'名称\',priority:\'primary\'},{key:\'status\',label:\'状态\'}]" :rows="rows" row-key="id" /></section>' });
const meta = { title: "Patterns/Admin and States", component: Patterns, tags: ["autodocs"] } satisfies Meta<typeof Patterns>;
export default meta;
export const Responsive: StoryObj<typeof meta> = {};
