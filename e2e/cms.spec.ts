import { expect, test } from "@playwright/test";

test("the public site switches locale and submits a consented contact request", async ({
  page
}) => {
  await page.goto("/zh-CN");
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
  await page.goto("/en");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");

  await page.goto("/zh-CN/contact");
  await page.getByLabel("姓名").fill("E2E 联系人");
  await page.getByLabel("邮箱").fill(`contact-${Date.now()}@example.com`);
  await page.getByLabel("消息").fill("这是一条浏览器端到端验收使用的合作联系消息。");
  await page.getByLabel("我同意按照隐私说明处理本次联系资料").check();
  await page.waitForTimeout(3_100);
  await page.getByRole("button", { name: "提交联系" }).click();
  await expect(page.getByRole("status")).toContainText("已收到你的联系信息");
});
