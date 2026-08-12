/**
 * Recommendation operations centre API client.
 *
 * Operators supervise the engine. This module deliberately exposes no call that
 * could force two members together, hand-edit a score, bypass a hard constraint
 * or read a member's private preference list — those endpoints do not exist and
 * no helper here fabricates them.
 */
import { catalogApi } from "@/features/catalog/api";

const BASE = "/admin/recommendations";

export type Row = Record<string, unknown> & { id?: string; status?: string };

export type DashboardSummary = {
  pool: { eligible: number; total: number };
  candidate_pairs: { eligible: number; total: number };
  batches: {
    total: number;
    active: number;
    failed: number;
    average_size: number;
    empty_batches: number;
  };
  exposure: ExposureOverview;
  feedback: FeedbackSummary;
  cold_start_users: number;
};

export type ExposureOverview = {
  eligible_profiles: number;
  exposed_profiles: number;
  coverage_ratio_bps: number;
  exposure_gini_bps: number;
  never_exposed_profiles: number;
};

export type FeedbackSummary = {
  counts_by_type: Record<string, number>;
  total_events: number;
  negative_events: number;
  report_events: number;
  block_events: number;
};

export type ColdStartSummary = {
  eligible_profiles: number;
  sparse_preference_members: number;
  new_profiles: number;
  never_exposed_profiles: number;
};

export type CandidateOverview = {
  pairs_by_status: Record<string, number>;
  active_exclusions: Record<string, number>;
};

export type ExposureReport = {
  overview: ExposureOverview;
  most_exposed_profiles: Array<{ total_exposures: number; last_exposed_at: string | null }>;
};

export type FeatureDefinition = {
  feature_code: string;
  semantic_version: string;
  feature_group: string;
  scoring_function_code: string;
  sensitivity: string;
  explainable: boolean;
  user_configurable: boolean;
  criterion_code: string | null;
  similarity_code: string | null;
  default_weight: number;
  confidence_only: boolean;
  status: string;
};

export type ConstraintPolicy = {
  supported_criteria: string[];
  policy: Record<string, unknown> | null;
};

export type StrategyDetail = {
  strategy: Row;
  evaluations: Row[];
};

export type BatchDetail = {
  batch: Row;
  rank_results: Row[];
};

/** Aggregate funnel diagnostics: counts and criterion codes only. */
export type UserDiagnostics = {
  pool_entry: Row | null;
  generation_report: Record<string, unknown>;
  cold_start: Record<string, unknown>;
  empty_result_report: Record<string, unknown>;
};

/** Pair diagnostics: feature codes, results and versions — never profile values. */
export type PairDiagnostics = {
  pair: {
    id: string;
    status: string;
    strategy_id: string;
    low_profile_projection_version: number | null;
    high_profile_projection_version: number | null;
    low_preference_version: number | null;
    high_preference_version: number | null;
    valid_until: string | null;
    invalidation_reason: string | null;
  };
  hard_constraints: {
    passed: boolean | null;
    blocking_codes: string[];
    unknown_codes: string[];
    relaxed_codes: string[];
    policy_version: string | null;
  };
  directional_scores: Array<
    Row & {
      feature_scores: Array<{
        feature_code: string;
        raw_match_bps: number;
        importance_weight: number;
        information_available: boolean;
      }>;
    }
  >;
  score_snapshot: Record<string, unknown> | null;
};

export const recommendationApi = {
  dashboard: () => catalogApi<DashboardSummary>(`${BASE}/dashboard`),

  listStrategies: () => catalogApi<{ strategies: Row[] }>(`${BASE}/strategies`),
  /**
   * A strategy carries eight policy documents. Authoring them field by field in
   * a form would be a worse source of truth than the strategy that is already
   * live, so the console clones an existing version and bumps the code/version;
   * the policies stay editable as JSON for the cases that need a real change.
   */
  createStrategy: (payload: Record<string, unknown>) =>
    catalogApi<Row>(`${BASE}/strategies`, { method: "POST", body: JSON.stringify(payload) }),
  getStrategy: (strategyId: string) =>
    catalogApi<StrategyDetail>(`${BASE}/strategies/${strategyId}`),
  transitionStrategy: (
    strategyId: string,
    action: "approve" | "activate" | "rollback",
    reason: string
  ) =>
    catalogApi<{ status: string; restored_strategy_id?: string | null }>(
      `${BASE}/strategies/${strategyId}/${action}`,
      { method: "POST", body: JSON.stringify({ reason }) }
    ),

  listFeatures: () => catalogApi<{ features: FeatureDefinition[] }>(`${BASE}/features`),
  constraints: () => catalogApi<ConstraintPolicy>(`${BASE}/constraints`),

  listBatches: () => catalogApi<{ batches: Row[] }>(`${BASE}/batches`),
  getBatch: (batchId: string) => catalogApi<BatchDetail>(`${BASE}/batches/${batchId}`),
  invalidateBatch: (batchId: string, reason: string) =>
    catalogApi<{ invalidated: boolean }>(`${BASE}/batches/${batchId}/invalidate`, {
      method: "POST",
      body: JSON.stringify({ reason })
    }),
  rebuildUser: (userId: string, reason: string) =>
    catalogApi<{ batch_id: string; generated_size: number }>(`${BASE}/users/${userId}/rebuild`, {
      method: "POST",
      body: JSON.stringify({ reason, batch_type: "manual_rebuild" })
    }),

  candidates: () => catalogApi<CandidateOverview>(`${BASE}/candidates`),
  userDiagnostics: (userId: string) =>
    catalogApi<UserDiagnostics>(`${BASE}/users/${userId}/diagnostics`),
  pairDiagnostics: (pairId: string) => catalogApi<PairDiagnostics>(`${BASE}/pairs/${pairId}`),

  exposures: () => catalogApi<ExposureReport>(`${BASE}/exposures`),
  coldStart: () => catalogApi<ColdStartSummary>(`${BASE}/cold-start`),
  feedback: () => catalogApi<FeedbackSummary>(`${BASE}/feedback`),

  listEvaluations: () => catalogApi<{ runs: Row[] }>(`${BASE}/evaluations`),
  runEvaluation: (datasetCode: string, strategyId: string) =>
    catalogApi<Record<string, unknown>>(`${BASE}/evaluations`, {
      method: "POST",
      body: JSON.stringify({ dataset_code: datasetCode, strategy_id: strategyId, metrics: {} })
    }),

  listExperiments: () => catalogApi<{ experiments: Row[] }>(`${BASE}/experiments`),
  createExperiment: (payload: Record<string, unknown>) =>
    catalogApi<Row>(`${BASE}/experiments`, { method: "POST", body: JSON.stringify(payload) }),
  transitionExperiment: (
    experimentId: string,
    action: "approve" | "start" | "stop",
    reason: string
  ) =>
    catalogApi<{ status: string }>(`${BASE}/experiments/${experimentId}/${action}`, {
      method: "POST",
      body: JSON.stringify({ reason })
    }),
  checkGuardrails: (experimentId: string) =>
    catalogApi<Record<string, unknown>>(`${BASE}/experiments/${experimentId}/guardrails`, {
      method: "POST",
      body: JSON.stringify({ metrics: {} })
    }),

  incidents: () => catalogApi<{ incidents: Row[] }>(`${BASE}/incidents`),
  audit: () => catalogApi<{ events: Row[] }>(`${BASE}/audit`)
};
