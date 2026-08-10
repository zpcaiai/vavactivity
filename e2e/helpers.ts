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
    "vav.cli.seed_ai_assistant",
    "vav.cli.run_ai_evaluation"
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

export function seedPrivacyFixture() {
  if (process.env.VAV_E2E_SKIP_PRIVACY_SEED === "1") return;
  for (const moduleName of [
    "vav.cli.seed_permissions",
    "vav.cli.seed_privacy",
    "vav.cli.seed_privacy_inventory"
  ]) {
    execFileSync(
      "docker",
      ["compose", "exec", "-T", "api", "python", "-m", moduleName],
      { stdio: "pipe" }
    );
  }
}

export function seedDatingProfileFixture() {
  if (process.env.VAV_E2E_SKIP_DATING_SEED === "1") return;
  for (const moduleName of [
    "vav.cli.seed_permissions",
    "vav.cli.seed_privacy",
    "vav.cli.seed_dating_taxonomies",
    "vav.cli.seed_dating_profiles"
  ]) {
    execFileSync(
      "docker",
      ["compose", "exec", "-T", "api", "python", "-m", moduleName],
      { stdio: "pipe" }
    );
  }
}

/**
 * Seed the Batch 14 recommendation engine through the CLIs the platform ships.
 *
 * The fixture members, the pool and the batches are all produced by the same
 * pipeline the scheduled worker uses, so a browser run never sees a shortcut
 * that production would not take.
 */
export function seedRecommendationFixture() {
  if (process.env.VAV_E2E_SKIP_RECOMMENDATION_SEED === "1") return;
  for (const moduleName of [
    "vav.cli.seed_permissions",
    "vav.cli.seed_recommendations",
    "vav.cli.seed_recommendation_fixtures",
    "vav.cli.build_recommendation_pool",
    "vav.cli.generate_recommendation_fixture_batches"
  ]) {
    execFileSync(
      "docker",
      ["compose", "exec", "-T", "api", "python", "-m", moduleName],
      { stdio: "pipe" }
    );
  }
  // Batch 15 browser tests may have consumed a synthetic recommendation with
  // like/skip. Restore only those synthetic cards so Batch 14 acceptance stays
  // repeatable regardless of suite order; production/member rows are untouched.
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
      "UPDATE recommendation_items SET status='ready', exposed_at=NULL, viewed_at=NULL, invalidated_at=NULL, invalidation_reason=NULL WHERE viewer_user_id IN (SELECT id FROM users WHERE email LIKE 'recommendation-fixture-%@example.com') AND (status IN ('liked','skipped') OR (status='invalidated' AND invalidation_reason='member_settings_changed'))"
    ],
    { stdio: "pipe" }
  );
}

/**
 * Build a Batch 15 match and pending invitation through the real services.
 * The members are synthetic Batch 14 fixtures; no production account is read
 * or mutated and no row is inserted behind the domain services' backs.
 */
