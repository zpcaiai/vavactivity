/**
 * Single source of truth for the member-space information architecture.
 *
 * The redesign groups routes by *user journey* (overview / matchmaking /
 * growth / billing / account) rather than by backend module. Everything that
 * renders navigation — sidebar, mobile tab bar, dashboard shortcuts and the
 * command palette — reads from here, so a route can never appear in one place
 * and be missing from another.
 */

export type AppSpace = "public" | "app" | "focus" | "auth";

export interface IaItem {
  key: string;
  /** i18n key under `ia.items`. */
  labelKey: string;
  /** Path relative to the locale prefix, without a leading slash. */
  path: string;
  /** Requires the account to be flagged as single (V1.6 matchmaking gate). */
  singlesOnly?: boolean;
  /** Requires a verified email address. */
  verifiedOnly?: boolean;
  /** Highlight as an obligation rather than a destination. */
  critical?: boolean;
  /** Match the path exactly instead of by prefix. */
  exact?: boolean;
}

export interface IaGroup {
  key: string;
  labelKey: string;
  glyph: string;
  /** Landing route for the group. */
  path: string;
  singlesOnly?: boolean;
  items: IaItem[];
}

export const appIa: IaGroup[] = [
  {
    key: "overview",
    labelKey: "ia.groups.overview",
    glyph: "◎",
    path: "account/home",
    items: [
      { key: "home", labelKey: "ia.items.home", path: "account/home", exact: true },
      { key: "tasks", labelKey: "ia.items.tasks", path: "account/tasks" },
      { key: "journeys", labelKey: "ia.items.journeys", path: "account/journeys" },
      { key: "notifications", labelKey: "ia.items.notifications", path: "account/notifications" }
    ]
  },
  {
    key: "matchmaking",
    labelKey: "ia.groups.matchmaking",
    glyph: "❤",
    path: "recommendations",
    singlesOnly: true,
    items: [
      { key: "profile", labelKey: "ia.items.datingProfile", path: "account/dating-profile", verifiedOnly: true },
      { key: "recommendations", labelKey: "ia.items.recommendations", path: "recommendations", singlesOnly: true },
      { key: "matches", labelKey: "ia.items.matches", path: "account/matchmaking/matches", verifiedOnly: true },
      { key: "invitations", labelKey: "ia.items.invitations", path: "account/matchmaking/invitations", verifiedOnly: true },
      { key: "likes", labelKey: "ia.items.likes", path: "account/matchmaking/likes", verifiedOnly: true },
      { key: "relationships", labelKey: "ia.items.relationships", path: "account/relationships", verifiedOnly: true }
    ]
  },
  {
    key: "growth",
    labelKey: "ia.groups.growth",
    glyph: "✦",
    path: "account/activities",
    items: [
      { key: "activities", labelKey: "ia.items.myActivities", path: "account/activities" },
      { key: "courses", labelKey: "ia.items.myCourses", path: "account/courses" },
      { key: "counseling", labelKey: "ia.items.myCounseling", path: "account/counseling" },
      { key: "ai", labelKey: "ia.items.aiAssistant", path: "ai-assistant" }
    ]
  },
  {
    key: "billing",
    labelKey: "ia.groups.billing",
    glyph: "◈",
    path: "account/orders",
    items: [
      { key: "orders", labelKey: "ia.items.orders", path: "account/orders" },
      { key: "subscriptions", labelKey: "ia.items.subscriptions", path: "account/subscriptions" },
      { key: "entitlements", labelKey: "ia.items.entitlements", path: "account/entitlements" },
      { key: "membership", labelKey: "ia.items.membership", path: "account/membership" }
    ]
  },
  {
    key: "account",
    labelKey: "ia.groups.account",
    glyph: "☰",
    path: "account/profile",
    items: [
      { key: "profile", labelKey: "ia.items.profile", path: "account/profile" },
      { key: "notificationPreferences", labelKey: "ia.items.notificationPreferences", path: "account/notification-preferences" },
      { key: "privacy", labelKey: "ia.items.privacy", path: "account/privacy", critical: true },
      { key: "safety", labelKey: "ia.items.safety", path: "account/safety", critical: true },
      { key: "sessions", labelKey: "ia.items.sessions", path: "account/sessions", verifiedOnly: true }
    ]
  }
];

/** Bottom tab bar on small screens: one entry per journey group. */
export const mobileTabs = appIa.map((group) => ({
  key: group.key,
  labelKey: group.labelKey,
  glyph: group.glyph,
  path: group.path,
  singlesOnly: group.singlesOnly
}));

/** Marketing-site navigation shown to signed-out and signed-in visitors alike. */
export const publicIa: IaItem[] = [
  { key: "activities", labelKey: "ia.public.activities", path: "activities" },
  { key: "courses", labelKey: "ia.public.courses", path: "courses" },
  { key: "counseling", labelKey: "ia.public.counseling", path: "counseling" },
  { key: "membership", labelKey: "ia.public.membership", path: "membership" },
  { key: "stories", labelKey: "ia.public.stories", path: "stories" },
  { key: "articles", labelKey: "ia.public.articles", path: "articles" },
  { key: "about", labelKey: "ia.public.about", path: "about" }
];

export interface IaContext {
  /** `undefined` means "unknown"; the gate only closes on an explicit value. */
  relationshipStatus?: string | null;
  emailVerified: boolean;
}

export function isSingle(context: IaContext) {
  const status = context.relationshipStatus;
  if (status === undefined || status === null || status === "") return true;
  return status === "single";
}

export function isItemVisible(item: IaItem, context: IaContext) {
  if (item.singlesOnly && !isSingle(context)) return false;
  if (item.verifiedOnly && !context.emailVerified) return false;
  return true;
}

export function isGroupVisible(group: IaGroup, context: IaContext) {
  if (group.singlesOnly && !isSingle(context)) return false;
  return true;
}
