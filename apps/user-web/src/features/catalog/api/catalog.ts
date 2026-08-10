import type { CatalogProduct, PricingQuote } from "../types";
import { resolveApiBaseUrl } from "@/config/api";

const baseUrl = resolveApiBaseUrl();

interface ApiEnvelope<T> {
  data: T;
  error?: { code: string; message: string; details?: unknown[] };
}

async function request<T>(path: string, init?: Parameters<typeof fetch>[1]): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, init);
  const payload = (await response.json()) as ApiEnvelope<T>;
  if (!response.ok) {
    const error = new Error(payload.error?.message ?? "服务目录请求失败");
    error.name = payload.error?.code ?? "CATALOG_REQUEST_FAILED";
    throw error;
  }
  return payload.data;
}

export async function listProducts(options: {
  locale: string;
  currency: string;
  category?: string;
  productType?: string;
}) {
  const params = new URLSearchParams({
    locale: options.locale,
    currency: options.currency,
    available_only: "false"
  });
  if (options.category) {
    params.set("category", options.category);
  }
  if (options.productType) {
    params.set("product_type", options.productType);
  }
  return request<{ items: CatalogProduct[] }>(
    `/public/catalog/products?${params.toString()}`
  );
}

export async function getProduct(slug: string, locale: string, currency: string) {
  const params = new URLSearchParams({ locale, currency });
  return request<CatalogProduct>(
    `/public/catalog/products/${encodeURIComponent(slug)}?${params.toString()}`
  );
}

export async function listCurrencies() {
  return request<{ items: Array<{ currency_code: string; exponent: number }> }>(
    "/public/catalog/currencies"
  );
}

export async function createQuote(input: {
  skuId: string;
  quantity: number;
  currency: string;
  locale: string;
  couponCode?: string;
}) {
  return request<PricingQuote>("/public/catalog/pricing/quote", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sku_id: input.skuId,
      quantity: input.quantity,
      requested_currency: input.currency,
      locale: input.locale,
      anonymous_session_id: anonymousSessionId(),
      coupon_code: input.couponCode || null,
      pricing_context: {
        channel: "user_web",
        requested_at: new Date().toISOString()
      }
    })
  });
}

export function anonymousSessionId() {
  const key = "vav.anonymous-session-id";
  const existing = window.localStorage.getItem(key);
  if (existing) {
    return existing;
  }
  const created = crypto.randomUUID();
  window.localStorage.setItem(key, created);
  return created;
}
