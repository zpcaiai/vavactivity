/**
 * Single source of truth for the operator console navigation.
 *
 * Before this module the sidebar was a flat list of 30 links while the router
 * declared 250+ routes: every module's sections were reachable only through
 * hand-rolled tab strips inside each page, each shaped differently. Groups,
 * modules and sections now live here, and both the shell and the router read
 * from the same structure — a section cannot exist in the router and be
 * missing from navigation, or vice versa.
 */

export interface AdminSection {
  key: string;
  labelKey: string;
  permission?: string;
}

export interface AdminModule {
  key: string;
  labelKey: string;
  /** Route path prefix, e.g. `/admin/notifications`. */
  base: string;
  /** Landing section key; the first permitted section is used when omitted. */
  landing?: string;
  permission?: string;
  sections: AdminSection[];
}

export interface AdminGroup {
  key: string;
  labelKey: string;
  glyph: string;
  modules: AdminModule[];
}

const section = (key: string, permission?: string): AdminSection => ({
  key,
  labelKey: `section.${key}`,
  permission
});

export const notificationSectionPermissions: Record<string, string> = {
  dashboard: "notifications.analytics.read",
  templates: "notifications.templates.read",
  "template-releases": "notifications.templates.read",
  "event-subscriptions": "notifications.subscriptions.read",
  deliveries: "notifications.deliveries.read",
  "dead-letters": "notifications.dead_letters.read",
  reminders: "notifications.reminders.read",
  campaigns: "notifications.campaigns.read",
  providers: "notifications.providers.read",
  "provider-events": "notifications.providers.read",
  suppressions: "notifications.suppressions.read",
  audit: "notifications.audit.read"
};

export const matchmakingSectionPermissions: Record<string, string> = {
  profiles: "matchmaking.profiles.read",
  reviews: "matchmaking.reviews.read",
  "photo-reviews": "matchmaking.photos.read",
  "schema-releases": "matchmaking.schemas.read",
  taxonomies: "matchmaking.taxonomies.read",
  projections: "matchmaking.projections.read",
  audit: "matchmaking.audit.read"
};

export const recommendationSectionPermissions: Record<string, string> = {
  dashboard: "recommendations.analytics.read",
  strategies: "recommendations.strategies.read",
  features: "recommendations.features.read",
  constraints: "recommendations.constraints.read",
  batches: "recommendations.batches.read",
  candidates: "recommendations.candidates.read",
  diagnostics: "recommendations.diagnostics.run",
  "pair-diagnostics": "recommendations.candidates.sensitive.read",
  exposures: "recommendations.exposures.read",
  "cold-start": "recommendations.analytics.read",
  feedback: "recommendations.feedback.read",
  evaluations: "recommendations.evaluations.read",
  experiments: "recommendations.experiments.read",
  incidents: "recommendations.incidents.read",
  audit: "recommendations.audit.read"
};

export const interactionSectionPermissions: Record<string, string> = {
  dashboard: "matchmaking.analytics.read",
  pairs: "matchmaking.interactions.read",
  matches: "matchmaking.matches.read",
  invitations: "matchmaking.invitations.read",
  "contact-exchanges": "matchmaking.contact_exchange.read",
  invalidations: "matchmaking.interactions.read",
  "dead-letters": "matchmaking.dead_letters.resolve",
  incidents: "matchmaking.incidents.read",
  audit: "matchmaking.audit.read"
};

export const relationshipSectionPermissions: Record<string, string> = {
  dashboard: "relationships.analytics.read",
  journeys: "relationships.read",
  stages: "relationships.stages.read",
  proposals: "relationships.proposals.read",
  pauses: "relationships.pauses.read",
  endings: "relationships.endings.read",
  milestones: "relationships.milestones.read",
  checkins: "relationships.checkins.read",
  reminders: "relationships.reminders.read",
  audit: "relationships.audit.read"
};

export const membershipSectionPermissions: Record<string, string> = {
  dashboard: "memberships.analytics.read",
  plans: "memberships.plans.read",
  "plan-versions": "memberships.plans.read",
  benefits: "memberships.benefits.read",
  "sku-mappings": "memberships.sku_mappings.read",
  accounts: "memberships.accounts.read",
  cycles: "memberships.accounts.read",
  changes: "memberships.changes.read",
  quotas: "memberships.quotas.read",
  usage: "memberships.quotas.read",
  adjustments: "memberships.quotas.read",
  "manual-grants": "memberships.manual_grants.read",
  trials: "memberships.trials.read",
  reconciliation: "memberships.reconciliation.read",
  audit: "memberships.audit.read"
};

