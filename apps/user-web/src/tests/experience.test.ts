import { beforeEach, describe, expect, it, vi } from "vitest";

const bootstrap = vi.fn(async () => undefined);
vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({ bootstrap, accessToken: "member-token", user: { id: "member" } })
}));

import { experienceApi } from "@/features/experience/api";

describe("experience API", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ ok: true, status: 200, json: async () => ({ data: url.includes("/tasks") ? [] : { items: [] } }) })));
  });

  it("uses the backend-owned task projection", async () => {
    await expect(experienceApi.tasks()).resolves.toEqual([]);
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/experience/tasks?include_history=false"), expect.objectContaining({ credentials: "include" }));
  });

  it("keeps anonymous search on the public filtered endpoint", async () => {
    await experienceApi.search("活动", false);
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/public/experience/search?q="), expect.any(Object));
  });
});
