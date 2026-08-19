import type { ButtonHTMLAttributes } from "react";

type ButtonVariant = "primary" | "secondary" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "h-9 px-5 rounded-xl bg-gradient-to-br from-[#221205] to-[#0f0701] border border-green-500 text-green-400 font-bold text-xs shadow-[0_0_12px_rgba(16,185,129,0.2)] hover:shadow-[0_0_20px_rgba(16,185,129,0.5)] transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed",
  secondary:
    "h-9 px-4 rounded-xl border border-white/15 hover:border-white/30 text-white/70 hover:text-white font-bold text-xs cursor-pointer transition-all disabled:opacity-50 disabled:cursor-not-allowed",
  ghost:
    "h-6 px-2.5 rounded-full border border-white/15 hover:border-white/30 text-white/60 hover:text-white text-[10px] font-bold cursor-pointer",
};

/** Shared button primitive covering the modal action styles duplicated across features/documents. */
export function Button({ variant = "secondary", className, ...rest }: ButtonProps) {
  const classes = [VARIANT_CLASSES[variant], className].filter(Boolean).join(" ");
  return <button className={classes} {...rest} />;
}
