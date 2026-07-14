const configuredApiUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim().replace(/\/$/, "");

if (!configuredApiUrl && process.env.NODE_ENV === "production") {
  throw new Error("NEXT_PUBLIC_API_BASE_URL is required for production builds");
}

export const API_BASE_URL = configuredApiUrl || "http://127.0.0.1:8000";

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
