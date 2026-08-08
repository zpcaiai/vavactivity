import { expect, it } from "vitest";
import { resolveStep } from "../src";

it("does not make blocked journey steps actionable", () => expect(resolveStep([{ code: "review", route: "user.safety" }], { current_step_code: "review", state: "blocked", authoritative_state_version: "2" }).actionable).toBe(false));