export const safetySectionPermissions: Record<string, string> = {
  reports: "safety.reports.read",
  cases: "safety.cases.read",
  moderation: "safety.moderation.read",
  harassment: "safety.analytics.read",
  fraud: "safety.analytics.read",
  restrictions: "safety.restrictions.read",
  appeals: "safety.appeals.read",
  rules: "safety.rules.read",
  "red-team": "safety.red_team.read",
  audit: "safety.audit.read"
};

export const systemSectionPermissions: Record<string, string> = {
  status: "system.status.read",
  releases: "system.releases.read",
  jobs: "system.jobs.read",
  integrations: "system.status.read",
  "dead-letters": "system.dead_letters.read",
  "feature-flags": "system.feature_flags.read",
  maintenance: "system.maintenance.read",
  backups: "system.backups.read",
  "restore-drills": "system.restore_drills.read",
  capacity: "system.capacity.read"
};

export const skillSectionPermissions: Record<string, string> = {
  dashboard: "skills.analytics.read",
  catalog: "skills.registry.read",
  installations: "skills.installations.read",
  executions: "skills.executions.read",
  dependencies: "skills.registry.read",
  permissions: "skills.permissions.read",
  configurations: "skills.installations.read",
  publishers: "skills.publishers.read",
  reviews: "skills.marketplace.review",
  marketplace: "skills.marketplace.read",
  incidents: "skills.incidents.read",
  audit: "skills.audit.read"
};

export const qualitySectionPermissions: Record<string, string> = {
  dashboard: "quality.analytics.read",
  requirements: "quality.requirements.read",
  capabilities: "quality.capabilities.read",
  traceability: "quality.traceability.read",
  "business-flows": "quality.business_flows.read",
  gaps: "quality.gaps.read",
  risks: "quality.risks.read",
  waivers: "quality.waivers.read",
  evidence: "quality.evidence.read",
  gates: "quality.gates.read",
  "gate-runs": "quality.gates.read",
  releases: "quality.releases.read",
  certifications: "quality.releases.read",
  audit: "quality.audit.read"
};

export const designSystemSectionPermissions: Record<string, string> = {
  dashboard: "design.analytics.read",
  tokens: "design.tokens.read",
  components: "design.components.read",
  patterns: "design.patterns.read",
  pages: "design.audits.read",
  accessibility: "design.accessibility.read",
  "responsive-audits": "design.audits.read",
  "visual-regression": "design.audits.read",
  baselines: "design.baselines.read",
  evidence: "design.evidence.read",
  releases: "design.tokens.read",
  audit: "design.audit.read"
};

export const experienceSectionPermissions: Record<string, string> = {
  dashboard: "experience.analytics.read",
  ia: "experience.ia.read",
  routes: "experience.routes.read",
  navigation: "experience.navigation.read",
  tasks: "experience.tasks.read",
  journeys: "experience.journeys.read",
  handoffs: "experience.handoffs.read",
  "search-governance": "experience.search.read",
  help: "experience.help.read",
  support: "experience.support.read",
  "dead-ends": "experience.dead_ends.read",
  analytics: "experience.analytics.read",
  evidence: "experience.closure.read",
  release: "experience.closure.read",
  audit: "experience.audit.read"
};

export const processSectionPermissions: Record<string, string> = {
  dashboard: "process.dashboard.read",
  definitions: "process.definitions.read",
  "state-machines": "process.state_machines.read",
  instances: "process.instances.read",
  sagas: "process.sagas.read",
  timeouts: "process.timeouts.read",
  cancellations: "process.cancellations.read",
  compensations: "process.compensations.read",
  stuck: "process.stuck.read",
  interventions: "process.interventions.read",
  simulations: "process.simulations.read",
  certifications: "process.certifications.read",
  release: "process.release.read"
};

export const dataGovernanceSectionPermissions: Record<string, string> = {
  dashboard: "data.dashboard.read",
  assets: "data.assets.read",
  contracts: "data.contracts.read",
  lineage: "data.lineage.read",
  events: "data.events.read",
  "event-gaps": "data.events.read",
  "dead-letters": "data.dead_letters.read",
  quality: "data.quality.read",
  reconciliations: "data.reconciliations.read",
  differences: "data.reconciliations.read",
  backfills: "data.backfills.read",
  repairs: "data.repairs.read",
  projections: "data.projections.read",
  erasures: "data.erasures.read",
  certifications: "data.certifications.read",
  release: "data.release.read"
};

export const adminPlatformSectionPermissions: Record<string, string> = {
  dashboard: "admin.workbench.read",
  capabilities: "admin.capabilities.read",
  "work-items": "admin.workbench.read",
  "saved-views": "admin.saved_views.read",
  "bulk-jobs": "admin.bulk.read",
  approvals: "admin.approvals.read",
  exceptions: "admin.exceptions.read",
  configurations: "admin.configurations.read",
  "field-access": "admin.fields.policies.read",
  "reveal-history": "admin.fields.policies.read",
  certifications: "admin.certifications.read",
  releases: "admin.certifications.read",
  audit: "admin.audit.read"
};

