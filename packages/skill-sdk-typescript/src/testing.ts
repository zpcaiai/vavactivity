import type { SkillContext } from "./context";

export class FakeClock {
  constructor(private value = new Date("2026-01-01T00:00:00Z")) {}
  now(): Date { return new Date(this.value); }
  advance(milliseconds: number): void { this.value = new Date(this.value.getTime() + milliseconds); }
}

export function fakeSkillContext(overrides: Partial<SkillContext> = {}): SkillContext {
  const controller = new AbortController();
  const base: SkillContext = {
    executionId: "00000000-0000-4000-8000-000000000001",
    installationId: "00000000-0000-4000-8000-000000000002",
    principal: { principalType: "service", principalId: "skill-testkit" },
    locale: "zh-CN",
    timezone: "Asia/Shanghai",
    deadline: new Date(Date.now() + 30_000),
    permissions: new Set<string>(),
    capabilityGrants: new Set<string>(),
    requestId: "00000000-0000-4000-8000-000000000003",
    traceId: "0123456789abcdef0123456789abcdef",
    signal: controller.signal
  };
  return Object.freeze({ ...base, ...overrides });
}
