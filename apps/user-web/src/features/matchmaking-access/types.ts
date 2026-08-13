/**
 * Matchmaking eligibility and entitlement types (B12).
 *
 * `matchmaking_available` is the server's verdict, not something the client
 * derives from `status`. Deriving it locally would let the two drift, and the
 * whole point of MATCH-001 is that one rule decides everywhere.
 */

export type RelationshipStatusValue =
  | "undisclosed"
  | "single"
  | "dating"
  | "engaged"
  | "married"
  | "separated"
  | "widowed";

export type RelationshipStatusSource = "self_declared" | "couple_binding" | "admin";

export interface RelationshipStatus {
  user_id: string;
  status: RelationshipStatusValue;
  source: RelationshipStatusSource;
  couple_relationship_id?: string | null;
  declared_at?: string | null;
  effective_from?: string | null;
  version: number;
  matchmaking_available: boolean;
}

export interface EntitlementLedgerEntry {
  delta: number;
  reason: "grant" | "consume" | "refund" | "expire" | "admin_adjust";
  balance_after: number;
  note: string | null;
  created_at: string;
}

export interface MatchmakingEntitlement {
  granted: number;
  consumed: number;
  balance: number;
  expires_at: string | null;
  policy_version: string;
  max_candidates_per_attempt: number;
  ledger: EntitlementLedgerEntry[];
}

export interface MatchmakingDisclaimer {
  disclaimer_code: string;
  semantic_version: string;
  locale: string;
  body: string;
}

export interface GenerationResult {
  /** False when nothing new was found — no attempt was spent. */
  consumed: boolean;
  reason_code: string;
  batch_id?: string;
  candidates: string[];
  balance: number;
  wait_pool: boolean;
  disclaimer: MatchmakingDisclaimer | null;
}

export interface WaitPoolState {
  status: "not_in_pool" | "waiting" | "notified" | "exited";
  entered_at?: string;
  last_notified_at?: string | null;
  notify_count?: number;
  exited_at?: string | null;
  exit_reason?: string | null;
}