export function seedMatchmakingInteractionFixture(): string {
  seedRecommendationFixture();
  execFileSync(
    "docker",
    ["compose", "exec", "-T", "api", "python", "-m", "vav.cli.seed_matchmaking_interactions"],
    { stdio: "pipe" }
  );
  return apiPython([
    "import asyncio",
    "from uuid import UUID",
    "from sqlalchemy import text",
    "from vav.core.database import session_factory",
    "from vav.modules.matchmaking_interactions import likes, invitations",
    "async def main():",
    "    async with session_factory() as session:",
    "        existing = (await session.execute(text(\"SELECT m.id,u.email FROM matchmaking_introduction_invitations i JOIN matchmaking_mutual_matches m ON m.id=i.mutual_match_id JOIN users u ON u.id=i.sender_user_id WHERE u.email LIKE 'recommendation-fixture-%@example.com' AND i.status='pending' ORDER BY i.created_at DESC LIMIT 1\"))).first()",
    "        if existing is not None:",
    "            print(existing.email)",
    "            return",
    "        active = (await session.execute(text(\"SELECT m.id AS match_id,m.user_low_id AS sender_user_id,u.email FROM matchmaking_mutual_matches m JOIN users u ON u.id=m.user_low_id WHERE u.email LIKE 'recommendation-fixture-%@example.com' AND m.status='active' ORDER BY m.created_at DESC LIMIT 1\"))).mappings().first()",
    "        if active is not None:",
    "            await invitations.send_invitation(session, sender_user_id=active['sender_user_id'], match_id=active['match_id'], message='愿意在平台内进一步认识吗？', idempotency_key='e2e-introduction-active')",
    "            await session.commit()",
    "            print(active['email'])",
    "            return",
    "        row = (await session.execute(text(\"SELECT i.id AS first_item,j.id AS second_item,i.viewer_user_id AS first_user,i.recommended_user_id AS second_user,u.email FROM recommendation_items i JOIN recommendation_items j ON j.viewer_user_id=i.recommended_user_id AND j.recommended_user_id=i.viewer_user_id JOIN users u ON u.id=i.viewer_user_id WHERE i.status IN ('ready','exposed','viewed') AND j.status IN ('ready','exposed','viewed') AND u.email LIKE 'recommendation-fixture-%@example.com' ORDER BY i.created_at DESC LIMIT 1\"))).mappings().first()",
    "        if row is None:",
    "            raise SystemExit('no reciprocal actionable recommendation fixture')",
    "        await likes.create_like(session, viewer_user_id=row['first_user'], recommendation_item_id=row['first_item'], idempotency_key=f\"e2e-first-like-{row['first_item']}\")",
    "        matched = await likes.create_like(session, viewer_user_id=row['second_user'], recommendation_item_id=row['second_item'], idempotency_key=f\"e2e-second-like-{row['second_item']}\")",
    "        match_id = UUID(matched['mutual_match_id'])",
    "        await invitations.send_invitation(session, sender_user_id=row['first_user'], match_id=match_id, message='愿意在平台内进一步认识吗？', idempotency_key=f'e2e-introduction-{match_id}')",
    "        await session.commit()",
    "        print(row['email'])",
    "asyncio.run(main())"
  ]);
}

/** Accept the pending Batch 15 introduction through the domain service so the
 * Batch 16 relationship handoff and its initial timeline are real. */
export function seedRelationshipFixture(): string {
  seedMatchmakingInteractionFixture();
  return apiPython([
    "import asyncio",
    "from sqlalchemy import text",
    "from vav.core.database import session_factory",
    "from vav.modules.matchmaking_interactions import invitations",
    "async def main():",
    "    async with session_factory() as session:",
    "        existing = (await session.execute(text(\"SELECT j.id,u.email FROM relationship_journeys j JOIN users u ON u.id=j.user_low_id WHERE u.email LIKE 'recommendation-fixture-%@example.com' ORDER BY j.created_at DESC LIMIT 1\"))).first()",
    "        if existing is not None:",
    "            print(existing.email)",
    "            return",
    "        invitation = (await session.execute(text(\"SELECT i.id,i.recipient_user_id,u.email FROM matchmaking_introduction_invitations i JOIN users u ON u.id=i.sender_user_id WHERE u.email LIKE 'recommendation-fixture-%@example.com' AND i.status='pending' ORDER BY i.created_at DESC LIMIT 1\"))).mappings().one()",
    "        await invitations.accept_invitation(session,user_id=invitation['recipient_user_id'],invitation_id=invitation['id'])",
    "        await session.commit()",
    "        print(invitation['email'])",
    "asyncio.run(main())"
  ]);
}

/** Password `vav.cli.seed_recommendation_fixtures` gives every fixture member. */
export const recommendationFixturePassword = "RecommendationFixture!2026";

/** Fixture member keys seeded by `vav.cli.seed_recommendation_fixtures`. */
export const recommendationFixtureKeys = [
  "mei",
  "jonathan",
  "daniel",
  "grace",
  "peter",
  "hannah"
] as const;

