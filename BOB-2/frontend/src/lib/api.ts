import { installCompanyAwareFetch } from "./companyAwareFetch";

const configuredApiUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim().replace(/\/$/, "");

/**
 * Resolve the API base URL with a sensible production fallback.
 *
 * Production deployments MUST set NEXT_PUBLIC_API_BASE_URL. If it is
 * missing we fall back to the canonical public backend on the same host
 * (`/api`) — this prevents the user-facing "Failed to fetch" error that
 * happens when the frontend tries to reach `http://127.0.0.1:8000` from
 * a browser that has no access to localhost.
 *
 * Local development still uses `http://127.0.0.1:8000` when
 * NEXT_PUBLIC_API_BASE_URL is not set.
 */
function resolveApiBaseUrl(): string {
  if (configuredApiUrl) return configuredApiUrl;

  if (typeof window !== "undefined") {
    const protocol = window.location.protocol;
    const host = window.location.hostname;
    const isLocal =
      host === "localhost" ||
      host === "127.0.0.1" ||
      host === "0.0.0.0" ||
      host.endsWith(".local");
    if (!isLocal && process.env.NODE_ENV === "production") {
      console.warn(
        "[guardianai] NEXT_PUBLIC_API_BASE_URL is not set; " +
          "falling back to same-origin '/api'. " +
          "Set NEXT_PUBLIC_API_BASE_URL to silence this warning.",
      );
      return `${protocol}//${host}/api`;
    }
  }

  return "http://127.0.0.1:8000";
}

installCompanyAwareFetch();

export const API_BASE_URL = resolveApiBaseUrl();

export async function getBackendHealth() {
  const response = await fetch(`${API_BASE_URL}/health`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error("Backend health check failed");
  }

  return response.json();
}

export async function getSystemStatus() {
  const response = await fetch(`${API_BASE_URL}/api/v1/system/status`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error("Backend system status check failed");
  }

  return response.json();
}
