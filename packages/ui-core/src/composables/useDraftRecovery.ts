import { readonly, ref } from "vue";

export function useDraftRecovery<T>(key: string, initial: T, storage: Storage = localStorage) {
  const draft = ref<T>(initial);
  const status = ref<"pristine" | "editing" | "saved" | "failed" | "recovered">("pristine");

  function recover() {
    const raw = storage.getItem(key);
    if (!raw) return false;
    try {
      draft.value = JSON.parse(raw) as T;
      status.value = "recovered";
      return true;
    } catch {
      storage.removeItem(key);
      return false;
    }
  }

  function save(value: T) {
    draft.value = value;
    status.value = "editing";
    try {
      storage.setItem(key, JSON.stringify(value));
      status.value = "saved";
      return true;
    } catch {
      status.value = "failed";
      return false;
    }
  }

  function clear() {
    storage.removeItem(key);
    draft.value = initial;
    status.value = "pristine";
  }

  return { draft, status: readonly(status), recover, save, clear };
}
