import { execFileSync } from "node:child_process";

import type { APIRequestContext } from "@playwright/test";
import { expect } from "@playwright/test";

export const adminEmail = "e2e-admin@example.com";
export const adminPassword = "VavE2e!2026_Secure#";

export function seedSuperAdmin() {
  if (process.env.VAV_E2E_SKIP_ADMIN_SEED === "1") return;
  execFileSync(
    "docker",
    [
      "compose",
      "exec",
      "-T",
      "api",
      "python",
      "-c",
      [
        "import asyncio",
        "from vav.cli.create_super_admin import create_super_admin",
        `asyncio.run(create_super_admin(${JSON.stringify(adminEmail)}, ${JSON.stringify(adminPassword)}))`
      ].join(";")
    ],
    { stdio: "pipe" }
  );
}

export function seedCommerceFixture() {
  for (const moduleName of ["vav.cli.seed_catalog", "vav.cli.seed_commerce"]) {
    execFileSync(
      "docker",
      ["compose", "exec", "-T", "api", "python", "-m", moduleName],
      { stdio: "pipe" }
    );
  }
}

export function seedActivityFixture() {
  for (const moduleName of [
    "vav.cli.seed_catalog",
    "vav.cli.seed_activities"
  ]) {
    execFileSync(
      "docker",
      ["compose", "exec", "-T", "api", "python", "-m", moduleName],
      { stdio: "pipe" }
    );
  }
}

export function seedCourseFixture() {
  for (const moduleName of [
    "vav.cli.seed_catalog",
    "vav.cli.seed_courses"
  ]) {
    execFileSync(
      "docker",
      ["compose", "exec", "-T", "api", "python", "-m", moduleName],
      { stdio: "pipe" }
    );
  }
}

export function seedCounselingFixture() {
  for (const moduleName of [
    "vav.cli.seed_permissions",
    "vav.cli.seed_catalog",
    "vav.cli.seed_counseling"
  ]) {
    execFileSync(
      "docker",
      ["compose", "exec", "-T", "api", "python", "-m", moduleName],
      { stdio: "pipe" }
    );
  }
}

export function seedKnowledgeFixture() {
  for (const moduleName of ["vav.cli.seed_permissions", "vav.cli.seed_knowledge"]) {
    execFileSync(
      "docker",
      ["compose", "exec", "-T", "api", "python", "-m", moduleName],
      { stdio: "pipe" }
    );
  }
}

export function seedAiFixture() {
  if (process.env.VAV_E2E_SKIP_AI_SEED === "1") return;
  for (const moduleName of [
    "vav.cli.seed_permissions",
    "vav.cli.seed_ai_assistant"
  ]) {
    execFileSync(
      "docker",
      ["compose", "exec", "-T", "api", "python", "-m", moduleName],
      { stdio: "pipe" }
    );
  }
}

export function seedNotificationFixture() {
  if (process.env.VAV_E2E_SKIP_NOTIFICATION_SEED === "1") return;
  for (const moduleName of [
    "vav.cli.seed_permissions",
    "vav.cli.seed_notification_templates",
    "vav.cli.seed_notifications"
  ]) {
    execFileSync(
      "docker",
      ["compose", "exec", "-T", "api", "python", "-m", moduleName],
      { stdio: "pipe" }
    );
  }
}

export function verifyUserFixture(email: string) {
  const escaped = email.replaceAll("'", "''");
  execFileSync(
    "docker",
    [
      "compose",
      "exec",
      "-T",
      "postgres",
      "psql",
      "-U",
      "vav",
      "-d",
      "vav",
      "-c",
      `UPDATE users SET status='active', email_verified_at=now() WHERE email='${escaped}'`
    ],
    { stdio: "pipe" }
  );
}

export function seedUserNotificationFixture(email: string) {
  const escaped = email.replaceAll("'", "''");
  const deduplicationKey = `notification-e2e-${Date.now()}`;
  execFileSync(
    "docker",
    [
      "compose",
      "exec",
      "-T",
      "postgres",
      "psql",
      "-U",
      "vav",
      "-d",
      "vav",
      "-v",
      "ON_ERROR_STOP=1",
      "-c",
      [
        "WITH target AS (SELECT id FROM users WHERE email='" + escaped + "'),",
        "created_intent AS (",
        "  INSERT INTO notification_intents (notification_type,category,priority,recipient_type,recipient_reference_id,template_code,channel_policy,preference_policy,template_variables_encrypted,deduplication_key,status)",
        "  SELECT 'notification-e2e','platform','normal','user',id,'platform-announcement','{\"required\":[\"in_app\"]}'::jsonb,'service_optional','encrypted','" + deduplicationKey + "','created' FROM target RETURNING id,recipient_reference_id",
        ")",
        "INSERT INTO user_notifications (user_id,notification_intent_id,category,priority,title,body,action_type,action_reference,action_url,status,rendering_snapshot)",
        "SELECT recipient_reference_id,id,'platform','normal','Batch 11 浏览器验收通知','这是一条来自持久化通知中心的可审计消息。','route','{\"route_name\":\"account-notifications\",\"params\":{}}'::jsonb,'/account/notifications','active','{\"locale\":\"zh-CN\",\"channel\":\"in_app\"}'::jsonb FROM created_intent"
      ].join(" ")
    ],
    { stdio: "pipe" }
  );
}

export function providerPaymentId(orderNumber: string): string {
  return execFileSync(
    "docker",
    [
      "compose",
      "exec",
      "-T",
      "api",
      "python",
      "-c",
      [
        "import asyncio",
        "from sqlalchemy import select",
        "from vav.core.database import session_factory",
        "from vav.models.commerce import Order, PaymentAttempt",
        "async def main():",
        " async with session_factory() as session:",
        `  order = await session.scalar(select(Order).where(Order.order_number == ${JSON.stringify(orderNumber)}))`,
        "  payment = await session.scalar(select(PaymentAttempt).where(PaymentAttempt.order_id == order.id))",
        "  print(payment.provider_payment_id)",
        "asyncio.run(main())"
      ].join("\n")
    ],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }
  ).trim();
}

interface MailpitMessage {
  ID: string;
  To: Array<{ Address: string }>;
}

export async function verificationLinkFor(
  request: APIRequestContext,
  recipient: string
): Promise<string> {
  let messageId = "";
  await expect.poll(async () => {
    const response = await request.get("http://localhost:8025/api/v1/messages");
    expect(response.ok()).toBeTruthy();
    const payload = await response.json() as { messages: MailpitMessage[] };
    messageId = payload.messages.find((message) =>
      message.To.some((target) => target.Address === recipient)
    )?.ID ?? "";
    return messageId;
  }, {
    message: `verification email for ${recipient}`,
    timeout: 15_000
  }).not.toBe("");

  const response = await request.get(
    `http://localhost:8025/api/v1/message/${encodeURIComponent(messageId)}`
  );
  expect(response.ok()).toBeTruthy();
  const message = await response.json() as { Text: string };
  const match = message.Text.match(/https?:\/\/[^\s]+\/auth\/verify-email\?token=[^\s]+/);
  expect(match, "verification email contains a browser link").not.toBeNull();
  return match![0];
}
