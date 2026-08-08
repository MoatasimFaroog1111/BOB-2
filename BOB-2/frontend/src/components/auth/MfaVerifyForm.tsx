"use client";

/**
 * MfaVerifyForm — Single Responsibility: collect a 6-digit MFA code.
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

export interface MfaVerifyFormProps {
  code: string;
  error: string;
  submitting: boolean;
  onCodeChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onBack: () => void;
}

export function MfaVerifyForm({
  code,
  error,
  submitting,
  onCodeChange,
  onSubmit,
  onBack,
}: MfaVerifyFormProps) {
  return (
    <AuthCard
      title="التحقق بخطوتين"
      subtitle="أدخل الرمز المكوّن من 6 أرقام من تطبيق المصادقة."
    >
      <form onSubmit={onSubmit} className="space-y-5">
        <AuthField label="رمز التحقق">
          <AuthInput
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            onChange={(event) =>
              onCodeChange(event.target.value.replace(/\D/g, "").slice(0, 6))
            }
            required
            minLength={6}
            maxLength={6}
            inputClassName="w-full rounded-lg border border-white/15 bg-white/5 px-3 py-2.5 text-center text-2xl tracking-[0.4em] outline-none focus:border-amber-400"
          />
        </AuthField>

        {error && <AuthFeedback variant="error">{error}</AuthFeedback>}

        <AuthButton
          disabled={code.length !== 6}
          loading={submitting}
          loadingLabel="جاري التحقق…"
          idleLabel="تحقق"
        />

        <AuthSecondaryAction
          label="العودة إلى تسجيل الدخول"
          onClick={onBack}
        />
      </form>
    </AuthCard>
  );
}
