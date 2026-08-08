"use client";

/**
 * PasswordResetConfirmForm — Single Responsibility: collect a new password
 * and submit it with the reset token.
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

export interface PasswordResetConfirmFormProps {
  newPassword: string;
  confirmPassword: string;
  error: string;
  submitting: boolean;
  hasResetToken: boolean;
  onNewPasswordChange: (value: string) => void;
  onConfirmPasswordChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onCancel: () => void;
}

export function PasswordResetConfirmForm({
  newPassword,
  confirmPassword,
  error,
  submitting,
  hasResetToken,
  onNewPasswordChange,
  onConfirmPasswordChange,
  onSubmit,
  onCancel,
}: PasswordResetConfirmFormProps) {
  return (
    <AuthCard
      title="تعيين كلمة مرور جديدة"
      subtitle="استخدم 12 حرفًا على الأقل تشمل حرفًا كبيرًا وصغيرًا ورقمًا ورمزًا خاصًا."
    >
      <form onSubmit={onSubmit} className="space-y-5">
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
          disabled={!hasResetToken}
          loading={submitting}
          loadingLabel="جاري الحفظ…"
          idleLabel="حفظ كلمة المرور الجديدة"
        />

        <AuthSecondaryAction label="إلغاء والعودة للدخول" onClick={onCancel} />
      </form>
    </AuthCard>
  );
}
