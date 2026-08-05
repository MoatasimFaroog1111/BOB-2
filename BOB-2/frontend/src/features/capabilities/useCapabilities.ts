"use client";

/**
 * Hook over `GET /api/v1/system/capabilities`.
 *
 * The capabilities endpoint is the runtime contract between the
 * backend and the frontend. Reading the response here lets every page
 * decide which surface to render without a hard-coded frame name.
 *
 * In the ``enterprise`` frame the marketing and signup routes are
 * hidden; the hook returns the right shape so callers can branch on
 * ``capabilities[capabilityName] === "default"`` without crashing.
 *
 * In production the response is cached for a short window by the edge
 * proxy, so re-rendering on the client is cheap.
 */

import { useEffect, useState } from "react";

const DEFAULT_API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type CapabilityState = "default" | "optional" | "disabled";

export interface CapabilitiesView {
  frame: string;
  capabilities: Record<string, CapabilityState>;
  build: string;
  git_sha: string;
}

export interface UseCapabilitiesResult {
  view: CapabilitiesView | null;
  loading: boolean;
  error: string | null;
  /** Returns ``true`` if the capability is on by default in the active frame. */
  isEnabled: (name: string) => boolean;
}

const EMPTY_VIEW: CapabilitiesView = {
  frame: "unknown",
  capabilities: {},
  build: "",
  git_sha: "",
};

export function useCapabilities(): UseCapabilitiesResult {
  const [view, setView] = useState<CapabilitiesView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const url = `${DEFAULT_API_BASE.replace(/\/$/, "")}/api/v1/system/capabilities`;
    fetch(url, { credentials: "omit", cache: "no-store" })
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`Capabilities responded ${res.status}`);
        }
        const json = (await res.json()) as CapabilitiesView;
        if (!cancelled) {
          setView(json);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(String(err));
          // Provide an empty view so callers do not crash on first
          // render; isEnabled() returns false for every capability.
          setView(EMPTY_VIEW);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const isEnabled = (name: string) =>
    view?.capabilities?.[name] === "default";

  return { view, loading, error, isEnabled };
}