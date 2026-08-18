"use client";

import { useState } from "react";

import type { OdooJournal } from "@/features/documents/model/types";

export type SmartAccountantWorkspaceMode = "assistant" | "sheet";

export function SmartAccountantCockpitBar({
  language,
  mode,
  onModeChange,
  journals,
  selectedJournalId,
  onJournalChange,
  journalsLoading,
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
  const [open, setOpen] = useState(false);

  return (
    <div className="pointer-events-none fixed bottom-5 left-5 z-40" dir={ar ? "rtl" : "ltr"}>
      <div className="pointer-events-auto flex flex-col items-start gap-2">
        {open ? (
          <div className="w-64 rounded-2xl border border-white/10 bg-[#120a05]/95 p-3 shadow-2xl backdrop-blur-xl">
            <div className="text-[9px] font-bold text-white/45">
              {ar ? "أدوات متقدمة" : "Advanced tools"}
            </div>

            <label className="mt-3 block text-[9px] font-semibold text-white/45">
              {ar ? "اليومية" : "Journal"}
            </label>
            {journalsLoading ? (
              <div className="mt-1 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-[10px] text-white/35">
                ...
              </div>
            ) : (
              <select
                value={selectedJournalId || ""}
                onChange={(event) => onJournalChange(event.target.value ? Number(event.target.value) : null)}
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-2.5 py-2 text-[10px] font-semibold text-white/80 outline-none"
                aria-label={ar ? "اختيار اليومية" : "Select journal"}
              >
                {journals.map((journal) => (
                  <option key={journal.id} value={journal.id} className="bg-[#170b04] text-white">
                    {journal.name} ({journal.code})
                  </option>
                ))}
              </select>
            )}

            <button
              type="button"
              onClick={() => {
                onModeChange(mode === "assistant" ? "sheet" : "assistant");
                setOpen(false);
              }}
              className="mt-3 w-full rounded-lg border border-amber-400/20 bg-amber-400/[0.06] px-3 py-2 text-[10px] font-bold text-amber-200 transition hover:bg-amber-400/10"
            >
              {mode === "assistant"
                ? (ar ? "فتح الجدول المتقدم" : "Open advanced spreadsheet")
                : (ar ? "العودة للمحاسب الذكي" : "Back to Smart Accountant")}
            </button>
          </div>
        ) : null}

        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="rounded-full border border-white/10 bg-black/55 px-3 py-1.5 text-[9px] font-bold text-white/45 shadow-lg backdrop-blur-md transition hover:border-white/20 hover:bg-black/70 hover:text-white/75"
          aria-expanded={open}
        >
          {open ? (ar ? "إغلاق" : "Close") : (ar ? "أدوات" : "Tools")}
        </button>
      </div>
    </div>
  );
}
