import { watchEffect } from "vue";
import type { Ref } from "vue";

export interface SeoMeta {
  title: string;
  description: string;
}

export function useSeo(meta: Ref<SeoMeta>) {
  watchEffect(() => {
    document.title = `${meta.value.title} · VAV`;
    let description = document.querySelector<HTMLMetaElement>('meta[name="description"]');
    if (!description) {
      description = document.createElement("meta");
      description.name = "description";
      document.head.append(description);
    }
    description.content = meta.value.description;
  });
}

