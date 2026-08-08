import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import { recommendationFixturePassword, resetLoginRateLimits, seedRelationshipFixture } from "../helpers";

let memberEmail = "";
test.beforeAll(() => { resetLoginRateLimits(); memberEmail = seedRelationshipFixture(); });

async function signIn(page: Page) {
  await page.goto("/zh-CN/auth/login");
  await page.getByLabel("邮箱或账号").fill(memberEmail);
  await page.getByLabel("密码").fill(recommendationFixturePassword);
  await page.getByRole("button", { name: "欢迎回来" }).click();
  await expect(page).toHaveURL(/\/zh-CN\/account\/security$/u);
}

test("member sees a consent-preserving relationship journey", async ({ page }) => {
  await signIn(page);
  const listResponsePromise = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith("/api/v1/account/relationships") &&
    response.request().method() === "GET" && response.ok()
  );
  await page.goto("/zh-CN/account/relationships");
  const listPayload = await listResponsePromise.then((response) => response.json()) as {
    data: Array<{ journey_id: string; journey_number: string; current_stage_code: string; status: string }>;
  };
  expect(listPayload.data.length).toBeGreaterThan(0);
  const journey = listPayload.data[0];
  await expect(page.getByRole("heading", { name: "关系旅程" })).toBeVisible();
  await expect(page.getByText(/阶段推进需要双方确认/)).toBeVisible();
  const journeyLink = page.getByRole("link", { name: new RegExp(journey.journey_number, "u") });
  await expect(journeyLink).toContainText(journey.current_stage_code);
  await expect(journeyLink).toContainText(journey.status);
  await journeyLink.click();
  await expect(page).toHaveURL(new RegExp(`/account/relationships/${journey.journey_id}$`, "u"));
  await expect(page.getByRole("heading", { name: "双方确认阶段" })).toBeVisible();
  await expect(page.getByRole("heading", { name: journey.current_stage_code })).toBeVisible();
  await expect(page.getByText(`状态：${journey.status}`)).toBeVisible();
  await expect(page.getByRole("heading", { name: "共同里程碑" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "我的私密反思" })).toBeVisible();
  await expect(page.getByRole("button", { name: "结束关系旅程" })).toBeVisible();
  await expect(page.getByText(/关系打分|关系健康分/)).toHaveCount(0);
});
