"use client";

/**
 * Pricing page — reads the live plan catalog from
 * ``GET /api/v1/billing/plans`` and renders a responsive comparison
 * grid.
 *
 * Plans come from the backend so the marketing team does not need a
 * redeploy to change prices — the canonical source of truth is the
 * backend's :class:`InMemoryBillingProvider` (and later, Stripe /
 * Lemon Squeezy when configured).
 */

import { useEffect, useState } from "react";
import Link from "next/link";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

interface Plan {
  id: string;
  name: string;
  interval: string;
  amount_cents: number;
  currency: string;
  description: string;
  trial_days: number;
  features: string[];
}

interface PlansResponse {
  provider: string;
  plans: Plan[];
}

function formatMoney(amount_cents: number, currency: string) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
  }).format(amount_cents / 100);
}

export default function PricingPage() {
  const [data, setData] = useState<PlansResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const url = `${API_BASE.replace(/\/$/, "")}/api/v1/billing/plans`;
    fetch(url, { cache: "no-store" })
      .then(async (res) => {
        if (!res.ok) throw new Error(`Plans responded ${res.status}`);
        return (await res.json()) as PlansResponse;
      })
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <p className="p-12 text-slate-400">Loading plans…</p>;
  }
  if (error) {
    return (
      <p className="p-12 text-red-400">
        Could not load plans: {error}
      </p>
    );
  }
  if (!data || data.plans.length === 0) {
    return (
      <p className="p-12 text-slate-400">
        No public plans available in this deployment frame.
      </p>
    );
  }

  return (
    <section className="mx-auto max-w-6xl px-6 py-16">
      <h1 className="text-3xl font-semibold">Plans</h1>
      <p className="mt-2 text-sm text-slate-400">
        Provider: <code>{data.provider}</code>. Cancel anytime.
      </p>
      <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {data.plans.map((plan) => (
          <article
            key={plan.id}
            className="flex flex-col rounded-xl border border-slate-800 bg-slate-900/60 p-6"
          >
            <h2 className="text-lg font-semibold text-white">{plan.name}</h2>
            <p className="mt-2 text-sm text-slate-400">{plan.description}</p>
            <p className="mt-4 text-3xl font-bold">
              {formatMoney(plan.amount_cents, plan.currency)}
              <span className="ml-1 text-sm font-normal text-slate-400">
                / {plan.interval === "lifetime" ? "once" : plan.interval}
              </span>
            </p>
            {plan.trial_days > 0 && (
              <p className="mt-1 text-xs text-amber-300">
                {plan.trial_days}-day free trial
              </p>
            )}
            <ul className="mt-4 space-y-1 text-sm text-slate-300">
              {plan.features.map((f) => (
                <li key={f}>· {f}</li>
              ))}
            </ul>
            <Link
              href="/signup"
              className="mt-6 inline-block rounded-md border border-amber-400 px-3 py-2 text-center text-sm text-amber-300 hover:bg-amber-400 hover:text-slate-950"
            >
              Choose {plan.name}
            </Link>
          </article>
        ))}
      </div>
    </section>
  );
}