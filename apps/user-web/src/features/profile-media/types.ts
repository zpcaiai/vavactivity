/**
 * Profile media types (B15 PROFILE-001).
 *
 * Three contract facts this UI must not paper over:
 *
 * - `media_path` is derived from an opaque token, never from the asset id. The
 *   client must use the path the server returns and never construct one.
 * - Every share consent flag defaults to `false`. Nothing is shareable until
 *   the member switches it on.
 * - The share card *omits* a field entirely rather than sending `null`, so a
 *   consumer cannot infer "this member has a video but hid it". Optional keys
 *   below are therefore genuinely absent, not nullable.
 */

export type MediaKind = "photo" | "video";
export type AssetState = "uploading" | "active" | "replaced" | "deleted";
export type ModerationState = "pending" | "approved" | "rejected";

export interface MediaAsset {
  asset_id: string;
  kind: MediaKind;
  state: AssetState;
  moderation_state: ModerationState;
  rejection_reason_code: string | null;
  position: number | null;
  duration_seconds: number | null;
  /**
   * The asset's logical identity, token-derived. It is deliberately NOT a
   * fetchable URL — private media is only readable through a short-lived URL
   * issued after API authorization, so binding this to a `src` yields a broken
   * image.
   */
  media_path: string;
  is_publishable: boolean;
}

export interface ProfileMediaView {
  assets: MediaAsset[];
  pending_assets: MediaAsset[];
  mbti: string | null;
  intro: string | null;
  city_code: string | null;
  completeness_percent: number;
  /** Machine codes for what is still missing; localized in the UI. */
  completeness_missing: string[];
  is_published: boolean;
}

/** A signed storage POST policy. Fields are sent verbatim, file appended last. */
export interface UploadPolicy {
  url: string;
  method: "POST";
  fields: Record<string, string>;
  /** The ceiling storage itself enforces — not advice. */
  max_bytes: number;
  expires_in_seconds: number;
}

interface BaseUploadTarget {
  asset_id: string;
  /** Logical identity of the asset. Not fetchable; do not use as a `src`. */
  upload_path: string;
  upload: UploadPolicy;
  upload_expires_at: string;
  moderation_state: ModerationState;
}

export interface UploadTarget extends BaseUploadTarget {
  state: AssetState;
}

/** A new staged asset that will replace the named active asset at finalize. */
export interface ReplacementUploadTarget extends BaseUploadTarget {
  replaced_asset_id: string;
}

export interface DeleteAssetResult {
  asset_id: string;
  remaining_photos: number;
  profile_falls_below_minimum: boolean;
}

export interface MediaGrant {
  /** Logical identity. Not fetchable — see `media_url`. */
  media_path: string;
  /**
   * The short-lived, fetchable storage URL. This is a bearer URL: the API made
   * a viewer-specific authorization decision before issuing it, but storage
   * does not re-authenticate the viewer on each GET.
   */
  media_url: string;
  expires_at: string;
  signature: string;
  /** Echoes the viewer the API authorized before issuing this response. */
  viewer_id: string;
}

export interface ShareConsent {
  share_enabled: boolean;
  share_photos: boolean;
  share_video: boolean;
  share_mbti: boolean;
  share_intro: boolean;
  share_city: boolean;
}

export interface ProfileShareCard {
  user_id: string;
  display_name: string;
  completeness_percent: number;
  /** Absent — not null — when photos are not consented or not approved. */
  photo_tokens?: string[];
  video_token?: string;
  mbti?: string;
  intro?: string;
  city_code?: string;
}
