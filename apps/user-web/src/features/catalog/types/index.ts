import type { ContentBlock } from "@/features/public-site/types";

export interface CatalogPrice {
  price_id: string;
  currency: string;
  unit_amount_minor: number;
  compare_at_amount_minor: number | null;
  billing_type: "one_time" | "recurring" | "free";
  billing_interval: string | null;
  billing_interval_count: number | null;
}

export interface Availability {
  status: "available" | "low_stock" | "sold_out";
  inventory_policy: string;
  available_quantity: number | null;
}

export interface CatalogSku {
  id: string;
  sku_code: string;
  billing_type: string;
  service_quantity: number | null;
  service_unit: string | null;
  entitlement_definition: Record<string, unknown>;
  purchase_limit_per_user: number | null;
  prices: CatalogPrice[];
  availability: Availability;
}

export interface CatalogProduct {
  id: string;
  product_code: string;
  product_type: string;
  fulfillment_type: string;
  category_id: string | null;
  featured: boolean;
  purchasable_from: string | null;
  purchasable_until: string | null;
  locale: string;
  fallback_used: boolean;
  slug: string;
  name: string;
  short_description: string | null;
  description_blocks: ContentBlock[];
  seo_title: string | null;
  seo_description: string | null;
  cover_media_id: string | null;
  skus: CatalogSku[];
}

export interface PricingQuote {
  quote_id: string;
  sku_id: string;
  quantity: number;
  currency: string;
  unit_amount_minor: number;
  subtotal_minor: number;
  discounts: Array<{
    promotion_code: string;
    discount_type: string;
    discount_amount_minor: number;
    description: string;
  }>;
  discount_total_minor: number;
  tax_estimate_minor: number | null;
  total_minor: number;
  inventory_reservation_required: boolean;
  expires_at: string;
  payment_status: "not_paid";
  grants_entitlement: false;
}
