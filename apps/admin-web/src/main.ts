import "@vav/design-tokens/tokens.css";
import "element-plus/dist/index.css";
import "./assets/main.css";

import ElementPlus from "element-plus";
import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import { permission } from "./directives/permission";
import { router } from "./router";

const app = createApp(App);
app.use(createPinia());
app.use(ElementPlus);
app.use(router);
app.directive("permission", permission);
app.mount("#app");

