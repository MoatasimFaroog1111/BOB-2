"use client";

/**
 * LoginForm — Single Responsibility: render and submit the login form.
 *
 * Open/Closed: extends the AuthCard primitives. Behavior is injected
 * via props (onSubmit, onForgot, error, submitting) so this component
 * never grows new branches when requirements change.
 */

import { FormEvent } from "react";
import {
  AuthButton,
  AuthCard,
  AuthFeedback,
  AuthField,
  AuthInput,
  AuthSecondaryAction,
} from "./AuthCard";

export interface LoginFormProps {
  email: string;
  password: string;
  error: string;
  notice: string;
  submitting: boolean;
  onEmailChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onForgotPassword: () => void;
  onCreateAccount: () => void;
}

export function LoginForm({
  email,
  password,
  error,
  notice,
  submitting,
  onEmailChange,
  onPasswordChange,
  onSubmit,
  onForgotPassword,
  onCreateAccount,
}: LoginFormProps) {
  return (
    <AuthCard
      title="GuardianAI"
      subtitle="سجّل الدخول للوصول إلى البيانات المحاسبية."
    >
      <form onSubmit={onSubmit} className="space-y-5">
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

        <AuthField label="كلمة المرور">
          <AuthInput
            type="password"
            value={password}
            onChange={(event) => onPasswordChange(event.target.value)}
            autoComplete="current-password"
            required
            minLength={1}
            maxLength={128}
          />
        </AuthField>

        {error && <AuthFeedback variant="error">{error}</AuthFeedback>}
        {notice && <AuthFeedback variant="notice">{notice}</AuthFeedback>}

        <AuthButton
          loading={submitting}
          loadingLabel="جاري الدخول…"
          idleLabel="تسجيل الدخول"
        />

        <AuthSecondaryAction
          label="نسيت كلمة المرور؟"
          onClick={onForgotPassword}
        />

        <AuthSecondaryAction
          label="لديك دعوة؟ إنشاء حساب جديد"
          onClick={onCreateAccount}
        />
      </form>
    </AuthCard>
  );
}
