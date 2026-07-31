import { expect, test } from "@playwright/test";

import { seedCourseFixture, verificationLinkFor } from "./helpers";

test.beforeAll(() => seedCourseFixture());

test("a verified user joins a free version-pinned course and opens learning", async ({
  page,
  request
}) => {
  const email = `course-e2e-${Date.now()}@example.com`;
  const password = "VavCourse!2026_Secure#";
  await page.goto("/zh-CN/auth/register");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByLabel("我已阅读并同意服务条款与隐私说明").check();
  await page.getByRole("button", { name: "建立 VAV 账户" }).click();
  await page.goto(await verificationLinkFor(request, email));
  await page.goto("/zh-CN/auth/login");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "欢迎回来" }).click();
  await expect(page).toHaveURL(/\/account\/security$/);

  await page.goto("/zh-CN/courses/healthy-relationship-foundations");
  await expect(page.getByRole("heading", { name: "健康关系基础课", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "免费加入课程" }).click();
  await expect(page).toHaveURL(/\/zh-CN\/learn\//);
  await page.getByRole("button", { name: "识别尊重与边界" }).click();
  await expect(page.getByText("健康边界以自愿、尊重和清晰沟通为基础。")).toBeVisible();
  await page.getByRole("button", { name: "标记完成" }).click();
  await page.getByRole("button", { name: "开始练习" }).click();
  await page.getByLabel("正确").check();
  await page.getByRole("button", { name: "提交练习" }).click();
  await expect(page.getByText("练习已通过")).toBeVisible();
  await page.goto("/zh-CN/account/courses");
  await expect(page.getByRole("heading", { name: "我的课程", level: 1 })).toBeVisible();
  await expect(page.getByText("固定版本：")).toBeVisible();
  await page.getByRole("link", { name: "继续学习" }).click();
  await page.getByRole("button", { name: "沟通练习" }).click();
  await page.getByRole("button", { name: "开始安全播放" }).click();
  await expect(page.getByText("跳转到结尾不会计为完成")).toBeVisible();
});
