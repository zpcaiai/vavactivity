import type { PublicContent } from "../types";

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export interface PublicNavigationItem {
  id: string;
  label: string;
  link_type: "route" | "external" | "content";
  external_url: string | null;
  route_name: string | null;
  target_slug: string | null;
  open_in_new_tab: boolean;
  required_auth: boolean;
}

export async function getNavigation(menuCode: string, locale: string) {
  const response = await fetch(
    `${baseUrl}/public/navigation/${encodeURIComponent(menuCode)}` +
      `?locale=${encodeURIComponent(locale)}`
  );
  const payload = (await response.json()) as {
    data?: { items: PublicNavigationItem[] };
    error?: { code: string };
  };
  if (!response.ok) {
    throw new Error(payload.error?.code ?? "NAVIGATION_LOAD_FAILED");
  }
  return payload.data?.items ?? [];
}

export async function getPage(slug: string, locale: string) {
  return getContent(`/public/content/pages/${encodeURIComponent(slug)}`, locale);
}

export async function getArticle(slug: string, locale: string) {
  return getContent(`/public/articles/${encodeURIComponent(slug)}`, locale);
}

export async function getTestimonial(slug: string, locale: string) {
  return getContent(`/public/testimonials/${encodeURIComponent(slug)}`, locale);
}

export async function listArticles(locale: string) {
  return listContent("/public/articles", locale);
}

export async function listTestimonials(locale: string) {
  return listContent("/public/testimonials", locale);
}

async function listContent(path: string, locale: string) {
  const response = await fetch(`${baseUrl}${path}?locale=${encodeURIComponent(locale)}`);
  const payload = (await response.json()) as {
    data?: { items: PublicContent[] };
    error?: { code: string };
  };
  if (!response.ok) {
    throw new Error(payload.error?.code ?? "CONTENT_LOAD_FAILED");
  }
  return payload.data?.items ?? [];
}

async function getContent(path: string, locale: string) {
  const response = await fetch(`${baseUrl}${path}?locale=${encodeURIComponent(locale)}`);
  const payload = (await response.json()) as {
    data?: PublicContent;
    error?: { code: string };
  };
  if (!response.ok) {
    if (payload.error?.code === "CONTENT_NOT_FOUND") {
      return null;
    }
    throw new Error(payload.error?.code ?? "CONTENT_LOAD_FAILED");
  }
  return payload.data ?? null;
}
