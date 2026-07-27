"use client";

import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "@/lib/api";

type AuthState =
  | "loading"
  | "authenticated"
  | "unauthenticated"
  | "mfa"
  | "forgot"
  | "reset"
  | "register";

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

type InvitationResponse = {
  invite_url: string;
  expires_in_hours: number;
  email_sent: boolean;
};

const ACCESS_TOKEN_KEY = "guardian_access_token";
const REFRESH_TOKEN_KEY = "guardian_refresh_token";
const ROLE_KEY = "guardian_role";

const INVITABLE_ROLES = [
  ["viewer", "مشاهد"],
  ["accountant", "محاسب"],
  ["reviewer", "مراجع"],
  ["auditor", "مدقق"],
  ["finance_manager", "مدير مالي"],
  ["cfo", "المدير المالي التنفيذي"],
  ["admin", "مدير نظام"],
] as const;

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

function cleanAccountAccessQuery(): void {
  const url = new URL(window.location.href);
  url.searchParams.delete("reset_token");
  url.searchParams.delete("invite");
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

export default function AuthGate({ children }: { children: ReactNode }) {
  const [authState, setAuthState] = useState<AuthState>("loading");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [resetToken, setResetToken] = useState("");
  const [inviteToken, setInviteToken] = useState("");
  const [fullName, setFullName] = useState("");
  const [registrationEmail, setRegistrationEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [currentRole, setCurrentRole] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("viewer");
  const [inviteResult, setInviteResult] = useState<InvitationResponse | null>(null);
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
        setCurrentRole("");
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
        url.includes("/api/v1/auth/password-reset/request") ||
        url.includes("/api/v1/auth/password-reset/confirm") ||
        url.includes("/api/v1/auth/register") ||
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

    const accessToken = sessionStorage.getItem(ACCESS_TOKEN_KEY);
    if (accessToken) {
      setCurrentRole(sessionStorage.getItem(ROLE_KEY) || "");
      setAuthState("authenticated");
    } else {
      const params = new URLSearchParams(window.location.search);
      const reset = params.get("reset_token");
      const invite = params.get("invite");
      if (reset) {
        setResetToken(reset);
        setAuthState("reset");
      } else if (invite) {
        setInviteToken(invite);
        setAuthState("register");
      } else {
        setAuthState("unauthenticated");
      }
    }

    return () => {
      window.fetch = originalFetch;
      originalFetchRef.current = null;
    };
  }, []);

  const goToLogin = (message = "") => {
    cleanAccountAccessQuery();
    setResetToken("");
    setInviteToken("");
    setNewPassword("");
    setConfirmPassword("");
    setPassword("");
    setError("");
    setNotice(message);
    setAuthState("unauthenticated");
  };

  const handleLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    setNotice("");

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
      setCurrentRole(data.role);
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
      setCurrentRole(data.role);
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

  const handlePasswordResetRequest = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    setNotice("");
    try {
      const transport = originalFetchRef.current ?? window.fetch.bind(window);
      const response = await transport(`${API_BASE_URL}/api/v1/auth/password-reset/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
        cache: "no-store",
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail || "تعذر إرسال طلب إعادة التعيين.");
      setNotice(body?.message || "تم استلام طلب إعادة التعيين.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "تعذر إرسال الطلب.");
    } finally {
      setSubmitting(false);
    }
  };

  const handlePasswordResetConfirm = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (newPassword !== confirmPassword) {
      setError("كلمتا المرور غير متطابقتين.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const transport = originalFetchRef.current ?? window.fetch.bind(window);
      const response = await transport(`${API_BASE_URL}/api/v1/auth/password-reset/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: resetToken, new_password: newPassword }),
        cache: "no-store",
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail || "تعذر تعيين كلمة المرور.");
      goToLogin(body?.message || "تم تعيين كلمة المرور الجديدة.");
    } catch (resetError) {
      setError(resetError instanceof Error ? resetError.message : "تعذر تعيين كلمة المرور.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleRegister = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (newPassword !== confirmPassword) {
      setError("كلمتا المرور غير متطابقتين.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const transport = originalFetchRef.current ?? window.fetch.bind(window);
      const response = await transport(`${API_BASE_URL}/api/v1/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          invite_token: inviteToken,
          email: registrationEmail,
          full_name: fullName,
          password: newPassword,
        }),
        cache: "no-store",
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail || "تعذر إنشاء الحساب.");
      setEmail(registrationEmail);
      setFullName("");
      setRegistrationEmail("");
      goToLogin(body?.message || "تم إنشاء الحساب بنجاح.");
    } catch (registrationError) {
      setError(registrationError instanceof Error ? registrationError.message : "تعذر إنشاء الحساب.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleCreateInvitation = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    setInviteResult(null);
    try {
      const response = await window.fetch(`${API_BASE_URL}/api/v1/auth/invitations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
        cache: "no-store",
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail || "تعذر إنشاء الدعوة.");
      setInviteResult(body as InvitationResponse);
    } catch (invitationError) {
      setError(invitationError instanceof Error ? invitationError.message : "تعذر إنشاء الدعوة.");
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
      setCurrentRole("");
      setMfaToken(null);
      setInviteOpen(false);
      setAuthState("unauthenticated");
    }
  };

  const authCardClass = "w-full max-w-md rounded-2xl border border-white/10 bg-black/40 p-7 shadow-2xl space-y-5";
  const inputClass = "w-full rounded-lg border border-white/15 bg-white/5 px-3 py-2.5 outline-none focus:border-amber-400";
  const primaryButtonClass = "w-full rounded-lg bg-amber-400 px-4 py-2.5 font-semibold text-black disabled:opacity-50";

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
        <form onSubmit={handleMfaVerify} className={authCardClass}>
          <div>
            <h1 className="text-2xl font-bold">التحقق بخطوتين</h1>
            <p className="mt-2 text-sm text-white/55">أدخل الرمز المكوّن من 6 أرقام من تطبيق المصادقة.</p>
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
          {error && <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">{error}</p>}
          <button type="submit" disabled={submitting || mfaCode.length !== 6} className={primaryButtonClass}>
            {submitting ? "جاري التحقق…" : "تحقق"}
          </button>
          <button type="button" onClick={() => goToLogin()} className="w-full text-sm text-white/60 hover:text-white">العودة إلى تسجيل الدخول</button>
        </form>
      </div>
    );
  }

  if (authState === "forgot") {
    return (
      <div className="min-h-screen bg-slate-950 text-white grid place-items-center p-6">
        <form onSubmit={handlePasswordResetRequest} className={authCardClass}>
          <div>
            <h1 className="text-2xl font-bold">نسيت كلمة المرور؟</h1>
            <p className="mt-2 text-sm text-white/55">أدخل بريد حسابك وسنرسل رابطًا آمنًا قصير الصلاحية.</p>
          </div>
          <label className="block space-y-2">
            <span className="text-sm text-white/70">البريد الإلكتروني</span>
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" required maxLength={254} className={inputClass} />
          </label>
          {notice && <p className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-200">{notice}</p>}
          {error && <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">{error}</p>}
          <button type="submit" disabled={submitting} className={primaryButtonClass}>{submitting ? "جاري الإرسال…" : "إرسال رابط إعادة التعيين"}</button>
          <button type="button" onClick={() => goToLogin()} className="w-full text-sm text-white/60 hover:text-white">العودة إلى تسجيل الدخول</button>
        </form>
      </div>
    );
  }

  if (authState === "reset") {
    return (
      <div className="min-h-screen bg-slate-950 text-white grid place-items-center p-6">
        <form onSubmit={handlePasswordResetConfirm} className={authCardClass}>
          <div>
            <h1 className="text-2xl font-bold">تعيين كلمة مرور جديدة</h1>
            <p className="mt-2 text-sm text-white/55">استخدم 12 حرفًا على الأقل تشمل حرفًا كبيرًا وصغيرًا ورقمًا ورمزًا خاصًا.</p>
          </div>
          <label className="block space-y-2">
            <span className="text-sm text-white/70">كلمة المرور الجديدة</span>
            <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" required minLength={12} maxLength={128} className={inputClass} />
          </label>
          <label className="block space-y-2">
            <span className="text-sm text-white/70">تأكيد كلمة المرور</span>
            <input type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} autoComplete="new-password" required minLength={12} maxLength={128} className={inputClass} />
          </label>
          {error && <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">{error}</p>}
          <button type="submit" disabled={submitting || !resetToken} className={primaryButtonClass}>{submitting ? "جاري الحفظ…" : "حفظ كلمة المرور الجديدة"}</button>
          <button type="button" onClick={() => goToLogin()} className="w-full text-sm text-white/60 hover:text-white">إلغاء والعودة للدخول</button>
        </form>
      </div>
    );
  }

  if (authState === "register") {
    return (
      <div className="min-h-screen bg-slate-950 text-white grid place-items-center p-6">
        <form onSubmit={handleRegister} className={authCardClass}>
          <div>
            <h1 className="text-2xl font-bold">إنشاء حساب جديد</h1>
            <p className="mt-2 text-sm text-white/55">لأمان البيانات المحاسبية، يتطلب التسجيل دعوة صادرة من مالك النظام أو المدير.</p>
          </div>
          <label className="block space-y-2">
            <span className="text-sm text-white/70">رمز الدعوة</span>
            <textarea value={inviteToken} onChange={(event) => setInviteToken(event.target.value.trim())} required rows={3} className={`${inputClass} resize-none text-xs`} placeholder="الصق رمز الدعوة أو افتح رابط الدعوة" />
          </label>
          <label className="block space-y-2">
            <span className="text-sm text-white/70">الاسم الكامل</span>
            <input type="text" value={fullName} onChange={(event) => setFullName(event.target.value)} autoComplete="name" required minLength={2} maxLength={255} className={inputClass} />
          </label>
          <label className="block space-y-2">
            <span className="text-sm text-white/70">البريد الإلكتروني المدعو</span>
            <input type="email" value={registrationEmail} onChange={(event) => setRegistrationEmail(event.target.value)} autoComplete="email" required maxLength={254} className={inputClass} />
          </label>
          <label className="block space-y-2">
            <span className="text-sm text-white/70">كلمة المرور</span>
            <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" required minLength={12} maxLength={128} className={inputClass} />
          </label>
          <label className="block space-y-2">
            <span className="text-sm text-white/70">تأكيد كلمة المرور</span>
            <input type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} autoComplete="new-password" required minLength={12} maxLength={128} className={inputClass} />
          </label>
          {error && <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">{error}</p>}
          <button type="submit" disabled={submitting || !inviteToken} className={primaryButtonClass}>{submitting ? "جاري إنشاء الحساب…" : "إنشاء الحساب"}</button>
          <button type="button" onClick={() => goToLogin()} className="w-full text-sm text-white/60 hover:text-white">لدي حساب بالفعل</button>
        </form>
      </div>
    );
  }

  if (authState === "unauthenticated") {
    return (
      <div className="min-h-screen bg-slate-950 text-white grid place-items-center p-6">
        <form onSubmit={handleLogin} className={authCardClass}>
          <div>
            <h1 className="text-2xl font-bold">GuardianAI</h1>
            <p className="mt-2 text-sm text-white/55">سجّل الدخول للوصول إلى البيانات المحاسبية.</p>
          </div>
          <label className="block space-y-2">
            <span className="text-sm text-white/70">البريد الإلكتروني</span>
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="username" required maxLength={254} className={inputClass} />
          </label>
          <label className="block space-y-2">
            <span className="flex items-center justify-between gap-3 text-sm text-white/70">
              <span>كلمة المرور</span>
              <button type="button" onClick={() => { setError(""); setNotice(""); setAuthState("forgot"); }} className="text-amber-300 hover:text-amber-200">نسيت كلمة المرور؟</button>
            </span>
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required maxLength={128} className={inputClass} />
          </label>
          {notice && <p className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-200">{notice}</p>}
          {error && <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">{error}</p>}
          <button type="submit" disabled={submitting} className={primaryButtonClass}>{submitting ? "جاري التحقق…" : "تسجيل الدخول"}</button>
          <div className="border-t border-white/10 pt-4 text-center text-sm text-white/60">
            لديك دعوة؟{" "}
            <button type="button" onClick={() => { setError(""); setNotice(""); setAuthState("register"); }} className="font-semibold text-amber-300 hover:text-amber-200">إنشاء حساب جديد</button>
          </div>
        </form>
      </div>
    );
  }

  const canManageUsers = currentRole === "owner" || currentRole === "admin";

  return (
    <>
      {children}
      <div className="fixed bottom-4 left-4 z-50 flex items-center gap-2">
        {canManageUsers && (
          <button
            type="button"
            onClick={() => {
              setError("");
              setInviteResult(null);
              setInviteOpen(true);
            }}
            className="rounded-lg border border-amber-400/30 bg-black/80 px-3 py-2 text-xs text-amber-300 hover:bg-amber-400/10"
          >
            دعوة مستخدم
          </button>
        )}
        <button type="button" onClick={handleLogout} className="rounded-lg border border-white/15 bg-black/80 px-3 py-2 text-xs text-white/75 hover:text-white">تسجيل الخروج</button>
      </div>

      {inviteOpen && (
        <div className="fixed inset-0 z-[70] grid place-items-center bg-black/75 p-6" role="dialog" aria-modal="true" aria-label="دعوة مستخدم جديد">
          <form onSubmit={handleCreateInvitation} className={authCardClass}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-bold">دعوة مستخدم جديد</h2>
                <p className="mt-2 text-sm text-white/55">سيصدر رابط تسجيل آمن صالح لمدة 72 ساعة.</p>
              </div>
              <button type="button" onClick={() => setInviteOpen(false)} className="text-xl text-white/60 hover:text-white" aria-label="إغلاق">×</button>
            </div>
            <label className="block space-y-2">
              <span className="text-sm text-white/70">البريد الإلكتروني</span>
              <input type="email" value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} required maxLength={254} className={inputClass} />
            </label>
            <label className="block space-y-2">
              <span className="text-sm text-white/70">الصلاحية</span>
              <select value={inviteRole} onChange={(event) => setInviteRole(event.target.value)} className={inputClass}>
                {INVITABLE_ROLES.map(([value, label]) => <option key={value} value={value} className="bg-slate-900">{label}</option>)}
              </select>
            </label>
            {error && <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">{error}</p>}
            {inviteResult && (
              <div className="space-y-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-100">
                <p>{inviteResult.email_sent ? "تم إرسال الدعوة بالبريد الإلكتروني." : "تم إنشاء الدعوة. خدمة البريد غير مفعلة؛ انسخ الرابط وأرسله للمستخدم."}</p>
                <textarea readOnly value={inviteResult.invite_url} rows={4} className="w-full resize-none rounded-lg border border-white/10 bg-black/30 p-2 text-xs text-white" />
                <button type="button" onClick={() => navigator.clipboard.writeText(inviteResult.invite_url)} className="rounded-lg border border-emerald-300/30 px-3 py-2 text-xs font-semibold hover:bg-emerald-300/10">نسخ رابط الدعوة</button>
              </div>
            )}
            <button type="submit" disabled={submitting} className={primaryButtonClass}>{submitting ? "جاري إنشاء الدعوة…" : "إنشاء وإرسال الدعوة"}</button>
          </form>
        </div>
      )}
    </>
  );
}
