"use client";

import { useEffect, useRef, useState } from "react";

import { useSmartAccountantReviewSubmission } from "@/features/documents/hooks/useSmartAccountantReviewSubmission";
import { emitSmartAccountantUiAction } from "@/features/documents/model/smartAccountantUiEvents";

export function SpreadsheetWorkspaceControls({
  language,
  onAddRow,
  onDeleteRow,
  onAddColumn,
  onDeleteColumn,
  onClear,
  onExport,
}: Readonly<{
  language: string;
  onAddRow: () => void;
  onDeleteRow: () => void;
  onAddColumn: () => void;
  onDeleteColumn: () => void;
  onClear: () => void;
  onExport: () => void;
}>) {
  const ar = language === "ar";
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const bankReview = useSmartAccountantReviewSubmission();
  const isBankReviewWorkspace = Boolean(bankReview.draft);
  const bankReviewBusy = bankReview.state === "submitting";
  const bankReviewSubmitted = bankReview.state === "submitted" || Boolean(bankReview.draft?.submitted);
  const bankReviewUnavailable = isBankReviewWorkspace && !bankReview.canSubmit && !bankReviewBusy && !bankReviewSubmitted;

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const run = (action: () => void) => {
    action();
    setOpen(false);
  };

  const handlePrimaryAction = () => {
    if (!isBankReviewWorkspace) {
      emitSmartAccountantUiAction({ type: "review-entry" });
      return;
    }

    if (!bankReview.canSubmit || bankReviewBusy || bankReviewSubmitted) return;
    void bankReview.submit().catch(() => {
      // The hook exposes the failure inline below the toolbar; avoid a blocking browser alert.
    });
  };

  const primaryLabel = isBankReviewWorkspace
    ? bankReviewBusy
      ? (ar ? "جاري الإرسال للمراجعة..." : "Sending for review...")
      : bankReviewSubmitted
        ? (ar ? "✓ تم الإرسال للمراجعة" : "✓ Sent for review")
        : (ar ? "↗ إرسال للمراجعة" : "↗ Send for review")
    : (ar ? "✓ تسجيل القيد" : "✓ Register entry");

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-white/10 bg-black/20 p-2.5">
      <button
        type="button"
        onClick={handlePrimaryAction}
        disabled={bankReviewBusy || bankReviewSubmitted || bankReviewUnavailable}
        className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-1.5 text-[9.5px] font-black text-amber-200 shadow-sm transition hover:bg-amber-400/15 hover:text-amber-100 disabled:cursor-not-allowed disabled:opacity-55"
      >
        {primaryLabel}
      </button>

      <div className="relative" ref={menuRef}>
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[9.5px] font-bold text-white/70 hover:bg-white/[0.08]"
        >
          {ar ? "أدوات الجدول ▾" : "Table tools ▾"}
        </button>
        {open ? (
          <div className="absolute start-0 top-9 z-50 w-44 overflow-hidden rounded-xl border border-white/15 bg-[#170b04] p-1 shadow-2xl">
            <ToolButton onClick={() => run(onAddRow)} label={ar ? "+ إضافة صف" : "+ Add row"} />
            <ToolButton onClick={() => run(onDeleteRow)} label={ar ? "− حذف صف" : "− Delete row"} />
            <ToolButton onClick={() => run(onAddColumn)} label={ar ? "+ إضافة عمود" : "+ Add column"} />
            <ToolButton onClick={() => run(onDeleteColumn)} label={ar ? "− حذف عمود" : "− Delete column"} />
            <div className="my-1 h-px bg-white/10" />
            <ToolButton danger onClick={() => run(onClear)} label={ar ? "مسح الجدول" : "Clear sheet"} />
          </div>
        ) : null}
      </div>

      <button
        type="button"
        onClick={onExport}
        className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[9.5px] font-bold text-white/60 hover:bg-white/[0.08] hover:text-white"
      >
        {ar ? "تصدير CSV" : "Export CSV"}
      </button>

      {bankReview.error ? (
        <span className="max-w-md truncate text-[8.5px] font-semibold text-red-300" title={bankReview.error}>
          {ar ? "تعذر إرسال مراجعة البنك — راجع الاتصال ثم أعد المحاولة" : "Bank review submission failed — check the connection and retry"}
        </span>
      ) : null}

      <span className="ms-auto text-[8.5px] text-white/35">
        {isBankReviewWorkspace
          ? (ar ? "كشف البنك يمر عبر المدقق الذكي قبل أي ترحيل إلى Odoo" : "Bank review goes through Smart Auditor before any Odoo posting")
          : (ar ? "الجدول أداة مساعدة — مكتب AI هو مساحة العمل الأساسية" : "Spreadsheet is a tool — AI Desk is the primary workspace")}
      </span>
    </div>
  );
}

function ToolButton({
  label,
  onClick,
  danger = false,
}: {
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`block w-full rounded-lg px-2.5 py-2 text-start text-[9.5px] font-semibold transition ${
        danger ? "text-red-300 hover:bg-red-400/10" : "text-white/70 hover:bg-white/[0.06] hover:text-white"
      }`}
    >
      {label}
    </button>
  );
}
