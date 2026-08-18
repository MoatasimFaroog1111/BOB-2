"use client";

import { useMemo, useState } from "react";

import { useSmartAccountantReviewSubmission } from "@/features/documents/hooks/useSmartAccountantReviewSubmission";
import {
  listVatAccounts,
  type SmartAccountingInlineEdit,
} from "@/features/documents/model/smartAccountingInlineEdit";
import {
  formatAccountingMoney,
  type SmartAccountantProposalSummary,
  type SmartAccountantVerification,
} from "@/features/documents/model/smartAccountantWorkspace";
import type {
  OdooAccount,
  OdooAnalyticAccount,
  OdooPartner,
} from "@/features/documents/model/types";

export function SmartAccountingProposalCard({
  language,
  currency,
  proposal,
  verification,
  lineCount,
  accounts,
  partners,
  analyticAccounts,
  onInlineEdit,
  onEdit,
  onApprove,
}: Readonly<{
  language: string;
  currency: string;
  proposal: SmartAccountantProposalSummary;
  verification: SmartAccountantVerification;
  lineCount: number;
  accounts: OdooAccount[];
  partners: OdooPartner[];
  analyticAccounts: OdooAnalyticAccount[];
  onInlineEdit: (edit: SmartAccountingInlineEdit) => void;
  onEdit: () => void;
  onApprove: () => void;
}>) {
  const ar = language === "ar";
  const review = useSmartAccountantReviewSubmission();
  const [reviewMessage, setReviewMessage] = useState("");
  const [editMessage, setEditMessage] = useState("");
  const hasProposal = lineCount >= 2;
  const vatAccounts = useMemo(() => listVatAccounts(accounts), [accounts]);
  const vatCodes = useMemo(() => new Set(vatAccounts.map((account) => account.code)), [vatAccounts]);
  const primaryAccounts = useMemo(
    () => accounts.filter((account) => !vatCodes.has(account.code)),
    [accounts, vatCodes],
  );
  const selectedPartner = partners.find(
    (partner) => partner.name.trim().toLocaleLowerCase() === proposal.partnerName.trim().toLocaleLowerCase(),
  );
  const selectedAnalytic = analyticAccounts.find(
    (analytic) => analytic.name.trim().toLocaleLowerCase() === proposal.analyticName.trim().toLocaleLowerCase(),
  );

  if (!hasProposal) return null;

  const applyInlineEdit = (edit: SmartAccountingInlineEdit) => {
    onInlineEdit(edit);
    setEditMessage(
      ar
        ? "تم تحديث مسودة القيد. لم يتم ترحيل أي شيء إلى Odoo."
        : "Draft entry updated. Nothing was posted to Odoo.",
    );
  };

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

  return (
    <section className="mb-3 overflow-hidden rounded-2xl border border-amber-400/25 bg-gradient-to-b from-amber-400/[0.08] to-white/[0.025] shadow-lg">
      <div className="flex items-center justify-between gap-3 border-b border-white/10 px-3 py-2.5">
        <div>
          <div className="text-[10.5px] font-black text-amber-200">
            {ar ? "بطاقة القيد المحاسبي المقترح" : "Proposed Accounting Entry"}
          </div>
          <div className="mt-0.5 text-[8.5px] text-white/40">
            {ar ? "عدّل الحقول مباشرة — التغييرات تبقى في المسودة حتى المراجعة" : "Edit fields inline — changes stay in draft until review"}
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
        <InlineSelect
          label={ar ? "المورد / الشريك" : "Partner"}
          value={selectedPartner ? String(selectedPartner.id) : ""}
          placeholder={ar ? "اختر شريكًا" : "Select partner"}
          options={partners.map((partner) => ({ value: String(partner.id), label: partner.name }))}
          onChange={(value) => applyInlineEdit({ field: "partner", value })}
        />
        <InlineSelect
          label={ar ? "الحساب الرئيسي" : "Primary account"}
          value={proposal.primaryAccountCode}
          placeholder={ar ? "اختر حسابًا" : "Select account"}
          options={primaryAccounts.map((account) => ({
            value: account.code,
            label: `${account.code} · ${account.name}`,
          }))}
          onChange={(value) => applyInlineEdit({ field: "account", value })}
        />
        <InlineSelect
          label={ar ? "الضريبة VAT" : "VAT account"}
          value={proposal.taxAccountCode}
          placeholder={proposal.taxAccountCode
            ? (ar ? "اختر حساب VAT" : "Select VAT account")
            : (ar ? "لا يوجد سطر VAT قابل للتعديل" : "No VAT line to edit")}
          options={vatAccounts.map((account) => ({
            value: account.code,
            label: `${account.code} · ${account.name}`,
          }))}
          onChange={(value) => applyInlineEdit({ field: "tax", value })}
          disabled={!proposal.taxAccountCode}
          helper={proposal.taxAccountCode
            ? `${formatAccountingMoney(proposal.taxAmount, currency)} · ${proposal.taxAccountName}`
            : (ar ? "إضافة ضريبة جديدة تتطلب مراجعة المبلغ والمعالجة أولًا." : "Adding new VAT requires amount and treatment review first.")}
        />
        <InlineSelect
          label={ar ? "مركز التكلفة" : "Analytic / Cost center"}
          value={selectedAnalytic ? String(selectedAnalytic.id) : ""}
          placeholder={ar ? "بدون مركز تكلفة" : "No cost center"}
          options={analyticAccounts.map((analytic) => ({ value: String(analytic.id), label: analytic.name }))}
          onChange={(value) => applyInlineEdit({ field: "analytic", value })}
          allowEmpty
        />
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

      {(editMessage || reviewMessage || review.error) && (
        <div className={`mx-3 mt-2 rounded-lg border px-2.5 py-2 text-[9px] ${review.error ? "border-red-400/20 bg-red-400/10 text-red-200" : "border-emerald-400/20 bg-emerald-400/10 text-emerald-200"}`}>
          {review.error || reviewMessage || editMessage}
        </div>
      )}

      <div className="grid grid-cols-3 gap-1.5 p-3">
        <button type="button" onClick={onEdit} className="rounded-lg border border-white/15 bg-white/[0.04] px-2 py-2 text-[9px] font-bold text-white/75 hover:bg-white/[0.08]">
          {ar ? "مراجعة كاملة" : "Full review"}
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
          ? "التعديل المباشر يغيّر المسودة فقط. الاعتماد يفتح مسار المراجعة الحالي، ولا يستطيع نص AI الحر الترحيل مباشرة إلى Odoo."
          : "Inline editing changes the draft only. Approval opens the existing review flow; free-form AI text cannot post directly to Odoo."}
      </p>
    </section>
  );
}

function InlineSelect({
  label,
  value,
  placeholder,
  options,
  onChange,
  disabled = false,
  helper,
  allowEmpty = false,
}: {
  label: string;
  value: string;
  placeholder: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
  disabled?: boolean;
  helper?: string;
  allowEmpty?: boolean;
}) {
  return (
    <label className="min-w-0 rounded-xl border border-white/10 bg-black/20 p-2.5">
      <span className="block text-[8px] text-white/40">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className="mt-1 w-full min-w-0 rounded-lg border border-white/10 bg-[#170b04] px-2 py-1.5 text-[9px] font-bold text-white/85 outline-none focus:border-amber-400/40 disabled:cursor-not-allowed disabled:opacity-45"
      >
        <option value="" disabled={!allowEmpty}>{placeholder}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
      {helper && <span className="mt-1 block truncate text-[7.5px] text-white/35" title={helper}>{helper}</span>}
    </label>
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
