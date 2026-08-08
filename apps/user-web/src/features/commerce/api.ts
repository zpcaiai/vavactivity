import { useAuthStore } from "@/stores/auth";
import { resolveApiBaseUrl } from "@/config/api";

const baseUrl = resolveApiBaseUrl();

export interface CartItem {
  id: string;
  sku_id: string;
  quantity: number;
  coupon_code?: string | null;
}

export interface Cart {
  id: string;
  status: string;
  currency: string;
  version: number;
  items: CartItem[];
}

export interface Order {
  id: string;
  order_number: string;
  status: string;
  currency: string;
  total_minor: number;
  refunded_total_minor: number;
  placed_at?: string | null;
  items?: Array<{
    id: string;
    product_name: string;
    sku_name: string;
    quantity: number;
    total_minor: number;
  }>;
  payments?: Payment[];
  entitlements?: Entitlement[];
}

export interface Payment {
  id: string;
  provider: string;
  environment: string;
  status: string;
  client_action?: { type?: string; url?: string; test_only?: boolean } | null;
}

export interface Entitlement {
  id: string;
  order_id: string;
  type: string;
  status: string;
  quantity_granted?: number | null;
  quantity_consumed: number;
  expires_at?: string | null;
}

export interface Subscription {
  id: string;
  status: string;
  provider: string;
  currency: string;
  amount_minor: number;
  billing_interval: string;
  current_period_end?: string | null;
  cancel_at_period_end: boolean;
}

export interface CheckoutPreview {
  cart_id: string;
  currency: string;
  subtotal_minor: number;
  discount_total_minor: number;
  total_minor: number;
  quote_expires_at: string;
  available_payment_providers: string[];
}

export function anonymousSessionId() {
  const key = "vav_anonymous_session_id";
  let value = localStorage.getItem(key);
  if (!value) {
    value = crypto.randomUUID();
    localStorage.setItem(key, value);
  }
  return value;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  query?: Record<string, string | undefined>
): Promise<T> {
  const auth = useAuthStore();
  await auth.bootstrap();
  const url = new URL(`${baseUrl}${path}`, window.location.origin);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value) {
      url.searchParams.set(key, value);
    }
  }
  const headers = new Headers(init.headers);
  if (auth.accessToken) {
    headers.set("Authorization", `Bearer ${auth.accessToken}`);
  }
  if (init.body) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(url, { ...init, credentials: "include", headers });
  const payload = (await response.json()) as {
    data: T;
    error?: { code: string; message: string };
  };
  if (!response.ok) {
    throw new Error(payload.error?.message ?? "Commerce request failed");
  }
  return payload.data;
}

export const commerceApi = {
  getCart: (currency = "USD") =>
    request<Cart>("/cart", {}, {
      anonymous_session_id: anonymousSessionId(),
      currency_code: currency
    }),
  addItem: (skuId: string, quantity: number, currency: string, couponCode?: string) =>
    request<Cart>("/cart/items", {
      method: "POST",
      body: JSON.stringify({
        sku_id: skuId,
        quantity,
        currency_code: currency,
        coupon_code: couponCode || null,
        anonymous_session_id: anonymousSessionId()
      })
    }),
  updateItem: (item: CartItem, cart: Cart, quantity: number) =>
    request<Cart>(
      `/cart/items/${item.id}`,
      {
        method: "PATCH",
        body: JSON.stringify({
          quantity,
          coupon_code: item.coupon_code ?? null,
          expected_version: cart.version
        })
      },
      { anonymous_session_id: anonymousSessionId() }
    ),
  removeItem: (itemId: string) =>
    request<Cart>(`/cart/items/${itemId}`, { method: "DELETE" }, {
      anonymous_session_id: anonymousSessionId()
    }),
  preview: (cartId: string, locale: string) =>
    request<CheckoutPreview>("/checkout/preview", {
      method: "POST",
      body: JSON.stringify({
        cart_id: cartId,
        anonymous_session_id: anonymousSessionId(),
        locale,
        region_code: null
      })
    }),
  createOrder: (
    cartId: string,
    locale: string,
    email: string,
    total: number,
    idempotencyKey: string
  ) =>
    request<Order>("/checkout/orders", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({
        cart_id: cartId,
        anonymous_session_id: anonymousSessionId(),
        billing_email: email,
        locale,
        region_code: null,
        expected_total_minor: total,
        terms_version: "undecided-v1",
        privacy_version: "undecided-v1",
        refund_policy_version: "undecided-v1"
      })
    }),
  createPayment: (orderNumber: string, provider: string, idempotencyKey: string) =>
    request<Payment>(`/orders/${orderNumber}/payments`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ provider })
    }),
  orders: () => request<{ items: Order[] }>("/orders"),
  order: (number: string) => request<Order>(`/orders/${number}`),
  entitlements: () => request<{ items: Entitlement[] }>("/entitlements"),
  subscriptions: () => request<{ items: Subscription[] }>("/subscriptions"),
  cancelSubscription: (id: string) =>
    request<Subscription>(`/subscriptions/${id}/cancel`, {
      method: "POST",
      body: JSON.stringify({ immediate: false, reason: "User requested period-end cancellation" })
    })
};
