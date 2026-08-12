import { useLocalePath } from "@/composables/useAppNavigation";
import type { ExperienceRow } from "@/features/experience/api";

/**
 * Backend experience rows carry a route *code*, not a URL. This maps the codes
 * the API emits onto the redesigned member-space paths, so a task card always
 * lands somewhere real instead of falling back to the dashboard.
 */
const ROUTE_CODES: Record<string, string> = {
  "user.account": "account/profile",
  "user.experience-home": "account/home",
  "user.tasks": "account/tasks",
  "user.journeys": "account/journeys",
  "user.notifications": "account/notifications",
  "user.activities": "account/activities",
  "user.my-activities": "account/activities",
  "user.courses": "account/courses",
  "user.my-courses": "account/courses",
  "user.counseling": "account/counseling",
  "user.orders": "account/orders",
  "user.safety": "account/safety",
  "user.privacy": "account/privacy",
  "user.membership": "account/membership",
  "user.dating-profile": "account/dating-profile",
  "user.recommendations": "recommendations",
  "user.matchmaking": "account/matchmaking/matches",
  "user.invitations": "account/matchmaking/invitations",
  "user.relationships": "account/relationships",
  "user.ai-assistant": "ai-assistant",
  "user.help": "help"
};

export function useExperienceRoutes() {
  const { localePath, locale } = useLocalePath();

  function pathFor(row: ExperienceRow) {
    const code = String(row.action_route_code ?? row.route_code ?? row.fallback_route_code ?? "");
    const mapped = ROUTE_CODES[code];
    if (mapped) return localePath(mapped);
    const raw = String(row.route_path ?? "");
    if (raw.startsWith("/")) return raw.replace("{locale}", locale.value);
    return localePath("account/home");
  }

  function localized(value: unknown) {
    const map = value as Record<string, string> | undefined;
    return map?.[locale.value] ?? map?.["zh-CN"] ?? "";
  }

  function titleOf(row: ExperienceRow) {
    return (
      localized(row.title_i18n) ||
      String(row.title ?? row.task_code ?? row.journey_code ?? row.document_code ?? "")
    );
  }

  function descriptionOf(row: ExperienceRow) {
    return (
      localized(row.description_i18n) ||
      String(row.summary ?? row.body_markdown ?? row.current_step_code ?? "")
    );
  }

  return { pathFor, localized, titleOf, descriptionOf, localePath };
}
