/**
 * Safely parse a fetch Response as JSON.
 *
 * If the server returns an HTML page (e.g. a Vercel 404 / SPA fallback) instead
 * of a JSON API response, calling `response.json()` directly would throw:
 *   "Unexpected token '<', "<!doctype "... is not valid JSON"
 *
 * This helper reads the body as text first, detects HTML, and throws a
 * human-readable error so the caller can display it instead of crashing.
 */

export class ApiNotAvailableError extends Error {
  constructor(url: string) {
    super(
      `服务暂时不可用（${url}）。` +
      `请检查 VITE_API_BASE_URL 是否已指向真实后端地址。`
    );
    this.name = "ApiNotAvailableError";
  }
}

export async function safeJsonResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  const ct = response.headers.get("content-type") ?? "";

  const isHtml =
    text.trimStart().startsWith("<!") ||
    text.trimStart().toLowerCase().startsWith("<html") ||
    ct.includes("text/html");

  if (isHtml) {
    throw new ApiNotAvailableError(response.url);
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error(`无效的 API 响应（${response.url}）：${text.slice(0, 120)}`);
  }

  return parsed as T;
}
