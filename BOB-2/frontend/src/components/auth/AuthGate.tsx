"use client";

/**
 * AuthGate — orchestrates authentication state and delegates all rendering
 * to small, focused form components.
 *
 * Architecture (SOLID):
 *   - Single Responsibility: this component owns only the auth state
 *     machine and the wiring to the HTTP client abstraction. It does NOT
 *     render form markup directly.
 *   - Open/Closed: adding a new auth view (e.g. SSO, magic link) means
 *     adding a new state + a new form component, not editing this file.
 *   - Dependency Inversion: depends on `getApiClient()` abstraction, not
 *     on raw fetch.
 *   - Liskov: every form component receives the same `onSubmit` shape.
 *   - Interface Segregation: each form imports only the props it needs.
 */

import { FormEvent, ReactNode, useEffect, useState } from "react";
import { ApiError, getApiClient } from "@/lib/http-client";
import { LoginForm } from "./LoginForm";
import { PasswordResetRequestForm } from "./PasswordResetRequestForm";
import { PasswordResetConfirmForm } from "./PasswordResetConfirmForm";
import { MfaVerifyForm } from "./MfaVerifyForm";

type AuthState =
  | "loading"
  | "authenticated"
  | "unauthenticated"
  | "mfa"
  | "forgot"
  | "reset"
  | "register";

interface AuthSession {
  accessToken: string;
  refreshToken: string;
  role: string;
}

const ACCESS_TOKEN_KEY = "guardian_access_token";
const REFRESH_TOKEN_KEY = "guardian_refresh_token";
const ROLE_KEY = "guardian_role";

function storeSession(session: AuthSession): void {
  sessionStorage.setItem(ACCESS_TOKEN_KEY, session.accessToken);
  sessionStorage.setItem(REFRESH_TOKEN_KEY, session.refreshToken);
  sessionStorage.setItem(ROLE_KEY, session.role);
}

function clearSession(): void {
  sessionStorage.removeItem(ACCESS_TOKEN_KEY);
  sessionStorage.removeItem(REFRESH_TOKEN_KEY);
  sessionStorage.removeItem(ROLE_KEY);
}

