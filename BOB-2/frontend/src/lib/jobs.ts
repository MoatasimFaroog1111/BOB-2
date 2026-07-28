import { API_BASE_URL } from "@/lib/api";

type QueuedJob = {
  status: "queued";
  job_id: string;
};

type JobStatus<T> = {
  status: "queued" | "running" | "completed" | "failed";
  error_code?: string | null;
  result?: T | null;
};

const DEFAULT_POLL_INTERVAL_MS = 750;
const DEFAULT_TIMEOUT_MS = 15 * 60 * 1000;

function errorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    if (typeof record.detail === "string" && record.detail) return record.detail;
    if (typeof record.error_code === "string" && record.error_code) return record.error_code;
  }
  return fallback;
}

export async function resolveJobResponse<T>(
  response: Response,
  options: { pollIntervalMs?: number; timeoutMs?: number } = {},
): Promise<T> {
  const initial = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(errorMessage(initial, `Request failed (${response.status})`));
  }

  if (response.status !== 202 || !initial || typeof initial.job_id !== "string") {
    return initial as T;
  }

  const queued = initial as QueuedJob;
  const pollIntervalMs = options.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    await new Promise((resolve) => window.setTimeout(resolve, pollIntervalMs));
    const statusResponse = await fetch(`${API_BASE_URL}/api/v1/jobs/${encodeURIComponent(queued.job_id)}`, {
      cache: "no-store",
    });
    const statusPayload = (await statusResponse.json().catch(() => null)) as JobStatus<T> | null;
    if (!statusResponse.ok) {
      throw new Error(errorMessage(statusPayload, `Job status failed (${statusResponse.status})`));
    }
    if (!statusPayload) continue;
    if (statusPayload.status === "completed") {
      if (statusPayload.result === null || statusPayload.result === undefined) {
        throw new Error("Background job completed without an available result.");
      }
      return statusPayload.result;
    }
    if (statusPayload.status === "failed") {
      throw new Error(statusPayload.error_code || "Background job failed.");
    }
  }

  throw new Error("Background job timed out.");
}
