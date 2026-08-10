import { readonly, ref } from "vue";

export function useAsyncValidation<T>(validator: (value: T, signal: AbortSignal) => Promise<string | null>) {
  const validating = ref(false);
  const error = ref<string | null>(null);
  let controller: AbortController | null = null;

  async function validate(value: T) {
    controller?.abort();
    controller = new AbortController();
    const current = controller;
    validating.value = true;
    try {
      const result = await validator(value, current.signal);
      if (controller === current && !current.signal.aborted) error.value = result;
      return result;
    } catch (cause) {
      if (current.signal.aborted) return null;
      throw cause;
    } finally {
      if (controller === current) validating.value = false;
    }
  }

  function cancel() {
    controller?.abort();
    controller = null;
    validating.value = false;
  }

  return { validating: readonly(validating), error: readonly(error), validate, cancel };
}