function readStoredSession(): AuthSession | null {
  const accessToken = sessionStorage.getItem(ACCESS_TOKEN_KEY);
  const refreshToken = sessionStorage.getItem(REFRESH_TOKEN_KEY);
  const role = sessionStorage.getItem(ROLE_KEY);
  if (!accessToken || !refreshToken || !role) return null;
  return { accessToken, refreshToken, role };
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
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // -- Bootstrap: determine initial auth state from storage + URL -------

  useEffect(() => {
    if (readStoredSession()) {
      setAuthState("authenticated");
      return;
    }

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
  }, []);

  // -- Navigation helpers ----------------------------------------------

  function goToLogin(message = ""): void {
    cleanAccountAccessQuery();
    setResetToken("");
    setInviteToken("");
    setNewPassword("");
    setConfirmPassword("");
    setPassword("");
    setError("");
    setNotice(message);
    setAuthState("unauthenticated");
  }

  function goToForgot(): void {
    setError("");
    setNotice("");
    setAuthState("forgot");
  }

  function goToRegister(): void {
    setError("");
    setNotice("");
    setAuthState("register");
  }

  // -- Handlers (delegate to ApiClient abstraction) --------------------

  async function handleLogin(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    setNotice("");

    try {
      const data = await getApiClient().login(email, password);
      setPassword("");

      if (data.mfa_required && data.mfa_token) {
        clearSession();
        setMfaToken(data.mfa_token);
        setMfaCode("");
        setAuthState("mfa");
        return;
      }

      if (!data.access_token || !data.refresh_token) {
        throw new Error("لم تكتمل جلسة تسجيل الدخول الآمنة.");
      }

      storeSession({
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
        role: data.role,
      });
      setAuthState("authenticated");
    } catch (loginError) {
      clearSession();
      setError(toMessage(loginError, "تعذر تسجيل الدخول."));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleMfaVerify(
    event: FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();
    if (!mfaToken) {
      setAuthState("unauthenticated");
      return;
    }
    setSubmitting(true);
    setError("");

    try {
      const data = await getApiClient().verifyMfa(mfaToken, mfaCode);
      storeSession({
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
        role: data.role,
      });
      setMfaToken(null);
      setMfaCode("");
      setAuthState("authenticated");
    } catch (verificationError) {
      clearSession();
      setError(toMessage(verificationError, "رمز التحقق غير صحيح أو منتهي."));
    } finally {
      setSubmitting(false);
    }
  }

  async function handlePasswordResetRequest(
    event: FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    setNotice("");

    try {
      const response = await getApiClient().requestPasswordReset(email);
      setNotice(response.message || "تم استلام طلب إعادة التعيين.");
    } catch (requestError) {
      setError(toMessage(requestError, "تعذر إرسال طلب إعادة التعيين."));
    } finally {
      setSubmitting(false);
    }
  }

  async function handlePasswordResetConfirm(
    event: FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();
    if (newPassword !== confirmPassword) {
      setError("كلمتا المرور غير متطابقتين.");
      return;
    }
    setSubmitting(true);
    setError("");

    try {
      const response = await getApiClient().confirmPasswordReset(
        resetToken,
        newPassword,
      );
      goToLogin(response.message || "تم تعيين كلمة المرور الجديدة.");
    } catch (resetError) {
      setError(toMessage(resetError, "تعذر تعيين كلمة المرور."));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRegister(
    event: FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();
    if (newPassword !== confirmPassword) {
      setError("كلمتا المرور غير متطابقتين.");
      return;
    }
    setSubmitting(true);
    setError("");

    try {
      const response = await getApiClient().register({
        inviteToken,
        email: registrationEmail,
        fullName,
        password: newPassword,
      });
      setEmail(registrationEmail);
      setFullName("");
      setRegistrationEmail("");
      goToLogin(response.message || "تم إنشاء الحساب بنجاح.");
    } catch (registrationError) {
      setError(toMessage(registrationError, "تعذر إنشاء الحساب."));
    } finally {
      setSubmitting(false);
    }
  }

  // -- Rendering --------------------------------------------------------

  if (authState === "loading") {
    return (
      <div className="min-h-screen bg-slate-950 text-white grid place-items-center">
        <p className="text-sm text-white/60">جاري تهيئة الجلسة الآمنة…</p>
      </div>
    );
  }

  if (authState === "authenticated") {
    return <>{children}</>;
  }

  if (authState === "mfa") {
    return (
      <MfaVerifyForm
        code={mfaCode}
        error={error}
        submitting={submitting}
        onCodeChange={setMfaCode}
        onSubmit={handleMfaVerify}
        onBack={goToLogin}
      />
    );
  }

  if (authState === "forgot") {
    return (
      <PasswordResetRequestForm
        email={email}
        notice={notice}
        error={error}
        submitting={submitting}
        onEmailChange={setEmail}
        onSubmit={handlePasswordResetRequest}
        onBack={goToLogin}
      />
    );
  }

  if (authState === "reset") {
    return (
      <PasswordResetConfirmForm
        newPassword={newPassword}
        confirmPassword={confirmPassword}
        error={error}
        submitting={submitting}
        hasResetToken={Boolean(resetToken)}
        onNewPasswordChange={setNewPassword}
        onConfirmPasswordChange={setConfirmPassword}
        onSubmit={handlePasswordResetConfirm}
        onCancel={goToLogin}
      />
    );
  }

  if (authState === "register") {
    return (
      <RegisterForm
        inviteToken={inviteToken}
        email={registrationEmail}
        fullName={fullName}
        newPassword={newPassword}
        confirmPassword={confirmPassword}
        error={error}
        submitting={submitting}
        onEmailChange={setRegistrationEmail}
        onFullNameChange={setFullName}
        onNewPasswordChange={setNewPassword}
        onConfirmPasswordChange={setConfirmPassword}
        onSubmit={handleRegister}
        onBack={goToLogin}
      />
    );
  }

  // authState === "unauthenticated"
  return (
    <LoginForm
      email={email}
      password={password}
      error={error}
      notice={notice}
      submitting={submitting}
      onEmailChange={setEmail}
      onPasswordChange={setPassword}
      onSubmit={handleLogin}
      onForgotPassword={goToForgot}
      onCreateAccount={goToRegister}
    />
  );
}

// -- Inline presentational component for registration --------------------

import {
  AuthButton,
  AuthCard,
  AuthFeedback,
  AuthField,
  AuthInput,
  AuthSecondaryAction,
} from "./AuthCard";

interface RegisterFormProps {
  inviteToken: string;
  email: string;
  fullName: string;
  newPassword: string;
  confirmPassword: string;
  error: string;
  submitting: boolean;
  onEmailChange: (value: string) => void;
  onFullNameChange: (value: string) => void;
  onNewPasswordChange: (value: string) => void;
  onConfirmPasswordChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onBack: () => void;
}

function RegisterForm({
  email,
  fullName,
  newPassword,
  confirmPassword,
  error,
  submitting,
  onEmailChange,
  onFullNameChange,
  onNewPasswordChange,
  onConfirmPasswordChange,
  onSubmit,
  onBack,
}: RegisterFormProps) {
  return (
    <AuthCard
      title="إنشاء حساب جديد"
      subtitle="لأمان البيانات المحاسبية، يتطلب التسجيل دعوة صادرة من مالك النظام أو المدير."
    >
      <form onSubmit={onSubmit} className="space-y-5">
        <AuthField label="الاسم الكامل">
          <AuthInput
            type="text"
            value={fullName}
            onChange={(event) => onFullNameChange(event.target.value)}
            autoComplete="name"
            required
            maxLength={120}
          />
        </AuthField>

        <AuthField label="البريد الإلكتروني">
          <AuthInput
            type="email"
            value={email}
            onChange={(event) => onEmailChange(event.target.value)}
            autoComplete="email"
            required
            maxLength={254}
          />
        </AuthField>

        <AuthField label="كلمة المرور الجديدة">
          <AuthInput
            type="password"
            value={newPassword}
            onChange={(event) => onNewPasswordChange(event.target.value)}
            autoComplete="new-password"
            required
            minLength={12}
            maxLength={128}
          />
        </AuthField>

        <AuthField label="تأكيد كلمة المرور">
          <AuthInput
            type="password"
            value={confirmPassword}
            onChange={(event) => onConfirmPasswordChange(event.target.value)}
            autoComplete="new-password"
            required
            minLength={12}
            maxLength={128}
          />
        </AuthField>

        {error && <AuthFeedback variant="error">{error}</AuthFeedback>}

        <AuthButton
          loading={submitting}
          loadingLabel="جاري إنشاء الحساب…"
          idleLabel="إنشاء الحساب"
        />

        <AuthSecondaryAction
          label="لديك حساب بالفعل؟ تسجيل الدخول"
          onClick={onBack}
        />
      </form>
    </AuthCard>
  );
}

// -- Utilities ----------------------------------------------------------

function cleanAccountAccessQuery(): void {
  const url = new URL(window.location.href);
  url.searchParams.delete("reset_token");
  url.searchParams.delete("invite");
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

function toMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}
