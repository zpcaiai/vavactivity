import { describe, expect, it } from "vitest";
import { useAsyncValidation } from "../src/composables/useAsyncValidation";
import { useDraftRecovery } from "../src/composables/useDraftRecovery";

describe("form workflow utilities", () => {
  it("cancels stale async validation", async () => {
    const pending: Array<(value: string | null) => void> = [];
    const validator = useAsyncValidation<string>((_value, signal) => new Promise((resolve) => { signal.addEventListener("abort", () => resolve(null)); pending.push(resolve); }));
    const first = validator.validate("old");
    const second = validator.validate("new");
    pending.at(-1)?.("new error");
    await Promise.all([first, second]);
    expect(validator.error.value).toBe("new error");
  });

  it("recovers and clears local drafts", () => {
    const storage = new Map<string, string>();
    const adapter = { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => void storage.set(key, value), removeItem: (key: string) => void storage.delete(key), clear: () => storage.clear(), key: () => null, get length() { return storage.size; } } as Storage;
    const draft = useDraftRecovery("form", { value: "" }, adapter);
    expect(draft.save({ value: "kept" })).toBe(true);
    draft.draft.value = { value: "" };
    expect(draft.recover()).toBe(true);
    expect(draft.draft.value).toEqual({ value: "kept" });
    draft.clear();
    expect(storage.size).toBe(0);
  });
});
