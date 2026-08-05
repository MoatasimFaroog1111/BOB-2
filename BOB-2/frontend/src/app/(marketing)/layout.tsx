"use client";

/**
 * Shared marketing layout — public landing pages rendered only when the
 * active deployment frame enables them. The route group itself is
 * always declared so the build succeeds; each page checks
 * ``useCapabilities`` and hides itself in the ``enterprise`` frame.
 *
 * Pages within the group:
 *
 * - ``/``              — landing
 * - ``/pricing``       — plan comparison
 * - ``/compare``       — frame-by-frame comparison
 * - ``/signup``        — self-serve signup (top-level, sibling to (marketing))
 */

import Link from "next/link";
import type { ReactNode } from "react";

import { useCapabilities } from "@/features/capabilities/useCapabilities";

export default function MarketingLayout({ children }: { children: ReactNode }) {
  const { view, loading } = useCapabilities();

  // While loading, render the children unconditionally so the user does
  // not see a flash of empty marketing chrome. Once capabilities resolve
  // we hide the entire surface in the enterprise frame.
  const showMarketing = !view || view.frame !== "enterprise" || loading;

  if (!showMarketing) {
    return (
      <main className="flex h-full w-full flex-col items-center justify-center bg-slate-950 p-12 text-center text-slate-100">
        <h1 className="text-2xl font-semibold">
          Marketing pages are not enabled in this deployment
        </h1>
        <p className="mt-2 max-w-md text-sm text-slate-400">
          This deployment is configured with{" "}
          <code className="rounded bg-slate-800 px-1 py-0.5 text-xs">DEPLOYMENT_FRAME=enterprise</code>.
          Sign in via your invitation link to continue.
        </p>
      </main>
    );
  }

  return (
    <div className="flex h-full w-full flex-col bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-900/60 px-6 py-4 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <Link href="/" className="text-lg font-semibold tracking-tight">
            GuardianAI
          </Link>
          <nav className="flex items-center gap-4 text-sm">
            <Link href="/pricing" className="text-slate-300 hover:text-white">
              Pricing
            </Link>
            <Link href="/compare" className="text-slate-300 hover:text-white">
              Compare
            </Link>
            <Link
              href="/signup"
              className="rounded-md border border-amber-400 px-3 py-1.5 text-amber-300 hover:bg-amber-400 hover:text-slate-950"
            >
              Start free trial
            </Link>
          </nav>
        </div>
      </header>
      <main className="flex-1 overflow-auto">{children}</main>
      <footer className="border-t border-slate-800 px-6 py-6 text-xs text-slate-500">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 sm:flex-row sm:justify-between">
          <span>© {new Date().getFullYear()} GuardianAI — Enterprise-grade AI accounting.</span>
          <span>Frame: {view?.frame ?? "loading"}</span>
        </div>
      </footer>
    </div>
  );
}