/** Display names the fixtures publish; used to prove operators never see them. */
export const recommendationFixtureDisplayNames = [
  "Mei R.",
  "Jonathan T.",
  "Daniel K.",
  "Grace H.",
  "Peter S.",
  "Hannah C."
];

export function recommendationFixtureEmail(
  key: (typeof recommendationFixtureKeys)[number]
): string {
  return `recommendation-fixture-${key}@example.com`;
}

/** An operator role that deliberately lacks the sensitive and experiment scopes. */
export const recommendationOperatorEmail = "e2e-recommendation-operator@example.com";
export const recommendationOperatorPassword = "VavRecoOps!2026_Secure#";

function apiPython(script: string[]): string {
  return execFileSync(
    "docker",
    ["compose", "exec", "-T", "api", "python", "-c", script.join("\n")],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }
  ).trim();
}

/** Create an authenticated member with a real free membership projection. */
export function seedMembershipFixture(): string {
  const email = recommendationFixtureEmail("mei");
  const existingEmail = apiPython([
    "import asyncio",
    "from sqlalchemy import select",
    "from vav.core.database import session_factory",
    "from vav.models.identity import User",
    `EMAIL = ${JSON.stringify(email)}`,
    "async def main():",
    "    async with session_factory() as session:",
    "        user = await session.scalar(select(User.email).where(User.email == EMAIL))",
    "        print(user or '')",
    "asyncio.run(main())"
  ]);
  if (!existingEmail) seedRecommendationFixture();
  execFileSync(
    "docker",
    ["compose", "exec", "-T", "api", "python", "-m", "vav.cli.seed_memberships"],
    { stdio: "pipe" }
  );
  apiPython([
    "import asyncio",
    "from sqlalchemy import select",
    "from vav.core.database import session_factory",
    "from vav.models.identity import User",
    "from vav.modules.memberships import projection",
    `EMAIL = ${JSON.stringify(email)}`,
    "async def main():",
    "    async with session_factory() as session:",
    "        user = await session.scalar(select(User).where(User.email == EMAIL))",
    "        if user is None:",
    "            raise SystemExit(f'membership fixture user missing: {EMAIL}')",
    "        await projection.ensure_free_membership(session, user.id)",
    "        print(EMAIL)",
    "asyncio.run(main())"
  ]);
  return email;
}

/** Run SQL and return the last value psql printed, ignoring command tags. */
function postgresValue(statements: string): string {
  const output = execFileSync(
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
      "-q",
      "-t",
      "-A",
      "-v",
      "ON_ERROR_STOP=1",
      "-c",
      statements
    ],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }
  );
  const lines = output.split(/\r?\n/u).map((line) => line.trim()).filter(Boolean);
  return lines.at(-1) ?? "";
}

/** Fail loudly when the fixture the spec depends on was never produced. */
function requiredPostgresValue(subject: string, statements: string): string {
  const value = postgresValue(statements);
  if (!value) {
    throw new Error(`${subject} is missing; run seedRecommendationFixture() first.`);
  }
  return value;
}

/** Identifier of the strategy version the engine is currently serving. */
export function activeRecommendationStrategyId(): string {
  return requiredPostgresValue(
    "an active recommendation strategy",
    "SELECT id FROM recommendation_strategies WHERE status='active' " +
      "ORDER BY activated_at DESC NULLS LAST LIMIT 1"
  );
}

export function recommendationFixtureUserId(
  key: (typeof recommendationFixtureKeys)[number]
): string {
  return requiredPostgresValue(
    `fixture member ${key}`,
    `SELECT id FROM users WHERE email='${recommendationFixtureEmail(key)}'`
  );
}

/** A candidate pair the engine actually produced, for the sensitive diagnostics. */
export function recommendationCandidatePairId(): string {
  return requiredPostgresValue(
    "a recommendation candidate pair",
    "SELECT id FROM recommendation_candidate_pairs ORDER BY generated_at DESC LIMIT 1"
  );
}

