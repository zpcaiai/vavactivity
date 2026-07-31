import "@vav/design-tokens/tokens.css";
import "element-plus/dist/index.css";
import "./assets/main.css";

import {
  ElAlert,
  ElButton,
  ElDialog,
  ElIcon,
  ElInput,
  ElLoading,
  ElMenu,
  ElMenuItem,
  ElOption,
  ElPagination,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag
} from "element-plus";
import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import { permission } from "./directives/permission";
import { router } from "./router";

const app = createApp(App);
app.use(createPinia());
app.use(router);
[
  ElAlert,
  ElButton,
  ElDialog,
  ElIcon,
  ElInput,
  ElMenu,
  ElMenuItem,
  ElOption,
  ElPagination,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag
].forEach((component) => app.component(component.name ?? "", component));
app.directive("loading", ElLoading.directive);
app.directive("permission", permission);
app.mount("#app");
