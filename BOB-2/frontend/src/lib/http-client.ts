/**
 * Centralized HTTP client for GuardianAI backend.
 *
 * Implements:
 * - Dependency Inversion Principle: UI components depend on this abstraction,
 *   not on raw `fetch()` or on specific URLs.
 * - Single Responsibility: handles transport concerns (auth headers, token
 *   refresh, error normalization, JSON parsing) only.
 * - Open/Closed: add new behaviors (retry, logging, telemetry) without
 *   touching call sites.
 */

import { API_BASE_URL } from "@/lib/api";

// --- Public types --------------------------------------------------------

export interface ApiClientConfig {
  baseUrl: string;
  getAccessToken: () => string | null;
  getRefreshToken: () => string | null;
  onSessionInvalid: () => void;
  onTokensRefreshed: (access: string, refresh: string) => void;
}

export class ApiError extends Error {
  public readonly status: number;
  public readonly details: unknown;

  constructor(message: string, status: number, details: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

// --- Public API endpoints whitelist (no Authorization required) ---------

const PUBLIC_AUTH_PATHS: readonly string[] = [
  "/api/v1/auth/login",
  "/api/v1/auth/refresh",
  "/api/v1/auth/mfa/verify",
  "/api/v1/auth/password-reset/request",
  "/api/v1/auth/password-reset/confirm",
  "/api/v1/auth/register",
];

function isPublicAuthPath(path: string): boolean {
  return PUBLIC_AUTH_PATHS.some((p) => path.includes(p));
}

// --- The client ----------------------------------------------------------

export class ApiClient {
  private readonly config: ApiClientConfig;
  private refreshInFlight: Promise<string | null> | null = null;

  constructor(config: ApiClientConfig) {
    this.config = config;
  }

  /**
   * Build the full URL for a backend path. Public so tests can assert against
   * it without exercising the network.
   */
  public buildUrl(path: string): string {
    if (path.startsWith("http://") || path.startsWith("https://")) {
      return path;
    }
    const normalized = path.startsWith("/") ? path : `/${path}`;
    return `${this.config.baseUrl}${normalized}`;
  }

  /**
   * Issue a typed JSON request. Returns parsed body on success.
   * Throws ApiError with normalized detail message on failure.
   */
  public async request<T>(
    path: string,
    init: RequestInit = {},
  ): Promise<T> {
    const url = this.buildUrl(path);
    const headers = new Headers(init.headers);

    if (init.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }

    // Attach Authorization header for non-public auth paths.
    const isPublic = isPublicAuthPath(path) || url.endsWith("/health");
    if (!isPublic) {
      const accessToken = this.config.getAccessToken();
      if (accessToken) {
        headers.set("Authorization", `Bearer ${accessToken}`);
      }
    }

    const response = await fetch(url, {
      ...init,
      headers,
      cache: init.cache ?? "no-store",
    });

    // Try transparent token refresh on 401.
    if (
      response.status === 401 &&
      !isPublic &&
      this.config.getRefreshToken()
    ) {
      const rotated = await this.refreshAccessToken();
      if (rotated) {
        const retryHeaders = new Headers(headers);
        retryHeaders.set("Authorization", `Bearer ${rotated}`);
        const retryResponse = await fetch(url, { ...init, headers: retryHeaders });
        return this.parseResponse<T>(retryResponse);
      }
      this.config.onSessionInvalid();
    }

    return this.parseResponse<T>(response);
  }

  // --- Convenience helpers (one per public endpoint family) ------------

  public login(email: string, password: string) {
    return this.request<{
      access_token: string | null;
      refresh_token: string | null;
      role: string;
      mfa_required?: boolean;
      mfa_token?: string | null;
    }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  }

  public requestPasswordReset(email: string) {
    return this.request<{ message: string }>(
      "/api/v1/auth/password-reset/request",
      { method: "POST", body: JSON.stringify({ email }) },
    );
  }

  public confirmPasswordReset(token: string, newPassword: string) {
    return this.request<{ message: string }>(
      "/api/v1/auth/password-reset/confirm",
      { method: "POST", body: JSON.stringify({ token, new_password: newPassword }) },
    );
  }

  public verifyMfa(mfaToken: string, code: string) {
    return this.request<{
      access_token: string;
      refresh_token: string;
      role: string;
    }>("/api/v1/auth/mfa/verify", {
      method: "POST",
      body: JSON.stringify({ mfa_token: mfaToken, code }),
    });
  }

  public register(input: {
    inviteToken: string;
    email: string;
    fullName: string;
    password: string;
  }) {
    return this.request<{ message: string }>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({
        invite_token: input.inviteToken,
        email: input.email,
        full_name: input.fullName,
        password: input.password,
      }),
    });
  }

  // --- Internals --------------------------------------------------------

  private async refreshAccessToken(): Promise<string | null> {
    if (this.refreshInFlight) return this.refreshInFlight;

    const refreshToken = this.config.getRefreshToken();
    if (!refreshToken) return null;

    this.refreshInFlight = (async () => {
      try {
        const response = await fetch(this.buildUrl("/api/v1/auth/refresh"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
          cache: "no-store",
        });
        if (!response.ok) return null;
        const data = (await response.json()) as {
          access_token: string;
          refresh_token: string;
        };
        this.config.onTokensRefreshed(data.access_token, data.refresh_token);
        return data.access_token;
      } catch {
        return null;
      } finally {
        this.refreshInFlight = null;
      }
    })();

    return this.refreshInFlight;
  }

  private async parseResponse<T>(response: Response): Promise<T> {
    const body = await this.safeJson(response);

    if (!response.ok) {
      const detail =
        typeof body === "object" && body !== null && "detail" in body
          ? String((body as { detail?: unknown }).detail || "")
          : "";
      throw new ApiError(
        detail || `Request failed with status ${response.status}.`,
        response.status,
        body,
      );
    }

    return body as T;
  }

  private async safeJson(response: Response): Promise<unknown> {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      return response.json().catch(() => null);
    }
    return response.text().catch(() => null);
  }
}

// --- Singleton instance --------------------------------------------------

let clientInstance: ApiClient | null = null;

export function getApiClient(): ApiClient {
  if (!clientInstance) {
    clientInstance = new ApiClient({
      baseUrl: API_BASE_URL,
      getAccessToken: () => sessionStorage.getItem("guardian_access_token"),
      getRefreshToken: () => sessionStorage.getItem("guardian_refresh_token"),
      onSessionInvalid: () => {
        sessionStorage.removeItem("guardian_access_token");
        sessionStorage.removeItem("guardian_refresh_token");
        sessionStorage.removeItem("guardian_role");
      },
      onTokensRefreshed: (access, refresh) => {
        sessionStorage.setItem("guardian_access_token", access);
        sessionStorage.setItem("guardian_refresh_token", refresh);
      },
    });
  }
  return clientInstance;
}

// --- Backwards compatibility for existing code --------------------------

/**
 * @deprecated Prefer getApiClient().request(...) — direct fetch usage
 * bypasses the abstraction and breaks test isolation.
 */
export async function requestJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  return getApiClient().request<T>(path, init);
}

export { ApiError as SettingsApiError };
