export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: unknown[];
  };
  meta: { request_id: string };
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly requestId: string,
    public readonly details: unknown[] = []
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ApiClientOptions {
  baseUrl: string;
  getAccessToken?: () => string | undefined;
  refreshAccessToken?: () => Promise<boolean>;
  fetchImpl?: typeof fetch;
}

export function createApiClient(options: ApiClientOptions) {
  const fetchImpl = options.fetchImpl ?? fetch;
  let refreshPromise: Promise<boolean> | undefined;

  return async function request<T>(
    path: string,
    init: RequestInit = {},
    alreadyRetried = false
  ): Promise<T> {
    const token = options.getAccessToken?.();
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    headers.set("X-Request-ID", crypto.randomUUID());
    if (init.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }

    const response = await fetchImpl(`${options.baseUrl}${path}`, {
      ...init,
      credentials: init.credentials ?? "include",
      headers
    });
    const body = (await response.json()) as T | ApiErrorBody;
    if (!response.ok) {
      const failure = body as ApiErrorBody;
      if (
        !alreadyRetried &&
        options.refreshAccessToken &&
        response.status === 401 &&
        ["TOKEN_EXPIRED", "AUTH_SESSION_INVALID"].includes(failure.error?.code)
      ) {
        refreshPromise ??= options.refreshAccessToken().finally(() => {
          refreshPromise = undefined;
        });
        if (await refreshPromise) {
          return request<T>(path, init, true);
        }
      }
      throw new ApiError(
        response.status,
        failure.error?.code ?? "HTTP_ERROR",
        failure.error?.message ?? response.statusText,
        failure.meta?.request_id ?? response.headers.get("X-Request-ID") ?? "unknown",
        failure.error?.details ?? []
      );
    }
    return body as T;
  };
}
