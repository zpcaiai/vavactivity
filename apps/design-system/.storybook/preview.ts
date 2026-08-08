import type { Preview } from "@storybook/vue3-vite";
import "@vav/design-tokens/tokens.css";
import "@vav/ui-core/styles.css";
import "../src/catalog.css";

const preview: Preview = {
  parameters: {
    a11y: { test: "error" },
    controls: { expanded: true },
    options: { storySort: { order: ["Foundation", "Components", "Patterns"] } }
  },
  decorators: [() => ({ template: '<div class="story-surface" data-vav-theme="light" data-vav-density="comfortable"><story /></div>' })]
};

export default preview;
