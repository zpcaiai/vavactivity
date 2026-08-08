import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import {
  recommendationFixturePassword,
  resetLoginRateLimits,
  seedMembershipFixture
} from "../helpers";

let memberEmail = "";
test.beforeAll(() => {
  resetLoginRateLimits();
  memberEmail = seedMembershipFixture();
});

async function signIn(page: Page) {
  await page.goto("/zh-CN/auth/login");
  await page.getByLabel("邮箱或账号").fill(memberEmail);
  await page.getByLabel("密码").fill(recommendationFixturePassword);
  await page.getByRole("button", { name: "欢迎回来" }).click();
  await expect(page).toHaveURL(/\/zh-CN\/account\/security$/u);
}

test("public plans explain enforceable benefits and limits", async ({ page }) => {
  await page.goto("/zh-CN/membership/plans");
  await expect(page.getByRole("heading", { name: "会员计划" })).toBeVisible();
  await expect(page.getByText(/不能绕过安全、隐私、屏蔽/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "免费会员" })).toBeVisible();
  await expect(page.getByRole("link", { name: "查看真实权益与限制" }).first()).toBeVisible();
  await expect(page.getByText(/无限 AI|无限推荐|永久课程/)).toHaveCount(0);
});

test("member sees the authoritative plan, benefits, quota and history", async ({ page }) => {
  await signIn(page);
  const currentResponsePromise = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith("/api/v1/account/membership") &&
    response.request().method() === "GET" && response.ok()
  );
  const historyResponsePromise = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith("/api/v1/account/membership/history") &&
    response.request().method() === "GET" && response.ok()
  );
  await page.goto("/zh-CN/account/membership");
  const currentPayload = await currentResponsePromise.then((response) => response.json()) as {
    data: {
      plan_code: string;
      plan_name: string;
      status: string;
      benefits: Array<{ benefit_code: string }>;
      quotas: Array<{ benefit_code: string }>;
    };
  };
  const historyPayload = await historyResponsePromise.then((response) => response.json()) as {
    data: Array<{ plan_code: string; status: string }>;
  };

  expect(currentPayload.data.plan_code).toBe("free-v1");
  expect(currentPayload.data.benefits.length).toBeGreaterThan(0);
  expect(currentPayload.data.quotas.length).toBeGreaterThan(0);
  expect(historyPayload.data.length).toBeGreaterThan(0);
  await expect(page.getByRole("heading", { name: "我的会员" })).toBeVisible();
  await expect(page.getByRole("heading", { name: currentPayload.data.plan_name })).toBeVisible();
  await expect(page.getByText(currentPayload.data.status, { exact: true }).first()).toBeVisible();
  await expect(
    page.getByText(currentPayload.data.benefits[0].benefit_code, { exact: true }).first()
  ).toBeVisible();
  await expect(
    page.getByText(currentPayload.data.quotas[0].benefit_code, { exact: true }).last()
  ).toBeVisible();
  await expect(page.getByText(historyPayload.data[0].plan_code, { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "升级或变更" })).toBeVisible();
});
