const configured = import.meta.env.VITE_API_BASE_URL?.trim();
const normalizedConfigured = configured?.replace(/\/+$/, "") ?? "";

function isLocalhostHost(host: string): boolean {
  return host === "localhost" || host === "127.0.0.1" || host === "::1";
}

export function isApiBaseUrlConfigured(): boolean {
  return normalizedConfigured.length > 0;
}

export function resolveApiBaseUrl(): string {
  if (isApiBaseUrlConfigured()) {
    return normalizedConfigured;
  }
  const { hostname, origin } = window.location;
  if (import.meta.env.DEV || isLocalhostHost(hostname)) {
    return "/api/v1";
  }
  return `${origin.replace(/\/+$/, "")}/api/v1`;
}

export function explainApiConnectionError(operation: string, baseUrl: string): string {
  if (isApiBaseUrlConfigured()) {
    return `${operation} 失败：无法连接 ${baseUrl}，请检查网络与跨域配置。`;
  }
  return `${operation} 失败：VITE_API_BASE_URL 未配置，当前会回退请求 ${baseUrl}。\n` +
    "请在部署环境中设置正确的 VITE_API_BASE_URL（例如 https://api.example.com/api/v1），\n" +
    "并确保域名可达。";
}
