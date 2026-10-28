import { clearTokens, getAccessToken, getRefreshToken, setAccessToken, setRefreshToken } from "./tokenStore";

// `||` (not `??`): the Docker build / .env.example set this to an empty string, which must fall back to the relative default.
const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api/v1";

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

/** Set by AuthProvider so the client can force a logout+redirect on an
 * unrecoverable 401 (refresh also failed) without a circular import. */
let onSessionExpired: (() => void) | null = null;
export function registerSessionExpiredHandler(handler: () => void): void {
  onSessionExpired = handler;
}

let refreshPromise: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;

  // Coalesce concurrent 401s into a single refresh call.
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const res = await fetch(`${API_BASE}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!res.ok) return false;
        const data = await res.json();
        if (!data?.access_token) return false;
        setAccessToken(data.access_token);
        setRefreshToken(data.refresh_token);
        return true;
      } catch {
        return false;
      } finally {
        refreshPromise = null;
      }
    })();
  }
  return refreshPromise;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  params?: Record<string, string | number | boolean | undefined>;
}

function buildUrl(path: string, params?: RequestOptions["params"]): string {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
    }
  }
  // Return the full absolute URL, not just pathname+search: when API_BASE
  // is itself absolute (a separate API host, e.g. in production), dropping
  // the origin here would silently redirect every request back to the
  // frontend's own origin instead of the API host. Returning the full href
  // works correctly for both a relative API_BASE (default "/api/v1", same
  // origin) and an absolute one.
  return url.toString();
}

async function parseErrorBody(res: Response): Promise<{ code: string; message: string }> {
  try {
    const data = await res.json();
    if (data?.error?.code && data?.error?.message) {
      return { code: data.error.code, message: data.error.message };
    }
    if (data?.detail) {
      // FastAPI's own 422 validation-error shape
      const detail = Array.isArray(data.detail)
        ? data.detail.map((d: { msg?: string }) => d.msg).join("; ")
        : String(data.detail);
      return { code: "VALIDATION_ERROR", message: detail };
    }
  } catch {
    /* fall through */
  }
  return { code: "UNKNOWN", message: `Request failed (${res.status})` };
}

export async function apiRequest<T>(path: string, opts: RequestOptions = {}, _retried = false): Promise<{ data: T; totalCount: number | null }> {
  const url = buildUrl(path, opts.params);
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getAccessToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(url, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });

  if (res.status === 401 && !_retried) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      return apiRequest<T>(path, opts, true);
    }
    clearTokens();
    onSessionExpired?.();
    const errBody = await parseErrorBody(res);
    throw new ApiError(401, errBody.code, "Your session has expired. Please log in again.");
  }

  if (!res.ok) {
    const errBody = await parseErrorBody(res);
    throw new ApiError(res.status, errBody.code, errBody.message);
  }

  const totalCountHeader = res.headers.get("X-Total-Count");
  const totalCount = totalCountHeader ? parseInt(totalCountHeader, 10) : null;

  // Some endpoints (logout, approve/reject) return small ack bodies; all return JSON.
  const ctype = res.headers.get("Content-Type") || "";
  if (res.status !== 204 && ctype && !ctype.includes("json")) {
    // Typical misconfiguration: VITE_API_BASE_URL unset on a static host, so the SPA fallback answers /api/v1/* with index.html.
    throw new ApiError(res.status, "API_UNREACHABLE", "Cannot reach the API (received a non-JSON response). Check the API base URL configuration.");
  }
  const data = (await res.json().catch(() => null)) as T;
  return { data, totalCount };
}

export const api = {
  get: <T,>(path: string, params?: RequestOptions["params"]) => apiRequest<T>(path, { method: "GET", params }),
  post: <T,>(path: string, body?: unknown, params?: RequestOptions["params"]) =>
    apiRequest<T>(path, { method: "POST", body, params }),
  patch: <T,>(path: string, body?: unknown) => apiRequest<T>(path, { method: "PATCH", body }),
  put: <T,>(path: string, body?: unknown) => apiRequest<T>(path, { method: "PUT", body }),
  delete: <T,>(path: string) => apiRequest<T>(path, { method: "DELETE" }),
};
