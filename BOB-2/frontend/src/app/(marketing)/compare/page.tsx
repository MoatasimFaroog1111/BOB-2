"use client";

/**
 * Compare page — explains the three deployment frames from the ADR
 * so prospective buyers can pick the GTM motion that fits them.
 */

const ROWS: Array<{
  capability: string;
  enterprise: string;
  self_serve_saas: string;
  hybrid: string;
}> = [
  {
    capability: "Acquisition motion",
    enterprise: "Single-buyer asset sale",
    self_serve_saas: "Self-serve Stripe checkout",
    hybrid: "Marketplace + operator-led",
  },
  {
    capability: "Customer onboarding",
    enterprise: "Invitation only",
    self_serve_saas: "Self-serve signup + email verify",
    hybrid: "Self-serve + first-value session",
  },
  {
    capability: "Pricing display",
    enterprise: "Hidden — contact sales",
    self_serve_saas: "Public pricing page",
    hybrid: "Public pricing + lifetime tier",
  },
  {
    capability: "Billing integration",
    enterprise: "Off (invoice via Acquire deal)",
    self_serve_saas: "Stripe (primary)",
    hybrid: "Stripe + Lemon Squeezy",
  },
  {
    capability: "Multi-tenant",
    enterprise: "Single tenant",
    self_serve_saas: "Multi-tenant",
    hybrid: "Multi-tenant",
  },
  {
    capability: "Audit-chain S3 export",
    enterprise: "Optional",
    self_serve_saas: "Default",
    hybrid: "Default",
  },
];

export default function ComparePage() {
  return (
    <section className="mx-auto max-w-6xl px-6 py-16">
      <h1 className="text-3xl font-semibold">Compare frames</h1>
      <p className="mt-2 max-w-2xl text-sm text-slate-400">
        The same codebase can be deployed as any of the three frames below.
        Pick the GTM motion that matches your buyer — no fork required.
      </p>
      <div className="mt-8 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-left text-xs uppercase tracking-wider text-slate-400">
              <th className="px-4 py-3">Capability</th>
              <th className="px-4 py-3">Enterprise</th>
              <th className="px-4 py-3">Self-Serve SaaS</th>
              <th className="px-4 py-3">Hybrid Marketplace</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map((r) => (
              <tr key={r.capability} className="border-b border-slate-900">
                <td className="px-4 py-3 font-medium text-white">
                  {r.capability}
                </td>
                <td className="px-4 py-3 text-slate-300">{r.enterprise}</td>
                <td className="px-4 py-3 text-slate-300">
                  {r.self_serve_saas}
                </td>
                <td className="px-4 py-3 text-slate-300">{r.hybrid}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}