"use client";

/**
 * Reusable auth card primitives.
 *
 * Single Responsibility: pure presentational components that render form
 * markup. They own no transport logic and no state machine — that lives in
 * AuthGate. This keeps each form < 50 lines and trivially testable.
 */

import { FormEvent, ReactNode } from "react";

interface CardProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
}

export function AuthCard({ title, subtitle, children }: CardProps) {
  return (
    <div className="min-h-screen bg-slate-950 text-white grid place-items-center p-6">
      <form
        onSubmit={(event) => event.preventDefault()}
        className="w-full max-w-md rounded-2xl border border-white/10 bg-black/40 p-7 shadow-2xl space-y-5"
      >
        <div>
          <h1 className="text-2xl font-bold">{title}</h1>
          {subtitle && <p className="mt-2 text-sm text-white/55">{subtitle}</p>}
        </div>
        {children}
      </form>
    </div>
  );
}

interface FieldProps {
  label: string;
  htmlFor?: string;
  children: ReactNode;
}

export function AuthField({ label, htmlFor, children }: FieldProps) {
  return (
    <label htmlFor={htmlFor} className="block space-y-2">
      <span className="text-sm text-white/70">{label}</span>
      {children}
    </label>
  );
}

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  inputClassName?: string;
}

export function AuthInput({ inputClassName, ...rest }: InputProps) {
  const baseClass =
    "w-full rounded-lg border border-white/15 bg-white/5 px-3 py-2.5 outline-none focus:border-amber-400";
  return (
    <input
      {...rest}
      className={inputClassName ?? baseClass}
    />
  );
}

interface ButtonProps {
  type?: "button" | "submit";
  onClick?: (event: FormEvent<HTMLFormElement>) => void;
  disabled?: boolean;
  loading?: boolean;
  loadingLabel: string;
  idleLabel: string;
  variant?: "primary" | "ghost";
}

export function AuthButton({
  type = "submit",
  onClick,
  disabled,
  loading,
  loadingLabel,
  idleLabel,
  variant = "primary",
}: ButtonProps) {
  const className =
    variant === "primary"
      ? "w-full rounded-lg bg-amber-400 px-4 py-2.5 font-semibold text-black disabled:opacity-50"
      : "w-full text-sm text-white/60 hover:text-white";
  return (
    <button
      type={type === "submit" ? "submit" : "button"}
      onClick={onClick as unknown as React.MouseEventHandler<HTMLButtonElement>}
      disabled={disabled}
      className={className}
    >
      {loading ? loadingLabel : idleLabel}
    </button>
  );
}

interface FeedbackProps {
  variant: "error" | "notice";
  children: ReactNode;
}

export function AuthFeedback({ variant, children }: FeedbackProps) {
  const isError = variant === "error";
  const className = isError
    ? "rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200"
    : "rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-200";
  return (
    <p role={isError ? "alert" : "status"} className={className}>
      {children}
    </p>
  );
}

interface SecondaryActionProps {
  label: string;
  onClick: () => void;
}

export function AuthSecondaryAction({ label, onClick }: SecondaryActionProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-sm text-white/60 hover:text-white"
    >
      {label}
    </button>
  );
}
