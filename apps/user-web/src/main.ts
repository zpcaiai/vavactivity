import "@vav/design-tokens/tokens.css";
import "./assets/main.css";

import { VueQueryPlugin } from "@tanstack/vue-query";
import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import { apiPlugin } from "./api/plugin";
import { i18n } from "./i18n";
import { router } from "./router";

const app = createApp(App);

app.use(createPinia());
app.use(i18n);
app.use(router);
app.use(VueQueryPlugin, {
  queryClientConfig: {
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: 1,
        refetchOnWindowFocus: false
      }
    }
  }
});
app.use(apiPlugin);
app.mount("#app");

