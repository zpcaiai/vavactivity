/**
 * Section catalogue for the recommendation operations centre.
 *
 * Each entry is `[section, label, permission]`. The router mirrors this list in
 * `recommendationSectionPermissions`; the unit test keeps both in step.
 *
 * `pair-diagnostics` is intentionally gated on the separate sensitive
 * permission: it is the only surface that reveals per-pair feature codes, and
 * it still shows codes, pass/fail results, adjustments and versions only.
 */
export const recommendationSections = [
  ["dashboard", "总览", "recommendations.analytics.read"],
  ["strategies", "策略版本", "recommendations.strategies.read"],
  ["features", "特征注册表", "recommendations.features.read"],
  ["constraints", "硬性条件", "recommendations.constraints.read"],
  ["batches", "推荐批次", "recommendations.batches.read"],
  ["candidates", "候选统计", "recommendations.candidates.read"],
  ["diagnostics", "漏斗诊断", "recommendations.diagnostics.run"],
  ["pair-diagnostics", "配对诊断（敏感）", "recommendations.candidates.sensitive.read"],
  ["exposures", "曝光公平", "recommendations.exposures.read"],
  ["cold-start", "冷启动", "recommendations.analytics.read"],
  ["feedback", "反馈聚合", "recommendations.feedback.read"],
  ["evaluations", "离线评估", "recommendations.evaluations.read"],
  ["experiments", "实验", "recommendations.experiments.read"],
  ["incidents", "异常信号", "recommendations.incidents.read"],
  ["audit", "推荐审计", "recommendations.audit.read"]
] as const;

export type RecommendationSection = (typeof recommendationSections)[number][0];

/** The section whose data requires the separate sensitive permission. */
export const RECOMMENDATION_SENSITIVE_SECTION = "pair-diagnostics";

/** Permission guarding the sensitive pair-diagnostics surface. */
export const RECOMMENDATION_SENSITIVE_PERMISSION = "recommendations.candidates.sensitive.read";
