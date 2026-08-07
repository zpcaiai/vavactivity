import { describe, expect, it } from "vitest";
import AdminPlatformPage from "@/pages/AdminPlatformPage.vue";
import { adminPlatformSectionPermissions } from "@/router";

describe("Batch 26 administration platform", () => {
  it("registers all governed console sections", () => {
    expect(Object.keys(adminPlatformSectionPermissions)).toHaveLength(13);
    expect(AdminPlatformPage).toBeTruthy();
  });
});
