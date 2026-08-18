"use client";

import type { OdooJournal } from "@/features/documents/model/types";

export type SmartAccountantWorkspaceMode = "assistant" | "sheet";

export function SmartAccountantCockpitBar({
  language,
  mode,
  onModeChange,
  companyName,
  currency,
  journals,
  selectedJournalId,
  onJournalChange,
  journalsLoading,
  onManualEntry,
  onReview,
}: Readonly<{
  language: string;
  mode: SmartAccountantWorkspaceMode;
  onModeChange: (mode: SmartAccountantWorkspaceMode) => void;
  companyName?: string;
  currency?: string;
  journals: OdooJournal[];
  selectedJournalId: number | null;
  onJournalChange: (journalId: number | null) => void;
  journalsLoading: boolean;
  onManualEntry: () => void;
  onReview: () => void;
}>) {
  const ar = language === "ar";

  return (
    <section className="shrink-0 rounded-2xl border border-white/10 bg-black/35 p-2.5 shadow-xl backdrop-blur-xl">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-xl border border-white/10 bg-black/30 p-1">
          <ModeButton
            active={mode === "assistant"}
            onClick={() => onModeChange("assistant")}
            icon="✦"
            label={ar ? "مكتب AI" : "AI Desk"}
          />
          <ModeButton
            active={mode === "sheet"}
            onClick={() => onModeChange("sheet")}
            icon="▦"
            label={ar ? "الجدول" : "Spreadsheet"}
          />
        </div>

        <div className="hidden h-7 w-px bg-white/10 md:block" />

        <div className="min-w-[10rem] flex-1 md:flex-none">
          <div className="text-[8px] font-semibold uppercase tracking-[0.16em] text-white/30">
            {ar ? "السياق الحالي" : "Current context"}
          </div>
          <div className="mt-0.5 truncate text-[10px] font-bold text-white/75">
            {companyName || (ar ? "لم يتم اختيار شركة" : "No company selected")}
            {currency ? ` · ${currency}` : ""}
          </div>
        </div>

        <div className="flex min-w-[12rem] items-center gap-2 rounded-xl border border-white/10 bg-white/[0.035] px-2.5 py-1.5">
          <span className="shrink-0 text-[9px] text-white/40">{ar ? "اليومية" : "Journal"}</span>
          {journalsLoading ? (
            <span className="text-[10px] text-white/40">...</span>
          ) : (
            <select
              value={selectedJournalId || ""}
              onChange={(event) => onJournalChange(event.target.value ? Number(event.target.value) : null)}
              className="min-w-0 flex-1 bg-transparent text-[10px] font-semibold text-white/80 outline-none"
              aria-label={ar ? "اختيار اليومية" : "Select journal"}
            >
              {journals.map((journal) => (
                <option key={journal.id} value={journal.id} className="bg-[#170b04] text-white">
                  {journal.name} ({journal.code})
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5 md:ms-auto">
          <button
            type="button"
            onClick={onManualEntry}
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-[9.5px] font-bold text-white/70 transition hover:bg-white/[0.08] hover:text-white"
          >
            {ar ? "✎ إدخال يدوي" : "✎ Manual entry"}
          </button>
          <button
            type="button"
            onClick={onReview}
            className="rounded-xl bg-gradient-to-r from-amber-400 to-yellow-500 px-3.5 py-2 text-[9.5px] font-black text-black shadow-lg transition hover:brightness-110"
          >
            {ar ? "مراجعة القيد" : "Review entry"}
          </button>
        </div>
      </div>
    </section>
  );
}

function ModeButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: string;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[9.5px] font-bold transition ${
        active
          ? "bg-amber-400/15 text-amber-200 shadow-[inset_0_0_0_1px_rgba(251,191,36,0.25)]"
          : "text-white/45 hover:bg-white/[0.05] hover:text-white/75"
      }`}
    >
      <span>{icon}</span>
      <span>{label}</span>
    </button>
  );
}
