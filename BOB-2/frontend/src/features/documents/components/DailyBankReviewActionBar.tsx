"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { documentsGateway } from "@/features/documents/api/documentsGateway";
import type { DailyBankReviewDraft } from "@/features/documents/lib/dailyBankReview";
import {
  DAILY_BANK_REVIEW_EVENT,
  loadDailyBankReviewDraft,
  saveDailyBankReviewDraft,
} from "@/features/documents/lib/dailyBankReviewSession";
import { useLanguage } from "@/lib/LanguageContext";

export function DailyBankReviewActionBar() {
  const { language } = useLanguage();
  const router = useRouter();
  const [draft, setDraft] = useState<DailyBankReviewDraft | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const refresh = () => setDraft(loadDailyBankReviewDraft());
    refresh();
    window.addEventListener(DAILY_BANK_REVIEW_EVENT, refresh);
    return () => window.removeEventListener(DAILY_BANK_REVIEW_EVENT, refresh);
  }, []);

  if (!draft) return null;

  const submitForReview = async () => {
    if (submitting || draft.submitted) {
      if (draft.submitted) router.push("/audit");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const response = await documentsGateway.submitDailyBankReview({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: draft.documentId,
          journal_id: draft.journalId,
          company_id: draft.companyId || null,
        }),
      });
      if (!response.ok) throw new Error(await response.text());
      const result = await response.json();
      const reviewIds = Array.isArray(result.reviews)
        ? result.reviews.map((item: any) => Number(item.approval_id)).filter(Number.isFinite)
        : [];
      const submittedDraft = { ...draft, submitted: true, reviewIds };
      saveDailyBankReviewDraft(submittedDraft);
      setDraft(submittedDraft);
      router.push("/audit");
    } catch (err: any) {
      console.error(err);
      setError(String(err?.message || err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed z-[120] bottom-4 left-1/2 -translate-x-1/2 w-[min(920px,calc(100vw-32px))] rounded-2xl border border-amber-500/40 bg-[#140a03]/95 shadow-2xl backdrop-blur-xl px-4 py-3 text-white"
      dir={language === "ar" ? "rtl" : "ltr"}
    >
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-xs font-bold text-amber-300">
            {language === "ar" ? "مسودة قيود البنك اليومية جاهزة للمراجعة" : "Daily bank journal draft is ready for review"}
          </div>
          <div className="mt-1 text-[10px] text-white/65 flex flex-wrap gap-x-3 gap-y-1">
            <span>{language === "ar" ? "القيود" : "Entries"}: {draft.entries.length}</span>
            <span>{language === "ar" ? "الحركات" : "Transactions"}: {draft.transactionCount}</span>
            <span>{language === "ar" ? "غير محلول" : "Unresolved"}: {draft.unresolvedCount}</span>
            <span>{language === "ar" ? "ثقة منخفضة" : "Low confidence"}: {draft.lowConfidenceCount}</span>
            <span className="text-emerald-300">
              {language === "ar" ? "لا يوجد ترحيل إلى Odoo في هذه المرحلة" : "No Odoo posting at this stage"}
            </span>
          </div>
          {error && <div className="mt-1 text-[10px] text-red-300 break-all">{error}</div>}
        </div>

        <button
          type="button"
          onClick={submitForReview}
          disabled={submitting}
          className="h-9 px-5 rounded-xl bg-gradient-to-r from-amber-500 to-yellow-500 hover:from-amber-400 hover:to-yellow-400 text-black text-xs font-black shadow-lg disabled:opacity-50 disabled:cursor-not-allowed transition-all"
        >
          {submitting
            ? (language === "ar" ? "جاري الإرسال..." : "Sending...")
            : draft.submitted
              ? (language === "ar" ? "فتح المدقق الذكي" : "Open Smart Auditor")
              : (language === "ar" ? "إرسال للمراجعة" : "Send for Review")}
        </button>
      </div>
    </div>
  );
}
