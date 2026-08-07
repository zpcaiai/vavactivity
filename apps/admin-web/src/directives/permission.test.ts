import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { permission } from "./permission";
import { useAccessStore } from "@/stores/access";

describe("v-permission", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("removes an element when the required permission is absent", () => {
    const element = document.createElement("button");
    document.body.append(element);
    permission.mounted?.(element, { value: "orders:refund" } as never, {} as never, {} as never);
    expect(document.body.contains(element)).toBe(false);
  });

  it("keeps an element when the required permission is present", () => {
    const access = useAccessStore();
    access.permissions = ["orders:view"];
    const element = document.createElement("button");
    document.body.append(element);
    permission.mounted?.(element, { value: "orders:view" } as never, {} as never, {} as never);
    expect(document.body.contains(element)).toBe(true);
  });
});