export const privacySectionPermissions: Record<string, string> = {
  dashboard: "privacy.requests.read",
  requests: "privacy.requests.read",
  exports: "privacy.exports.read",
  corrections: "privacy.corrections.read",
  erasures: "privacy.erasures.read",
  consents: "privacy.consents.read",
  "consent-releases": "privacy.consents.read",
  inventory: "privacy.inventory.read",
  processing: "privacy.inventory.read",
  classifications: "privacy.classifications.read",
  retention: "privacy.retention.read",
  "retention-instances": "privacy.retention.read",
  holds: "privacy.holds.read",
  "break-glass": "privacy.break_glass.read",
  "access-events": "privacy.sensitive_access.read",
  incidents: "privacy.incidents.read",
  audit: "privacy.audit.read"
};

function sectionsOf(permissions: Record<string, string>): AdminSection[] {
  return Object.entries(permissions).map(([key, permission]) => section(key, permission));
}

const commerceSections: AdminSection[] = [
  section("orders", "commerce.orders.read"),
  section("payments", "commerce.payments.read"),
  section("subscriptions", "commerce.subscriptions.read"),
  section("refunds", "commerce.refunds.read"),
  section("webhooks", "commerce.webhooks.read"),
  section("reconciliation", "commerce.reconciliation.read"),
  section("entitlements", "commerce.entitlements.read")
];

const catalogSections: AdminSection[] = [
  section("categories", "catalog.products.read"),
  section("products", "catalog.products.read"),
  section("price-books", "catalog.price_books.read"),
  section("prices", "catalog.prices.read"),
  section("inventory", "catalog.inventory.read"),
  section("promotions", "catalog.promotions.read"),
  section("coupons", "catalog.coupons.read")
];

const contentSections: AdminSection[] = [
  section("pages", "content.pages.read"),
  section("articles", "content.articles.read"),
  section("testimonials", "content.testimonials.read"),
  section("media", "content.media.read"),
  section("navigation", "content.navigation.read"),
  section("contact-submissions", "contact.submissions.read"),
  section("settings", "content.settings.read")
];

const accessSections: AdminSection[] = [
  section("admins", "admins.read"),
  section("roles", "roles.read"),
  section("permissions", "roles.read"),
  section("invitations", "admins.read")
];