/**
 * A strategy version parked in `evaluating` with no evaluation run at all.
 *
 * It exists so a browser run can prove the release gate: without a passing
 * offline evaluation the backend refuses to approve or activate the version.
 */
export const recommendationCandidateStrategyCode = "vav-recommendation-e2e-candidate";

export function seedRecommendationCandidateStrategy(): string {
  const code = recommendationCandidateStrategyCode;
  return requiredPostgresValue(
    "the e2e candidate strategy",
    [
      "INSERT INTO recommendation_strategies (strategy_code,semantic_version,status," +
        "hard_constraint_policy,feature_manifest,scoring_policy,bidirectional_policy,ranking_policy," +
        "diversification_policy,exposure_policy,explanation_policy,cold_start_policy," +
        "applicable_regions,applicable_segments) " +
        `SELECT '${code}','9.9.9','evaluating',` +
        "hard_constraint_policy,feature_manifest,scoring_policy,bidirectional_policy,ranking_policy," +
        "diversification_policy,exposure_policy,explanation_policy,cold_start_policy," +
        "applicable_regions,applicable_segments FROM recommendation_strategies " +
        "WHERE status='active' LIMIT 1 " +
        "ON CONFLICT (strategy_code, semantic_version) DO NOTHING",
      "DELETE FROM recommendation_evaluation_runs WHERE strategy_id IN " +
        `(SELECT id FROM recommendation_strategies WHERE strategy_code='${code}')`,
      "UPDATE recommendation_strategies SET status='evaluating', evaluation_run_id=NULL, " +
        "approved_by=NULL, approved_at=NULL, activated_by=NULL, activated_at=NULL, updated_at=now() " +
        `WHERE strategy_code='${code}'`,
      `SELECT id FROM recommendation_strategies WHERE strategy_code='${code}' LIMIT 1`
    ].join("; ")
  );
}

/**
 * A running experiment whose guardrail threshold is already breached.
 *
 * Guardrails are compared against reported metrics, so a threshold below zero
 * makes the very next guardrail check stop the treatment — which is the rule
 * the operations centre has to demonstrate.
 */
export const recommendationExperimentCode = "e2e-guardrail-experiment";

export function seedBreachingRecommendationExperiment(): string {
  return requiredPostgresValue(
    "the e2e guardrail experiment",
    [
      "WITH source AS (",
      "  SELECT id FROM recommendation_strategies WHERE status='active' LIMIT 1",
      "), upserted AS (",
      "  INSERT INTO recommendation_experiments (experiment_code,name,hypothesis,status,",
      "    control_strategy_id,treatment_strategy_ids,eligibility_definition,allocation_policy,",
      "    primary_metrics,guardrail_metrics,guardrail_thresholds,starts_at,approved_at)",
      `  SELECT '${recommendationExperimentCode}','E2E 护栏实验','护栏指标越界必须立即停止实验。','running',`,
      "    source.id, to_jsonb(ARRAY[source.id::text]), '{}'::jsonb, '{}'::jsonb,",
      "    '[]'::jsonb, '[\"report_rate_bps\"]'::jsonb, '{\"report_rate_bps\": -1}'::jsonb, now(), now()",
      "  FROM source",
      "  ON CONFLICT (experiment_code) DO UPDATE SET status='running', ends_at=NULL,",
      "    stop_reason=NULL, starts_at=now(),",
      "    guardrail_metrics=EXCLUDED.guardrail_metrics,",
      "    guardrail_thresholds=EXCLUDED.guardrail_thresholds",
      "  RETURNING id",
      ")",
      "SELECT id FROM upserted"
    ].join(" ")
  );
}

