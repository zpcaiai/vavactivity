export type SkillErrorCategory =
  | "validation"
  | "authorization"
  | "dependency"
  | "conflict"
  | "rate_limit"
  | "timeout"
  | "provider"
  | "business"
  | "internal";

export type SkillError = Readonly<{
  code: string;
  category: SkillErrorCategory;
  messageSafe: string;
  retryable: boolean;
  correlationId: string;
  fieldErrors?: ReadonlyArray<Readonly<{ field: string; code: string; messageSafe: string }>>;
}>;

export class SkillExecutionError extends Error {
  constructor(readonly contract: SkillError) {
    super(contract.messageSafe);
    this.name = "SkillExecutionError";
  }
}

export function safeInternalError(correlationId: string): SkillExecutionError {
  return new SkillExecutionError({
    code: "SKILL_INTERNAL_ERROR",
    category: "internal",
    messageSafe: "The Skill could not complete.",
    retryable: false,
    correlationId
  });
}
