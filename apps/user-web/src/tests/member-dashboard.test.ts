import { beforeEach, describe, expect, it, vi } from "vitest";

const bootstrap = vi.fn(async () => undefined);
vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({ bootstrap, accessToken: "member-token", user: { id: "member" } })
}));

import { useDashboard } from "@/features/member-dashboard/composables/useDashboard";
import type { DashboardView } from "@/features/member-dashboard/types";

function view(overrides: Partial<DashboardView> = {}): DashboardView {
  return {
    sections: {
      survey_tasks: {
        key: "survey_tasks",
        count: 1,
        items: [
          {
            task_type: "survey_pending",
            task_key: "survey_pending:1",
            section: "survey_tasks",
            subject_id: "1",
            deep_link: "/account/surveys/1",
            priority: "urgent",
            due_at: null,
            activity_id: null,
            title_code: "",
            metadata: {}
          }
        ],
        total: 1,
        limit: 20,
        offset: 0,
        has_more: false
      },
      notifications: {
        key: "notifications",
        available: false,
        error_code: "SECTION_UNAVAILABLE"
      }
    },
    degraded: ["notifications"],
    counts: { survey_tasks: 1 },
    total_open_tasks: 1,
    generated_at: "2026-08-13T00:00:00Z",
    relationship_gate: { matchmaking_available: false },
    ...overrides
  };
}

function stubFetch(payload: DashboardView) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () =>
        url.includes("/preferences")
          ? { data: { hidden_sections: [], page_size: 20 } }
          : { data: payload }
    }))
  );
}

describe("member dashboard", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps a degraded section visible and separate from an ineligible one", async () => {
    stubFetch(view());
    const dashboard = useDashboard();
    await dashboard.load();

    const keys = dashboard.orderedSections.value.map((entry) => entry.key);
    // A section whose module failed is still rendered — the member is told it
    // is missing rather than shown a silently shorter list.
    expect(keys).toContain("notifications");
    expect(dashboard.degraded.value).toEqual(["notifications"]);
    // The gated section was never sent, so it must not be rendered at all:
    // "not for you" and "temporarily broken" must not look alike.
    expect(keys).not.toContain("matchmaking");
  });

  it("does not count a degraded section as zero outstanding items", async () => {
    stubFetch(view());
    const dashboard = useDashboard();
    await dashboard.load();

    // The server's total covers working sections only. A client-side sum over
    // rendered sections would quietly turn "unknown" into "none".
    expect(dashboard.totalOpenTasks.value).toBe(1);
    expect(dashboard.view.value?.counts.notifications).toBeUndefined();
  });

  it("surfaces urgent work across sections", async () => {
    stubFetch(view());
    const dashboard = useDashboard();
    await dashboard.load();

    expect(dashboard.urgentTasks.value).toHaveLength(1);
    expect(dashboard.urgentTasks.value[0]?.task_key).toBe("survey_pending:1");
  });

  it("renders nothing for a member with no sections at all", async () => {
    stubFetch(
      view({ sections: {}, degraded: [], counts: {}, total_open_tasks: 0 })
    );
    const dashboard = useDashboard();
    await dashboard.load();

    expect(dashboard.orderedSections.value).toHaveLength(0);
    expect(dashboard.totalOpenTasks.value).toBe(0);
  });

  it("rolls a preference back when the server rejects it", async () => {
    const payload = view();
    let call = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (init?.method === "PUT") {
          call += 1;
          return { ok: false, status: 500, json: async () => ({ error: { message: "nope" } }) };
        }
        return {
          ok: true,
          status: 200,
          json: async () =>
            url.includes("/preferences")
              ? { data: { hidden_sections: [], page_size: 20 } }
              : { data: payload }
        };
      })
    );

    const dashboard = useDashboard();
    await dashboard.load();
    await dashboard.toggleSection("survey_tasks");

    expect(call).toBe(1);
    // The UI must not keep claiming a preference the server never stored.
    expect(dashboard.preferences.value.hidden_sections).toEqual([]);
  });
});