export const adminGroups: AdminGroup[] = [
  {
    key: "workbench",
    labelKey: "group.workbench",
    glyph: "◎",
    modules: [
      { key: "dashboard", labelKey: "menu.dashboard", base: "/admin/dashboard", sections: [] },
      {
        key: "platform",
        labelKey: "menu.adminPlatform",
        base: "/admin/platform",
        landing: "dashboard",
        permission: "admin.workbench.read",
        sections: sectionsOf(adminPlatformSectionPermissions)
      }
    ]
  },
  {
    key: "content",
    labelKey: "group.content",
    glyph: "▤",
    modules: [
      {
        key: "content",
        labelKey: "menu.pages",
        base: "/admin/content",
        landing: "pages",
        permission: "content.pages.read",
        sections: contentSections
      }
    ]
  },
  {
    key: "commerce",
    labelKey: "group.commerce",
    glyph: "◈",
    modules: [
      {
        key: "catalog",
        labelKey: "menu.catalog",
        base: "/admin/catalog",
        landing: "products",
        permission: "catalog.products.read",
        sections: catalogSections
      },
      {
        key: "commerce",
        labelKey: "menu.commerce",
        base: "/admin/commerce",
        landing: "orders",
        permission: "commerce.orders.read",
        sections: commerceSections
      },
      {
        key: "memberships",
        labelKey: "menu.memberships",
        base: "/admin/memberships",
        landing: "dashboard",
        permission: "memberships.analytics.read",
        sections: sectionsOf(membershipSectionPermissions)
      }
    ]
  },
  {
    key: "operations",
    labelKey: "group.operations",
    glyph: "✦",
    modules: [
      { key: "activities", labelKey: "menu.activities", base: "/admin/activities", permission: "activities.read", sections: [] },
      { key: "courses", labelKey: "menu.courses", base: "/admin/courses", permission: "courses.read", sections: [] },
      { key: "counseling", labelKey: "menu.counseling", base: "/admin/counseling", permission: "counseling.appointments.read", sections: [] },
      { key: "knowledge", labelKey: "menu.knowledge", base: "/admin/knowledge", permission: "knowledge.spaces.read", sections: [] },
      { key: "ai", labelKey: "menu.ai", base: "/admin/ai", permission: "ai.conversations.read", sections: [] },
      {
        key: "notifications",
        labelKey: "menu.notifications",
        base: "/admin/notifications",
        landing: "dashboard",
        permission: "notifications.analytics.read",
        sections: sectionsOf(notificationSectionPermissions)
      }
    ]
  },
  {
    key: "matchmaking",
    labelKey: "group.matchmaking",
    glyph: "❤",
    modules: [
      {
        key: "matchmaking",
        labelKey: "menu.matchmaking",
        base: "/admin/matchmaking",
        landing: "profiles",
        permission: "matchmaking.profiles.read",
        sections: sectionsOf(matchmakingSectionPermissions)
      },
      {
        key: "recommendations",
        labelKey: "menu.recommendations",
        base: "/admin/recommendations",
        landing: "dashboard",
        permission: "recommendations.analytics.read",
        sections: sectionsOf(recommendationSectionPermissions)
      },
      {
        key: "matchmaking-interactions",
        labelKey: "menu.interactions",
        base: "/admin/matchmaking-interactions",
        landing: "dashboard",
        permission: "matchmaking.analytics.read",
        sections: sectionsOf(interactionSectionPermissions)
      },
      {
        key: "relationships",
        labelKey: "menu.relationships",
        base: "/admin/relationships",
        landing: "dashboard",
        permission: "relationships.analytics.read",
        sections: sectionsOf(relationshipSectionPermissions)
      }
    ]
  },
  {
    key: "trust",
    labelKey: "group.trust",
    glyph: "⛨",
    modules: [
      {
        key: "trust-safety",
        labelKey: "menu.trustSafety",
        base: "/admin/trust-safety",
        landing: "reports",
        permission: "safety.reports.read",
        sections: sectionsOf(safetySectionPermissions)
      },
      {
        key: "privacy",
        labelKey: "menu.privacy",
        base: "/admin/privacy",
        landing: "dashboard",
        permission: "privacy.requests.read",
        sections: sectionsOf(privacySectionPermissions)
      },
      { key: "users", labelKey: "menu.users", base: "/admin/users", permission: "users.read", sections: [] },
      {
        key: "access",
        labelKey: "menu.admins",
        base: "/admin/access",
        landing: "admins",
        permission: "admins.read",
        sections: accessSections
      },
      {
        key: "audit",
        labelKey: "menu.audit",
        base: "/admin/audit",
        landing: "auth",
        permission: "audit.read",
        sections: [section("auth", "audit.read"), section("permissions", "audit.read")]
      }
    ]
  },
  {
    key: "governance",
    labelKey: "group.governance",
    glyph: "⚙",
    modules: [
      {
        key: "system",
        labelKey: "menu.system",
        base: "/admin/system",
        landing: "status",
        permission: "system.status.read",
        sections: sectionsOf(systemSectionPermissions)
      },
      {
        key: "quality",
        labelKey: "menu.quality",
        base: "/admin/quality",
        landing: "dashboard",
        permission: "quality.analytics.read",
        sections: sectionsOf(qualitySectionPermissions)
      },
      {
        key: "design-system",
        labelKey: "menu.designSystem",
        base: "/admin/design-system",
        landing: "dashboard",
        permission: "design.analytics.read",
        sections: sectionsOf(designSystemSectionPermissions)
      },
      {
        key: "experience",
        labelKey: "menu.experience",
        base: "/admin/experience",
        landing: "dashboard",
        permission: "experience.analytics.read",
        sections: sectionsOf(experienceSectionPermissions)
      },
      {
        key: "processes",
        labelKey: "menu.processes",
        base: "/admin/processes",
        landing: "dashboard",
        permission: "process.dashboard.read",
        sections: sectionsOf(processSectionPermissions)
      },
      {
        key: "data-governance",
        labelKey: "menu.dataGovernance",
        base: "/admin/data-governance",
        landing: "dashboard",
        permission: "data.dashboard.read",
        sections: sectionsOf(dataGovernanceSectionPermissions)
      },
      {
        key: "skills",
        labelKey: "menu.skills",
        base: "/admin/skills",
        landing: "dashboard",
        permission: "skills.analytics.read",
        sections: sectionsOf(skillSectionPermissions)
      }
    ]
  }
];

/** Resolve the module that owns a path, used for breadcrumbs and section nav. */
export function moduleForPath(path: string): { group: AdminGroup; module: AdminModule } | undefined {
  for (const group of adminGroups) {
    for (const module of group.modules) {
      if (path === module.base || path.startsWith(`${module.base}/`)) {
        return { group, module };
      }
    }
  }
  return undefined;
}

/** First section the operator may actually open, or the module base. */
export function landingPath(module: AdminModule, can: (permission: string) => boolean) {
  if (!module.sections.length) return module.base;
  const preferred = module.sections.find((item) => item.key === module.landing);
  const target =
    preferred && (!preferred.permission || can(preferred.permission))
      ? preferred
      : module.sections.find((item) => !item.permission || can(item.permission));
  return target ? `${module.base}/${target.key}` : module.base;
}
