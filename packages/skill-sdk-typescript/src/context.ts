export type PrincipalType = "user" | "admin" | "service" | "agent" | "event" | "schedule";

export type SkillPrincipal = Readonly<{
  principalType: PrincipalType;
  principalId: string;
  organizationId?: string;
}>;

export type SkillContext = Readonly<{
  executionId: string;
  installationId: string;
  actorUserId?: string;
  principal: SkillPrincipal;
  locale: string;
  timezone: string;
  idempotencyKey?: string;
  deadline: Date;
  permissions: ReadonlySet<string>;
  capabilityGrants: ReadonlySet<string>;
  requestId: string;
  traceId: string;
  signal: AbortSignal;
}>;

export function assertContextActive(context: SkillContext, now = new Date()): void {
  if (context.signal.aborted) throw new SkillCancelledError();
  if (now.getTime() >= context.deadline.getTime()) throw new SkillDeadlineExceededError();
}

export class SkillCancelledError extends Error {
  readonly code = "SKILL_CANCELLED";
  constructor() { super("SKILL_CANCELLED"); }
}

export class SkillDeadlineExceededError extends Error {
  readonly code = "SKILL_DEADLINE_EXCEEDED";
  constructor() { super("SKILL_DEADLINE_EXCEEDED"); }
}
