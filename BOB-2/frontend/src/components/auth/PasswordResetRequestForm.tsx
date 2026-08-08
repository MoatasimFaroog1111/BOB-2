"use client";

/**
 * PasswordResetRequestForm — Single Responsibility: collect an email and
 * submit a password reset request. Pure presentational; transport and
 * state live in AuthGate.
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

export interface PasswordResetRequestFormProps {
  email: string;
  notice: string;
  error: string;
  submitting: boolean;
  onEmailChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onBack: () => void;
}

export function PasswordResetRequestForm({
  email,
  notice,
  error,
  submitting,
  onEmailChange,
  onSubmit,
  onBack,
}: PasswordResetRequestFormProps) {
  return (
    <AuthCard
      title="نسيت كلمة المرور؟"
      subtitle="أدخل بريد حسابك وسنرسل رابطًا آمنًا قصير الصلاحية."
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

        {notice && <AuthFeedback variant="notice">{notice}</AuthFeedback>}
        {error && <AuthFeedback variant="error">{error}</AuthFeedback>}

        <AuthButton
          loading={submitting}
          loadingLabel="جاري الإرسال…"
          idleLabel="إرسال رابط إعادة التعيين"
        />

        <AuthSecondaryAction
          label="العودة إلى تسجيل الدخول"
          onClick={onBack}
        />
      </form>
    </AuthCard>
  );
}
