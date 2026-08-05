import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import {
  adminEmail,
  adminPassword,
  recommendationFixtureDisplayNames,
  resetLoginRateLimits,
  seedRecommendationFixture,
  seedSuperAdmin
} from "../helpers";

const adminBaseUrl = process.env.E2E_ADMIN_WEB_URL ?? "http://localhost:5174";

test.beforeAll(() => {
  resetLoginRateLimits();
  seedSuperAdmin();
  seedRecommendationFixture();
});

async function openBatches(page: Page) {
  await page.goto(`${adminBaseUrl}/admin/login`);
  await page.getByLabel("管理员邮箱").fill(adminEmail);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "安全登录" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);
  await page.goto(`${adminBaseUrl}/admin/recommendations/batches`);
  await expect(
    page.getByRole("heading", { name: "推荐运营中心", level: 2 })
  ).toBeVisible();
}

test("a batch is inspected as ranked candidate pairs, never as named members", async ({
  page
}) => {
  await openBatches(page);

  await page.getByRole("button", { name: "查看排序" }).first().click();
  await expect(
    page.getByText("已打开批次的排序结果：仅显示候选配对 ID、分数调整项与最终名次。")
  ).toBeVisible();

  for (const label of [
    "名次",
    "候选配对 ID",
    "基础分 (bps)",
    "调整后 (bps)",
    "新鲜度调整",
    "多样性调整",
    "曝光调整",
    "探索调整"
  ]) {
    await expect(page.getByText(label).first()).toBeVisible();
  }
  await expect(
    page.getByText("分数与调整项只读：引擎按策略版本计算，运营不能手工覆盖任何一项。")
  ).toBeVisible();

  // The ranking is expressed in pair identifiers; no member is named here.
  for (const displayName of recommendationFixtureDisplayNames) {
    await expect(page.getByText(displayName)).toHaveCount(0);
  }
});

test("rebuilding a member's batch is blocked until a reason is recorded", async ({ page }) => {
  await openBatches(page);

  await expect(
    page.getByText(
      "重建只会用同一套流水线重跑一次，不能指定候选人，也不能修改任何分数；原因必填。"
    )
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "重建该会员的推荐" })).toBeDisabled();

  await page.getByLabel("操作原因").fill("e2e 重建原因门槛验证");
  await expect(page.getByRole("button", { name: "重建该会员的推荐" })).toBeEnabled();
});

test("the centre says what an operator can never do to a batch", async ({ page }) => {
  await openBatches(page);

  await expect(
    page.getByText(
      "运营人员只监督引擎：这里没有指定两个人配对、手工改分、绕过硬性条件或查看会员择偶条件原文的入口。"
    )
  ).toBeVisible();
  await expect(
    page.getByText(
      "推荐结果由策略版本、特征注册表与硬性条件共同决定；运营的每一次干预都会带原因写入推荐审计，"
    )
  ).toBeVisible();
});
