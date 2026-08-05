"use client";

/**
 * Self-serve signup page. Returns 404 in the enterprise frame because
 * the backend's ``POST /api/v1/auth/signup`` does the same. The page
 * surfaces a friendly "not available" message instead of an HTTP error
 * so the user knows the platform exists, just under a different GTM.
 *
 * On success the response includes a verification token that the
 * platform normally sends via email. In dev the user copies the link
 * from this page and pastes it back into ``/verify-email``.
 */

import { useState, type FormEvent } from "react";

import { useCapabilities } from "@/features/capabilities/useCapabilities";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

interface SignupReceipt {
  organization_id: number;
  owner_user_id: number;
  tenant_slug: string;
  owner_email: string;
  verification_token: string;
  verification_expires_at: string;
}

export default function SignupPage() {
  const { isEnabled } = useCapabilities();
  const enabled = isEnabled("self_serve_signup");

  const [orgName, setOrgName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<SignupReceipt | null>(null);

  if (!enabled) {
    return (
      <section className="mx-auto max-w-2xl px-6 py-16 text-center">
        <h1 className="text-2xl font-semibold">
          Self-serve signup is not available in this deployment
        </h1>
        <p className="mt-2 text-sm text-slate-400">
          Contact the platform owner for an invitation.
        </p>
      </section>
    );
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const url = `${API_BASE.replace(/\/$/, "")}/api/v1/auth/signup`;
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          organization_name: orgName,
          owner_email: email,
          owner_password: password,
          owner_full_name: fullName || undefined,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`${res.status}: ${text}`);
      }
      const json = (await res.json()) as SignupReceipt;
      setReceipt(json);
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  if (receipt) {
    const link = `${window.location.origin}/verify-email?token=${encodeURIComponent(receipt.verification_token)}`;
    return (
      <section className="mx-auto max-w-2xl px-6 py-16">
        <h1 className="text-2xl font-semibold">Verify your email</h1>
        <p className="mt-2 text-sm text-slate-400">
          Tenant <code>{receipt.tenant_slug}</code> created. Click the
          verification link below — in production this is sent by email.
        </p>
        <p className="mt-4 break-all rounded-md border border-slate-800 bg-slate-900/60 p-3 text-xs">
          {link}
        </p>
      </section>
    );
  }

  return (
    <section className="mx-auto max-w-md px-6 py-16">
      <h1 className="text-2xl font-semibold">Create your tenant</h1>
      <p className="mt-2 text-sm text-slate-400">
        14-day trial. No credit card required.
      </p>
      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <label className="block text-sm">
          <span className="text-slate-300">Organization name</span>
          <input
            type="text"
            required
            minLength={2}
            maxLength={255}
            value={orgName}
            onChange={(e) => setOrgName(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white"
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-300">Owner full name</span>
          <input
            type="text"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white"
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-300">Owner email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white"
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-300">
            Password (min 12 chars)
          </span>
          <input
            type="password"
            required
            minLength={12}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white"
          />
        </label>
        {error && (
          <p className="rounded-md border border-red-800 bg-red-950/40 p-2 text-xs text-red-300">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-amber-400 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-amber-300 disabled:opacity-60"
        >
          {submitting ? "Creating tenant…" : "Create tenant"}
        </button>
      </form>
    </section>
  );
}