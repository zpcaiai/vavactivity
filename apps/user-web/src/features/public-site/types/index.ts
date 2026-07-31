export interface ContentBlock {
  id: string;
  type: string;
  version: number;
  data: Record<string, unknown>;
}

export interface PublicContent {
  id: string;
  entry_type: string;
  canonical_slug: string;
  published_at: string | null;
  locale: string;
  fallback_used: boolean;
  title: string;
  subtitle?: string;
  excerpt?: string;
  content_blocks: ContentBlock[];
  seo_title?: string;
  seo_description?: string;
}
