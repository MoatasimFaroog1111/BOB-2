"use client";

import { useState } from "react";

import { useSmartAccountantReviewSubmission } from "@/features/documents/hooks/useSmartAccountantReviewSubmission";
import {
  formatAccountingMoney,
  type SmartAccountantProposalSummary,
  type SmartAccountantVerification,
} from "@/features/documents/model/smartAccountantWorkspace";

export function SmartAccountingProposalCard({
  language,
  currency,
  proposal,
  verification,
  lineCount,
  onEdit,
  onApprove,
}: Readonly<{
  language: string;
  currency: string;
  proposal: SmartAccountantProposalSummary;
  verification: SmartAccountantVerification;
  lineCount: number;
  onEdit: () => void;
  onApprove: () => void;
}>) {
  const ar = language === "ar";
  const review = useSmartAccountantReviewSubmission();
  const [reviewMessage, setReviewMessage] = useState("");
  const hasProposal = lineCount >= 2;

  if (!hasProposal) return null;

  const sendToAuditor = async () => {
    if (!review.canSubmit) return;
    setReviewMessage("");
    try {
      const result = await review.submit();
      const count = Number(result?.review_count || review.draft?.reviewIds?.length || 0);
      setReviewMessage(
        ar
          ? `تم إرسال ${count.toLocaleString()} قيد إلى المدقق الذكي بدون ترحيل إلى Odoo.`
          : `${count.toLocaleString()} entries were sent to Smart Auditor without posting to Odoo.`,
      );
    } catch {
      setReviewMessage(
        ar ? "تعذر إرسال حزمة المراجعة. راجع رسالة الخطأ أدناه." : "Could not submit the review package. See the error below.",
      );
    }
  };

  const accountLabel = [proposal.primaryAccountCode, proposal.primaryAccountName].filter(Boolean).join(" · ");
  const taxLabel = proposal.taxAccountCode
    ? `${formatAccountingMoney(proposal.taxAmount, currency)} · ${proposal.taxAccountCode}`
    : (ar ? "لم يُكتشف سطر VAT مؤكد" : "No verified VAT line detected");

  return (
    <section className="mb-3 overflow-hidden rounded-2xl border border-amber-400/25 bg-gradient-to-b from-amber-400/[0.08] to-white/[0.025] shadow-lg">
      <div className="flex items-center justify-between gap-3 border-b border-white/10 px-3 py-2.5">
        <div>
          <div className="text-[10.5px] font-black text-amber-200">
            {ar ? "بطاقة القيد المحاسبي المقترح" : "Proposed Accounting Entry"}
          </div>
          <div className="mt-0.5 text-[8.5px] text-white/40">
            {ar ? "مبنية من القيد الحالي ومراجع Odoo المتاحة" : "Derived from the current entry and available Odoo references"}
          </div>
        </div>
        <div className="text-end">
          <div className="text-[8px] text-white/40">{ar ? "التحقق" : "Verification"}</div>
          <div className={`text-sm font-black ${verification.score >= 80 ? "text-emerald-300" : "text-amber-300"}`}>
            {verification.score}%
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 p-3">
        <Fact label={ar ? "المورد / الشريك" : "Partner"} value={proposal.partnerName || (ar ? "غير محدد" : "Not identified")} />
        <Fact label={ar ? "الحساب الرئيسي" : "Primary account"} value={accountLabel || (ar ? "غير محدد" : "Not identified")} />
        <Fact label={ar ? "الضريبة VAT" : "VAT"} value={taxLabel} />
        <Fact label={ar ? "مركز التكلفة" : "Analytic / Cost center"} value={proposal.analyticName || (ar ? "غير محدد" : "Not identified")} />
      </div>

      <div className="mx-3 rounded-xl border border-white/10 bg-black/25 p-2.5">
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="text-[9px] font-bold text-white/55">{ar ? "أدلة التحقق" : "Verification evidence"}</span>
          <span className={`rounded-full px-2 py-0.5 text-[8px] font-bold ${verification.balanced ? "bg-emerald-400/10 text-emerald-300" : "bg-red-400/10 text-red-300"}`}>
            {verification.balanced ? (ar ? "متوازن" : "Balanced") : (ar ? "غير متوازن" : "Unbalanced")}
          </span>
        </div>
        <div className="grid grid-cols-3 gap-1 text-center">
          <Evidence value={`${verification.rowsWithKnownAccounts}/${verification.accountCodeCount}`} label={ar ? "حسابات Odoo" : "Odoo accounts"} />
          <Evidence value={`${verification.rowsWithKnownPartners}/${verification.partnerCount}`} label={ar ? "الشركاء" : "Partners"} />
          <Evidence value={`${verification.rowsWithKnownAnalytics}/${verification.analyticCount}`} label={ar ? "التحليلي" : "Analytics"} />
        </div>
      </div>

      {(reviewMessage || review.error) && (
        <div className={`mx-3 mt-2 rounded-lg border px-2.5 py-2 text-[9px] ${review.error ? "border-red-400/20 bg-red-400/10 text-red-200" : "border-emerald-400/20 bg-emerald-400/10 text-emerald-200"}`}>
          {review.error || reviewMessage}
        </div>
      )}

      <div className="grid grid-cols-3 gap-1.5 p-3">
        <button type="button" onClick={onEdit} className="rounded-lg border border-white/15 bg-white/[0.04] px-2 py-2 text-[9px] font-bold text-white/75 hover:bg-white/[0.08]">
          {ar ? "تعديل" : "Edit"}
        </button>
        <button
          type="button"
          onClick={sendToAuditor}
          disabled={!review.canSubmit || review.state === "submitting"}
          title={!review.canSubmit ? (ar ? "الإرسال المباشر متاح لحزمة مراجعة البنك المُعدة. القيود العامة تمر أولاً عبر شاشة المراجعة." : "Direct submission is available for a prepared bank review package. General entries go through the review screen first.") : undefined}
          className="rounded-lg border border-sky-400/20 bg-sky-400/[0.08] px-2 py-2 text-[9px] font-bold text-sky-200 hover:bg-sky-400/15 disabled:cursor-not-allowed disabled:opacity-35"
        >
          {review.state === "submitting" ? (ar ? "جاري الإرسال..." : "Sending...") : review.state === "submitted" ? (ar ? "أُرسل للمدقق" : "Sent to auditor") : (ar ? "إرسال للمدقق" : "Send to auditor")}
        </button>
        <button
          type="button"
          onClick={onApprove}
          className="rounded-lg bg-emerald-600 px-2 py-2 text-[9px] font-black text-white hover:bg-emerald-500"
          title={ar ? "يفتح شاشة المراجعة البشرية الحالية؛ لا يتم الترحيل مباشرة من البطاقة." : "Opens the existing human review screen; this card never posts directly."}
        >
          {ar ? "اعتماد" : "Approve"}
        </button>
      </div>

      <p className="px-3 pb-3 text-[8px] leading-relaxed text-white/35">
        {ar
          ? "الاعتماد يفتح مسار المراجعة الحالي. لا يستطيع نص AI الحر ترحيل القيد مباشرة إلى Odoo."
          : "Approval opens the existing review flow. Free-form AI text cannot post the entry directly to Odoo."}
      </p>
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-xl border border-white/10 bg-black/20 p-2.5">
      <div className="text-[8px] text-white/40">{label}</div>
      <div className="mt-1 truncate text-[9.5px] font-bold text-white/80" title={value}>{value}</div>
    </div>
  );
}

function Evidence({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded-lg bg-white/[0.04] p-1.5">
      <div className="text-[10px] font-black text-white/80">{value}</div>
      <div className="mt-0.5 text-[7.5px] text-white/35">{label}</div>
    </div>
  );
}
