"use client";

/**
 * Email verification landing page. Reads the token from the query
 * string, posts it to ``POST /api/v1/auth/verify-email``, and shows
 * the result.
 */

import { useEffect, useState } from "react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type Status = "idle" | "verifying" | "verified" | "error";

export default function VerifyEmailPage() {
  const [status, setStatus] = useState<Status>("idle");
  const [message, setMessage] = useState<string>("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    if (!token) {
      setStatus("error");
      setMessage("Missing verification token.");
      return;
    }

    setStatus("verifying");
    const url = `${API_BASE.replace(/\/$/, "")}/api/v1/auth/verify-email`;
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    })
      .then(async (res) => {
        if (!res.ok) {
          const text = await res.text();
          throw new Error(`${res.status}: ${text}`);
        }
        return res.json();
      })
      .then(() => {
        setStatus("verified");
        setMessage("Your email is verified. You can now sign in.");
      })
      .catch((e) => {
        setStatus("error");
        setMessage(String(e));
      });
  }, []);

  return (
    <section className="mx-auto max-w-md px-6 py-16">
      <h1 className="text-2xl font-semibold">Verify email</h1>
      <p className="mt-3 rounded-md border border-slate-800 bg-slate-900/60 p-3 text-sm">
        {status === "verifying" && "Verifying…"}
        {status === "verified" && (
          <span className="text-emerald-300">{message}</span>
        )}
        {status === "error" && (
          <span className="text-red-300">{message}</span>
        )}
        {status === "idle" && "Preparing…"}
      </p>
    </section>
  );
}