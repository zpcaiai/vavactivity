import type { SkillContext } from "./context";

export type SkillMetadata = Readonly<{
  name: string;
  version: string;
  type: "query" | "command" | "workflow" | "agent-tool" | "event-handler" | "provider-adapter";
}>;

export interface Skill<Input, Output> {
  readonly metadata: SkillMetadata;
  execute(input: Input, context: SkillContext): Promise<Output>;
}

export interface CommandSkill<Input, Output> extends Skill<Input, Output> {
  readonly idempotencyRequired: true;
}

export type SkillResult<Output> = Readonly<{
  data: Output;
  warnings: ReadonlyArray<string>;
  metadata: Readonly<Record<string, string>>;
}>;
