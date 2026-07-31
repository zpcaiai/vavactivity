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
  fetchImpl?: typeof fetch;
}

export function createApiClient(options: ApiClientOptions) {
  const fetchImpl = options.fetchImpl ?? fetch;

  return async function request<T>(
    path: string,
    init: RequestInit = {}
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
      headers
    });
    const body = (await response.json()) as T | ApiErrorBody;
    if (!response.ok) {
      const failure = body as ApiErrorBody;
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

