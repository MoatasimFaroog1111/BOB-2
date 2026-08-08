"use client";

/**
 * Public landing page. Visible only when the active deployment frame
 * enables marketing (``self_serve_saas`` or ``hybrid_marketplace``).
 *
 * The page is intentionally conservative: it links to pricing and
 * signup and never makes unverified revenue / customer claims (per
 * ADR § Product Boundaries).
 */

import Link from "next/link";

import { useCapabilities } from "@/features/capabilities/useCapabilities";

export default function MarketingLanding() {
  const { view } = useCapabilities();

  return (
    <section className="mx-auto max-w-6xl px-6 py-16">
      <div className="grid gap-12 lg:grid-cols-2 lg:items-center">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-amber-400">
            AI accounting · ERP-aware · Audit-ready
          </p>
          <h1 className="mt-4 text-4xl font-semibold leading-tight sm:text-5xl">
            Reconciliation, posting, and audit evidence — without the spreadsheet sprawl.
          </h1>
          <p className="mt-6 text-base text-slate-300 sm:text-lg">
            GuardianAI connects to your Odoo ERP, ingests invoices and bank
            statements, drafts journal entries with explainable AI, and anchors
            every action to an immutable audit chain. Finance teams ship
            month-end in days, not weeks.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              href="/signup"
              className="rounded-md bg-amber-400 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-amber-300"
            >
              Start 14-day trial
            </Link>
            <Link
              href="/pricing"
              className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:border-slate-500"
            >
              See plans
            </Link>
          </div>
          <p className="mt-4 text-xs text-slate-500">
            Available now: Odoo ERP. SAP / Oracle: roadmap.
          </p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-6 text-sm text-slate-300">
          <p className="mb-3 text-xs uppercase tracking-widest text-slate-400">
            Frame
          </p>
          <p className="text-2xl font-semibold text-white">
            {view?.frame ?? "—"}
          </p>
          <p className="mt-2 text-slate-400">
            {view?.frame === "enterprise"
              ? "Invite-only deployment. Marketing pages hidden."
              : "Self-serve or hybrid marketplace. Sign up below."}
          </p>
          <ul className="mt-4 space-y-1 text-xs text-slate-400">
            <li>Build: {view?.build || "—"}</li>
            <li>Commit: {view?.git_sha?.slice(0, 7) || "—"}</li>
          </ul>
        </div>
      </div>
    </section>
  );
}