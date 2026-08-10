import { describe, expect, it } from "vitest";

import { buildCommerceApiUrl } from "./api";

describe("commerce API URL resolution", () => {
  it("resolves the same-origin fallback API base", () => {
    expect(
      buildCommerceApiUrl("/api/v1", "/cart", "http://localhost:5173").toString()
    ).toBe("http://localhost:5173/api/v1/cart");
  });

  it("preserves an explicitly configured absolute API base", () => {
    expect(
      buildCommerceApiUrl(
        "https://api.example.com/api/v1",
        "/cart/items",
        "https://app.example.com"
      ).toString()
    ).toBe("https://api.example.com/api/v1/cart/items");
  });
});
