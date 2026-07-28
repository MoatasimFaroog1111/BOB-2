"use client";

import { useEffect } from "react";
import { API_BASE_URL } from "@/lib/api";

const POLL_INTERVAL_MS = 750;
const JOB_TIMEOUT_MS = 15 * 60 * 1000;

type JobEnvelope = {
  job_id?: unknown;
  status?: unknown;
  result?: unknown;
  error_code?: unknown;
};

function jsonResponse(payload: unknown, status: number): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

export default function BackgroundJobFetchBridge() {
  useEffect(() => {
    const authenticatedFetch = window.fetch.bind(window);

    const bridgedFetch: typeof window.fetch = async (input, init) => {
      const initialResponse = await authenticatedFetch(input, init);
      if (initialResponse.status !== 202) return initialResponse;

      const initialPayload = (await initialResponse.clone().json().catch(() => null)) as JobEnvelope | null;
      if (!initialPayload || typeof initialPayload.job_id !== "string") return initialResponse;

      const deadline = Date.now() + JOB_TIMEOUT_MS;
      while (Date.now() < deadline) {
        await sleep(POLL_INTERVAL_MS);
        const statusResponse = await authenticatedFetch(
          `${API_BASE_URL}/api/v1/jobs/${encodeURIComponent(initialPayload.job_id)}`,
          { cache: "no-store", signal: init?.signal },
        );
        const statusPayload = (await statusResponse.json().catch(() => null)) as JobEnvelope | null;
        if (!statusResponse.ok) {
          return jsonResponse(
            { detail: typeof statusPayload?.error_code === "string" ? statusPayload.error_code : "Background job status failed." },
            statusResponse.status,
          );
        }
        if (statusPayload?.status === "completed") {
          return jsonResponse(statusPayload.result ?? { detail: "Background job completed without a result." }, 200);
        }
        if (statusPayload?.status === "failed") {
          return jsonResponse(
            { detail: typeof statusPayload.error_code === "string" ? statusPayload.error_code : "Background job failed." },
            500,
          );
        }
      }

      return jsonResponse({ detail: "Background job timed out." }, 504);
    };

    window.fetch = bridgedFetch;
    return () => {
      if (window.fetch === bridgedFetch) window.fetch = authenticatedFetch;
    };
  }, []);

  return null;
}
