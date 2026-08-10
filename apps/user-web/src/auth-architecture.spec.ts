import { describe, expect, it } from "vitest";

import authStoreSource from "./stores/auth.ts?raw";

describe("authentication architecture", () => {
  it("uses the governed FastAPI identity boundary exclusively", () => {
    expect(authStoreSource).not.toContain("@neondatabase/neon-js");
    expect(authStoreSource).not.toContain("VITE_NEON_AUTH_URL");
    expect(authStoreSource).toContain('authRequest<AuthResponse>("/auth/login"');
    expect(authStoreSource).toContain('authRequest<AuthResponse>("/auth/refresh"');
  });
});
