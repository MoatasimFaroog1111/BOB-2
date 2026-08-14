"use client";

interface DailyBankReviewStatusStripProps {
  language: string;
  entryCount: number;
  transactionCount: number;
  unresolvedCount: number;
  lowConfidenceCount: number;
  submitted: boolean;
  submitting: boolean;
  error?: string;
  onAction: () => void;
}

export function DailyBankReviewStatusStrip({
  language,
  entryCount,
  transactionCount,
  unresolvedCount,
  lowConfidenceCount,
  submitted,
  submitting,
  error = "",
  onAction,
}: DailyBankReviewStatusStripProps) {
  const ar = language === "ar";
  const actionLabel = submitting
    ? (ar ? "جاري الإرسال..." : "Sending...")
    : submitted
      ? (ar ? "فتح المدقق" : "Open Auditor")
      : (ar ? "إرسال للمراجعة" : "Send for Review");

  return (
    <aside
      aria-live="polite"
      className="mx-3 mt-2 mb-1 rounded-lg border border-amber-400/20 bg-amber-500/[0.045] px-2 py-1.5 text-white"
      dir={ar ? "rtl" : "ltr"}
    >
      <div className="flex min-w-0 items-center gap-2">
        <span
          aria-hidden="true"
          className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-300"
        />

        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="max-w-full truncate text-[10px] font-bold text-amber-200 md:text-[11px]">
              {ar ? "مسودة البنك جاهزة للمراجعة" : "Bank draft ready for review"}
            </span>

            <span className="text-[9px] text-white/60">
              {entryCount} {ar ? "قيد" : "entries"}
            </span>
            <span className="text-[9px] text-white/60">
              {transactionCount} {ar ? "حركة" : "transactions"}
            </span>
            <span className="text-[9px] text-amber-200/85">
              {unresolvedCount} {ar ? "غير محلول" : "unresolved"}
            </span>
            <span className="text-[9px] text-amber-200/85">
              {lowConfidenceCount} {ar ? "ثقة منخفضة" : "low confidence"}
            </span>
            <span
              className="hidden text-[9px] text-emerald-300/80 sm:inline"
              title={ar ? "لا يوجد ترحيل إلى Odoo في هذه المرحلة" : "No Odoo posting at this stage"}
            >
              {ar ? "مراجعة فقط · بدون ترحيل Odoo" : "Review only · no Odoo posting"}
            </span>
          </div>

          {error && (
            <div
              className="mt-0.5 max-w-full truncate text-[9px] text-red-300"
              title={error}
              role="alert"
            >
              {error}
            </div>
          )}
        </div>

        <button
          type="button"
          onClick={onAction}
          disabled={submitting}
          className="h-7 shrink-0 rounded-md border border-amber-300/25 bg-amber-300/90 px-2.5 text-[10px] font-bold text-black transition-colors hover:bg-amber-200 disabled:cursor-not-allowed disabled:opacity-50"
          aria-label={actionLabel}
        >
          {actionLabel}
        </button>
      </div>
    </aside>
  );
}
