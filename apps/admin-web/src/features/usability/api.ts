import { catalogApi } from "@/features/catalog/api";

export type UsabilityRow = Record<string, unknown> & { id?: string; status?: string };

export const ENVIRONMENTS = ["local", "ci", "demo", "staging", "production"] as const;

/** Step statuses accepted by complete_uat; anything else is a 422 server-side. */
export const STEP_STATUSES = ["not_run", "passed", "failed", "blocked", "skipped"] as const;

/** Overall run outcome accepted by UatRunComplete. */
export const RUN_OUTCOMES = ["passed", "failed", "blocked"] as const;

/**
 * The six dimensions certification_status() requires. A missing key makes the
 * backend return `rejected` outright, so the console always sends all six.
 */
export const CERTIFICATION_DIMENSIONS = [
  "uat",
  "compatibility",
  "localization",
  "draft",
  "notification",
  "import_export"
] as const;

export type CertificationDimension = (typeof CERTIFICATION_DIMENSIONS)[number];

export const DIMENSION_STATUSES = [
  "passed",
  "failed",
  "blocked",
  "not_run",
  "in_progress",
  "needs_retest"
] as const;

/**
 * Dimensions the module can prove from its own tables. usability_uat_runs,
 * usability_compatibility_runs and usability_localization_runs all carry
 * release_version + environment + status, so the console computes these three
 * and shows them read-only.
 *
 * The other three cannot be derived and the console must not pretend otherwise:
 * usability_user_drafts and usability_import_jobs carry no release/environment,
 * and usability_notification_qa_cases is a case catalogue with no result table
 * at all. Those stay operator assertions, defaulted to not_run.
 */
export const DERIVED_DIMENSIONS: CertificationDimension[] = [
  "uat",
  "compatibility",
  "localization"
];

export const ASSERTED_DIMENSIONS: CertificationDimension[] = [
  "draft",
  "notification",
  "import_export"
];

export interface UatRunCreate {
  scenario_code: string;
  environment: string;
  release_version: string;
  locale: string;
  device_profile: string;
}

export interface UatStepResult {
  status: string;
  observation?: string;
  error_code?: string | null;
  duration_ms?: number | null;
}

export interface UatRunComplete {
  status: string;
  step_results: UatStepResult[];
  evidence_refs: string[];
}

export interface ImportPreview {
  import_code: string;
  source_file_ref: string;
  rows: Record<string, unknown>[];
  idempotency_key: string;
  dry_run: boolean;
}

export interface CertificationEvaluate {
  business_domain: string;
  release_version: string;
  environment: string;
  results: Record<string, string>;
  unresolved_critical_findings: number;
  evidence_refs: string[];
}

const base = "/admin/usability";

export const usabilityApi = {
  dashboard: () => catalogApi<Record<string, unknown>>(`${base}/dashboard`),
  section: (section: string) =>
    catalogApi<UsabilityRow[]>(`${base}/${encodeURIComponent(section)}`),

  startUat: (payload: UatRunCreate) =>
    catalogApi<UsabilityRow>(`${base}/uat/runs`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),

  completeUat: (runId: string, payload: UatRunComplete) =>
    catalogApi<UsabilityRow>(`${base}/uat/runs/${encodeURIComponent(runId)}/complete`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),

  previewImport: (payload: ImportPreview) =>
    catalogApi<UsabilityRow>(`${base}/imports/preview`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),

  evaluateCertification: (payload: CertificationEvaluate) =>
    catalogApi<UsabilityRow>(`${base}/certifications/evaluate`, {
      method: "POST",
      body: JSON.stringify(payload)
    })
};

function asList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item));
  return [];
}

/** Locales a scenario actually declares; start_uat 422s on anything else. */
export function scenarioLocales(scenario: UsabilityRow | undefined): string[] {
  return asList(scenario?.required_locales);
}

export function scenarioDevices(scenario: UsabilityRow | undefined): string[] {
  return asList(scenario?.required_device_profiles);
}

/** complete_uat rejects a result list whose length differs from the scenario. */
export function scenarioSteps(scenario: UsabilityRow | undefined): Record<string, unknown>[] {
  const steps = scenario?.steps;
  if (Array.isArray(steps)) return steps.map((item) => (item && typeof item === "object" ? (item as Record<string, unknown>) : { text: String(item) }));
  return [];
}

export interface DerivedDimension {
  status: string;
  matched: number;
  failed: number;
  blocked: number;
  pending: number;
}

/**
 * Fold the runs of one dimension into a single status for a release/environment.
 * Deliberately pessimistic: a failure anywhere fails the dimension, and an
 * unfinished run degrades it to not_run rather than passing it.
 */
export function deriveDimension(
  rows: UsabilityRow[],
  releaseVersion: string,
  environment: string
): DerivedDimension {
  const matched = rows.filter(
    (row) =>
      String(row.release_version ?? "") === releaseVersion &&
      String(row.environment ?? "") === environment
  );
  const failed = matched.filter((row) => String(row.status) === "failed").length;
  const blocked = matched.filter((row) => String(row.status) === "blocked").length;
  const pending = matched.filter(
    (row) => !["passed", "failed", "blocked"].includes(String(row.status))
  ).length;
  let status = "not_run";
  if (!matched.length) status = "not_run";
  else if (failed) status = "failed";
  else if (blocked) status = "blocked";
  else if (pending) status = "not_run";
  else status = "passed";
  return { status, matched: matched.length, failed, blocked, pending };
}

/**
 * Mirror of the backend's certification_status(). Kept in the console so the
 * operator sees the verdict before submitting rather than after — the endpoint
 * upserts, so a careless submit overwrites an existing evaluation.
 */
export function certificationStatus(
  results: Record<string, string>,
  unresolvedCriticalFindings: number
): string {
  const allowed = new Set(DIMENSION_STATUSES as readonly string[]);
  const values = CERTIFICATION_DIMENSIONS.map((key) => results[key]);
  if (values.some((value) => !value || !allowed.has(value))) return "rejected";
  if (unresolvedCriticalFindings > 0) return "rejected";
  if (values.some((value) => ["failed", "blocked", "needs_retest", "in_progress"].includes(value)))
    return "rejected";
  if (values.every((value) => value === "passed")) return "certified";
  return "eligible";
}

/**
 * Minimal RFC4180-ish parser. Import previews are validated server-side against
 * the registered schema, so this only needs to turn a file into row objects
 * faithfully — including quoted fields containing commas and newlines.
 */
export function parseCsv(input: string): Record<string, unknown>[] {
  const text = input.replace(/^\uFEFF/u, "");
  const records: string[][] = [];
  let field = "";
  let record: string[] = [];
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"') {
        if (text[index + 1] === '"') {
          field += '"';
          index += 1;
        } else quoted = false;
      } else field += char;
      continue;
    }
    if (char === '"') quoted = true;
    else if (char === ",") {
      record.push(field);
      field = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[index + 1] === "\n") index += 1;
      record.push(field);
      records.push(record);
      record = [];
      field = "";
    } else field += char;
  }
  if (field.length || record.length) {
    record.push(field);
    records.push(record);
  }
  const rows = records.filter((item) => item.some((cell) => cell.trim().length));
  if (rows.length < 2) return [];
  const header = rows[0].map((cell) => cell.trim());
  return rows.slice(1).map((cells) => {
    const row: Record<string, unknown> = {};
    header.forEach((key, position) => {
      if (key) row[key] = cells[position] ?? "";
    });
    return row;
  });
}
