import "@vav/design-tokens/tokens.css";
import "@vav/ui-core/styles.css";
import "element-plus/dist/index.css";
import "./assets/main.css";

import {
  ElAlert,
  ElButton,
  ElDatePicker,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElLoading,
  ElMenu,
  ElMenuItem,
  ElOption,
  ElPagination,
  ElSelect,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag
} from "element-plus";
import { createPinia } from "pinia";
import { createApp } from "vue";
import { applyUiPreferences } from "@vav/ui-core";

import App from "./App.vue";
import { permission } from "./directives/permission";
import { router } from "./router";

const app = createApp(App);
applyUiPreferences(document.documentElement, "light", "compact");
app.use(createPinia());
app.use(router);
[
  ElAlert,
  ElButton,
  ElDatePicker,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElMenu,
  ElMenuItem,
  ElOption,
  ElPagination,
  ElSelect,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag
].forEach((component) => app.component(component.name ?? "", component));
app.directive("loading", ElLoading.directive);
app.directive("permission", permission);
app.mount("#app");
