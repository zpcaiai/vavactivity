import { createHmac, randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import {
  providerPaymentId,
  seedCommerceFixture,
  verificationLinkFor
} from "./helpers";

test.beforeAll(() => {
  seedCommerceFixture();
});

test("a verified user checks out and only a signed webhook fulfills the order", async ({
  page,
  request
}) => {
  const email = `commerce-e2e-${Date.now()}@example.com`;
  const password = "VavCommerce!2026_Secure#";
  await page.goto("/zh-CN/auth/register");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByLabel("我已阅读并同意服务条款与隐私说明").check();
  await page.getByRole("button", { name: "建立 VAV 账户" }).click();
  await page.goto(await verificationLinkFor(request, email));
  await expect(page.getByRole("status")).toContainText("邮箱已验证");
  await page.goto("/zh-CN/auth/login");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "欢迎回来" }).click();
  await expect(page).toHaveURL(/\/account\/security$/);

  await page.goto("/zh-CN/products/commerce-e2e-service?currency=USD");
  await page.getByRole("button", { name: "获取后端报价" }).click();
  await expect(page.getByText(/报价有效至/)).toBeVisible();
  await page.getByRole("button", { name: "加入购物车" }).click();
  await page.getByRole("link", { name: "查看购物车" }).click();
  await page.getByRole("link", { name: "安全结账" }).click();
  await expect(page.getByText("USD 12.99")).toBeVisible();
  await page.getByRole("button", { name: "创建支付" }).click();
  await expect(page).toHaveURL(/\/checkout\/processing\?order=/);
  await expect(page.getByText("payment_processing")).toBeVisible();
  const orderNumber = new URL(page.url()).searchParams.get("order");
  expect(orderNumber).toBeTruthy();

  const payload = JSON.stringify({
    id: `evt_test_browser_${randomUUID()}`,
    type: "payment.succeeded",
    data: {
      provider_payment_id: providerPaymentId(orderNumber!),
      amount_minor: 1299,
      currency: "USD"
    }
  });
  const signature = createHmac(
    "sha256",
    "local-commerce-webhook-change-me"
  ).update(payload).digest("hex");
  const webhook = await request.post("http://localhost:8000/api/v1/webhooks/stripe", {
    data: payload,
    headers: {
      "Content-Type": "application/json",
      "X-VAV-Test-Signature": signature
    }
  });
  expect(webhook.ok()).toBeTruthy();
  await expect(page.getByText("fulfilled")).toBeVisible({ timeout: 12_000 });
  await page.getByRole("link", { name: "查看订单" }).click();
  await expect(page.getByText("course_access · active")).toBeVisible();
});
