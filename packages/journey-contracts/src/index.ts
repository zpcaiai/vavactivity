export type JourneyState = "active" | "blocked" | "waiting" | "completed" | "cancelled" | "expired" | "invalidated";
export interface JourneyStep { code: string; route: string }
export interface JourneyProjection { current_step_code: string; state: JourneyState; authoritative_state_version: string }

export function resolveStep(steps: JourneyStep[], projection: JourneyProjection) {
  const step = steps.find((item) => item.code === projection.current_step_code);
  if (!step) throw new Error("projection step is outside the active journey version");
  return { step, actionable: projection.state === "active", terminal: ["completed", "cancelled", "expired", "invalidated"].includes(projection.state) };
}