/** An operator whose role covers monitoring but not the sensitive surfaces. */
export function seedRecommendationOperator() {
  apiPython([
    "import asyncio",
    "from datetime import UTC, datetime",
    "from uuid import uuid4",
    "from sqlalchemy import select",
    "from vav.core.database import session_factory",
    "from vav.models.identity import Role, User, UserRole",
    "from vav.modules.identity.domain import UserStatus",
    "from vav.modules.identity.security import PasswordHasher",
    `EMAIL = ${JSON.stringify(recommendationOperatorEmail)}`,
    `PASSWORD = ${JSON.stringify(recommendationOperatorPassword)}`,
    "async def main():",
    "    now = datetime.now(UTC)",
    "    hasher = PasswordHasher()",
    "    async with session_factory() as session:",
    "        role = await session.scalar(select(Role).where(Role.code == 'recommendation_operator'))",
    "        if role is None:",
    "            raise SystemExit('run vav.cli.seed_permissions first')",
    "        user = await session.scalar(select(User).where(User.email == EMAIL))",
    "        if user is None:",
    "            user = User(id=uuid4(), email=EMAIL, display_email=EMAIL,",
    "                        password_hash=hasher.hash(PASSWORD), status=UserStatus.ACTIVE,",
    "                        email_verified_at=now, preferred_locale='zh-CN', timezone='UTC',",
    "                        password_changed_at=now)",
    "            session.add(user)",
    "            await session.flush()",
    "        else:",
    "            user.password_hash = hasher.hash(PASSWORD)",
    "            user.status = UserStatus.ACTIVE",
    "            user.email_verified_at = user.email_verified_at or now",
    "            user.auth_version += 1",
    "        assignment = await session.get(UserRole, (user.id, role.id))",
    "        if assignment is None:",
    "            session.add(UserRole(user_id=user.id, role_id=role.id, granted_by=user.id,",
    "                                 grant_reason='e2e recommendation operator'))",
    "        else:",
    "            assignment.revoked_at = None",
    "            assignment.revoked_by = None",
    "            assignment.revoke_reason = None",
    "        user.rbac_version += 1",
    "        await session.commit()",
    "asyncio.run(main())"
  ]);
}

/**
 * Drop the login throttle counters.
 *
 * Admin logins are capped at five per quarter hour and per email, which a
 * directory full of specs would otherwise exhaust before the last file runs.
 */
export function resetLoginRateLimits() {
  const output = execFileSync(
    "docker",
    [
      "compose",
      "exec",
      "-T",
      "redis",
      "redis-cli",
      "--raw",
      "--scan",
      "--pattern",
      "rate:*"
    ],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }
  ).trim();
  const keys = output.split(/\r?\n/u).filter(Boolean);
  for (let offset = 0; offset < keys.length; offset += 100) {
    execFileSync(
      "docker",
      [
        "compose",
        "exec",
        "-T",
        "redis",
        "redis-cli",
        "UNLINK",
        ...keys.slice(offset, offset + 100)
      ],
      { stdio: "pipe" }
    );
  }
}

/** Give an e2e member the protected date of birth the adult check reads. */
export function seedProtectedDateOfBirth(email: string, isoDate = "1992-05-04") {
  const escaped = email.replaceAll("'", "''");
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
        "from sqlalchemy import text",
        "from vav.core.database import session_factory",
        "from vav.modules.privacy.crypto import encrypt_private",
        "async def main():",
        "    async with session_factory() as session:",
        "        await session.execute(text(\"INSERT INTO user_profiles (user_id,display_name,date_of_birth_encrypted,preferred_locale,timezone,profile_status) SELECT id,'E2E Member',:dob,'zh-CN','UTC','complete' FROM users WHERE email=:email ON CONFLICT (user_id) DO UPDATE SET date_of_birth_encrypted=EXCLUDED.date_of_birth_encrypted\"), {'dob': encrypt_private('" + isoDate + "'), 'email': '" + escaped + "'})",
        "        await session.execute(text(\"INSERT INTO user_privacy_settings (user_id,visible_in_matchmaking,privacy_mode) SELECT id,true,'strict' FROM users WHERE email=:email ON CONFLICT (user_id) DO UPDATE SET visible_in_matchmaking=true\"), {'email': '" + escaped + "'})",
        "        await session.commit()",
        "asyncio.run(main())"
      ].join("\n")
    ],
    { stdio: "pipe" }
  );
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
