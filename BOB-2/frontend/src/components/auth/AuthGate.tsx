"use client";

import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "@/lib/api";

type AuthState = "loading" | "authenticated" | "unauthenticated" | "mfa";

type LoginResponse = {
  access_token: string | null;
  refresh_token: string | null;
  role: string;
  mfa_required?: boolean;
  mfa_token?: string | null;
};

type RefreshResponse = {
  access_token: string;
  refresh_token: string;
};

const ACCESS_TOKEN_KEY = "guardian_access_token";
const REFRESH_TOKEN_KEY = "guardian_refresh_token";
const ROLE_KEY = "guardian_role";

function clearSession(): void {
  sessionStorage.removeItem(ACCESS_TOKEN_KEY);
  sessionStorage.removeItem(REFRESH_TOKEN_KEY);
  sessionStorage.removeItem(ROLE_KEY);
}

function storeSession(data: LoginResponse): void {
  if (!data.access_token || !data.refresh_token) {
    throw new Error("لم تكتمل جلسة تسجيل الدخول الآمنة.");
  }
  sessionStorage.setItem(ACCESS_TOKEN_KEY, data.access_token);
  sessionStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
  sessionStorage.setItem(ROLE_KEY, data.role);
}

function apiUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

export default function AuthGate({ children }: { children: ReactNode }) {
  const [authState, setAuthState] = useState<AuthState>("loading");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const originalFetchRef = useRef<typeof window.fetch | null>(null);

  useEffect(() => {
    const originalFetch = window.fetch.bind(window);
    originalFetchRef.current = originalFetch;
    let refreshPromise: Promise<string | null> | null = null;

    const refreshAccessToken = async (): Promise<string | null> => {
      const refreshToken = sessionStorage.getItem(REFRESH_TOKEN_KEY);
      if (!refreshToken) return null;

      const response = await originalFetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
        cache: "no-store",
      });

      if (!response.ok) {
        clearSession();
        setAuthState("unauthenticated");
        return null;
      }

      const data = (await response.json()) as RefreshResponse;
      sessionStorage.setItem(ACCESS_TOKEN_KEY, data.access_token);
      sessionStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
      return data.access_token;
    };

    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = apiUrl(input);
      const isBackendRequest = url.startsWith(API_BASE_URL);
      const isPublicAuthRequest =
        url.includes("/api/v1/auth/login") ||
        url.includes("/api/v1/auth/refresh") ||
        url.includes("/api/v1/auth/mfa/verify") ||
        url.endsWith("/health");

      if (!isBackendRequest || isPublicAuthRequest) {
        return originalFetch(input, init);
      }

      const headers = new Headers(
        input instanceof Request ? input.headers : init?.headers,
      );
      const accessToken = sessionStorage.getItem(ACCESS_TOKEN_KEY);
      if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

      const response = await originalFetch(input, { ...init, headers });
      if (response.status !== 401 || !sessionStorage.getItem(REFRESH_TOKEN_KEY)) {
        return response;
      }

      refreshPromise ??= refreshAccessToken().finally(() => {
        refreshPromise = null;
      });
      const rotatedAccessToken = await refreshPromise;
      if (!rotatedAccessToken) return response;

      const retryHeaders = new Headers(headers);
      retryHeaders.set("Authorization", `Bearer ${rotatedAccessToken}`);
      return originalFetch(input, { ...init, headers: retryHeaders });
    };

    setAuthState(
      sessionStorage.getItem(ACCESS_TOKEN_KEY)
        ? "authenticated"
        : "unauthenticated",
    );

    return () => {
      window.fetch = originalFetch;
      originalFetchRef.current = null;
    };
  }, []);

  const handleLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");

    try {
      const transport = originalFetchRef.current ?? window.fetch.bind(window);
      const response = await transport(`${API_BASE_URL}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
        cache: "no-store",
      });

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || "تعذر تسجيل الدخول.");
      }

      const data = (await response.json()) as LoginResponse;
      setPassword("");
      if (data.mfa_required && data.mfa_token) {
        clearSession();
        setMfaToken(data.mfa_token);
        setMfaCode("");
        setAuthState("mfa");
        return;
      }
      storeSession(data);
      setAuthState("authenticated");
    } catch (loginError) {
      clearSession();
      setError(
        loginError instanceof Error
          ? loginError.message
          : "تعذر تسجيل الدخول.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleMfaVerify = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!mfaToken) {
      setAuthState("unauthenticated");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const transport = originalFetchRef.current ?? window.fetch.bind(window);
      const response = await transport(`${API_BASE_URL}/api/v1/auth/mfa/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mfa_token: mfaToken, code: mfaCode }),
        cache: "no-store",
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || "رمز التحقق غير صحيح أو منتهي.");
      }
      const data = (await response.json()) as LoginResponse;
      storeSession(data);
      setMfaToken(null);
      setMfaCode("");
      setAuthState("authenticated");
    } catch (verificationError) {
      clearSession();
      setError(
        verificationError instanceof Error
          ? verificationError.message
          : "تعذر التحقق من الرمز.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleLogout = async () => {
    try {
      await window.fetch(`${API_BASE_URL}/api/v1/auth/logout`, {
        method: "POST",
        cache: "no-store",
      });
    } finally {
      clearSession();
      setMfaToken(null);
      setAuthState("unauthenticated");
    }
  };

  if (authState === "loading") {
    return (
      <div className="min-h-screen bg-slate-950 text-white grid place-items-center">
        <p className="text-sm text-white/60">جاري تهيئة الجلسة الآمنة…</p>
      </div>
    );
  }

  if (authState === "mfa") {
    return (
      <div className="min-h-screen bg-slate-950 text-white grid place-items-center p-6">
        <form
          onSubmit={handleMfaVerify}
          className="w-full max-w-md rounded-2xl border border-white/10 bg-black/40 p-7 shadow-2xl space-y-5"
        >
          <div>
            <h1 className="text-2xl font-bold">التحقق بخطوتين</h1>
            <p className="mt-2 text-sm text-white/55">
              أدخل الرمز المكوّن من 6 أرقام من تطبيق المصادقة.
            </p>
          </div>
          <label className="block space-y-2">
            <span className="text-sm text-white/70">رمز التحقق</span>
            <input
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={mfaCode}
              onChange={(event) => setMfaCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
              required
              minLength={6}
              maxLength={6}
              className="w-full rounded-lg border border-white/15 bg-white/5 px-3 py-2.5 text-center text-2xl tracking-[0.4em] outline-none focus:border-amber-400"
            />
          </label>
          {error && (
            <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={submitting || mfaCode.length !== 6}
            className="w-full rounded-lg bg-amber-400 px-4 py-2.5 font-semibold text-black disabled:opacity-50"
          >
            {submitting ? "جاري التحقق…" : "تحقق"}
          </button>
          <button
            type="button"
            onClick={() => {
              setMfaToken(null);
              setMfaCode("");
              setError("");
              setAuthState("unauthenticated");
            }}
            className="w-full text-sm text-white/60 hover:text-white"
          >
            العودة إلى تسجيل الدخول
          </button>
        </form>
      </div>
    );
  }

  if (authState === "unauthenticated") {
    return (
      <div className="min-h-screen bg-slate-950 text-white grid place-items-center p-6">
        <form
          onSubmit={handleLogin}
          className="w-full max-w-md rounded-2xl border border-white/10 bg-black/40 p-7 shadow-2xl space-y-5"
        >
          <div>
            <h1 className="text-2xl font-bold">GuardianAI</h1>
            <p className="mt-2 text-sm text-white/55">
              سجّل الدخول للوصول إلى البيانات المحاسبية.
            </p>
          </div>

          <label className="block space-y-2">
            <span className="text-sm text-white/70">البريد الإلكتروني</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="username"
              required
              maxLength={254}
              className="w-full rounded-lg border border-white/15 bg-white/5 px-3 py-2.5 outline-none focus:border-amber-400"
            />
          </label>

          <label className="block space-y-2">
            <span className="text-sm text-white/70">كلمة المرور</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
              maxLength={128}
              className="w-full rounded-lg border border-white/15 bg-white/5 px-3 py-2.5 outline-none focus:border-amber-400"
            />
          </label>

          {error && (
            <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-amber-400 px-4 py-2.5 font-semibold text-black disabled:opacity-50"
          >
            {submitting ? "جاري التحقق…" : "تسجيل الدخول"}
          </button>
        </form>
      </div>
    );
  }

  return (
    <>
      {children}
      <button
        type="button"
        onClick={handleLogout}
        className="fixed bottom-4 left-4 z-50 rounded-lg border border-white/15 bg-black/80 px-3 py-2 text-xs text-white/75 hover:text-white"
      >
        تسجيل الخروج
      </button>
    </>
  );
}
