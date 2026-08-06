import { expect, test } from "@playwright/test";

test("process operator can inspect governed instances and recovery controls", async ({ page }) => {
  await page.goto("/admin/processes/dashboard");
  await expect(page.getByRole("heading", { name: "业务流程与 Saga 控制中心" })).toBeVisible();
  await expect(page.getByText("NOT CERTIFIED")).toBeVisible();
  await page.getByRole("link", { name: "状态机" }).click();
  await expect(page.getByRole("button", { name: "运行状态机验证" })).toBeVisible();
  await page.getByRole("link", { name: "卡死检测" }).click();
  await expect(page.getByRole("button", { name: "扫描卡死流程" })).toBeVisible();
});

test("process console exposes no direct domain-state editor", async ({ page }) => {
  await page.goto("/admin/processes/interventions");
  await expect(page.getByText(/direct sql|直接修改状态|伪造支付/i)).toHaveCount(0);
});
