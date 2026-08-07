import type { ObjectDirective } from "vue";

import { useAccessStore } from "@/stores/access";

export const permission: ObjectDirective<HTMLElement, string | string[]> = {
  mounted(element, binding) {
    if (!useAccessStore().hasPermission(binding.value)) {
      element.remove();
    }
  },
  updated(element, binding) {
    if (!useAccessStore().hasPermission(binding.value)) {
      element.remove();
    }
  }
};
