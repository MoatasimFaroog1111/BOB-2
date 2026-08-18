"use client";

import { type ReactNode, useEffect, useMemo, useState } from "react";

import {
  emitSmartAccountantUiAction,
  SMART_ACCOUNTANT_UI_ACTION_EVENT,
  type SmartAccountantUiAction,
} from "@/features/documents/model/smartAccountantUiEvents";
import type { OdooJournal } from "@/features/documents/model/types";

export type SmartAccountantWorkspaceMode = "assistant" | "sheet";

const PIN_STORAGE_KEY = "guardian.smartAccountant.sidebarPinned.v1";

const assistantActions = [
  {
    key: "create",
    icon: "✎",
    ar: "إنشاء قيد",
    en: "Create journal",
    promptAr: "ساعدني في إنشاء قيد محاسبي جديد من البيانات الموجودة، وتحقق من الحسابات والشريك والضريبة قبل أي تنفيذ.",
    promptEn: "Help me create a new journal entry from the available data and validate accounts, partner and tax before any execution.",
  },
  {
    key: "search",
    icon: "⌕",
    ar: "بحث في Odoo",
    en: "Search Odoo",
    promptAr: "ابحث في بيانات Odoo الحالية عن الحساب أو الشريك المرتبط بما هو موجود في ورقة العمل واشرح أفضل نتيجة بدون تعديل البيانات.",
    promptEn: "Search current Odoo data for the account or partner related to this worksheet and explain the best result without modifying data.",
  },
  {
    key: "account",
    icon: "▣",
    ar: "تحليل حساب",
    en: "Analyze account",
    promptAr: "حلل البيانات المحاسبية الحالية وحدد الحسابات المستخدمة والفروقات أو المخاطر التي تحتاج مراجعة، بدون تنفيذ أي تعديل.",
    promptEn: "Analyze the current accounting data and identify used accounts, variances or risks needing review without making changes.",
  },
  {
    key: "tax",
    icon: "%",
    ar: "مراجعة ضريبة",
    en: "Review tax",
    promptAr: "راجع المعالجة الضريبية للبيانات الحالية، وحدد ما يحتاج تحققاً بشرياً قبل اعتماد القيد. لا تنفذ أي ترحيل.",
    promptEn: "Review the tax treatment of the current data and identify what requires human verification before approval. Do not post anything.",
  },
] as const;

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
  const [hovered, setHovered] = useState(false);
  const [touchOpen, setTouchOpen] = useState(false);
  const [pinned, setPinned] = useState(false);

  useEffect(() => {
    try {
      setPinned(window.localStorage.getItem(PIN_STORAGE_KEY) === "1");
    } catch {
      setPinned(false);
    }
  }, []);

  useEffect(() => {
    const handleWorkspaceAction = (event: Event) => {
      const detail = (event as CustomEvent<SmartAccountantUiAction>).detail;
      if (detail?.type === "review-entry") onReview();
    };

    window.addEventListener(SMART_ACCOUNTANT_UI_ACTION_EVENT, handleWorkspaceAction);
    return () => window.removeEventListener(SMART_ACCOUNTANT_UI_ACTION_EVENT, handleWorkspaceAction);
  }, [onReview]);

  const selectedJournal = useMemo(
    () => journals.find((journal) => journal.id === selectedJournalId) || null,
    [journals, selectedJournalId],
  );
  const journalTypes = useMemo(
    () => Array.from(new Set(journals.map((journal) => journal.type).filter(Boolean))),
    [journals],
  );
  const selectedType = selectedJournal?.type || journalTypes[0] || "";
  const journalsForType = useMemo(
    () => journals.filter((journal) => !selectedType || journal.type === selectedType),
    [journals, selectedType],
  );
  const expanded = pinned || hovered || touchOpen;

  const setPinnedState = (next: boolean) => {
    setPinned(next);
    setTouchOpen(next);
    try {
      window.localStorage.setItem(PIN_STORAGE_KEY, next ? "1" : "0");
    } catch {
      // The sidebar still works for this session if storage is unavailable.
    }
  };

  const chooseType = (type: string) => {
    const firstJournal = journals.find((journal) => journal.type === type);
    onJournalChange(firstJournal?.id ?? null);
  };

  const emitAfterAssistantMount = (action: Parameters<typeof emitSmartAccountantUiAction>[0]) => {
    onModeChange("assistant");
    window.setTimeout(() => emitSmartAccountantUiAction(action), 0);
  };

  const chooseAssistantPrompt = (prompt: string) => {
    emitAfterAssistantMount({ type: "prompt", prompt });
    if (!pinned) setTouchOpen(false);
  };

  return (
    <>
      <div
        data-smart-accountant-sidebar-pinned={pinned ? "true" : "false"}
        className={`fixed bottom-16 left-0 top-3 z-50 overflow-hidden rounded-e-2xl border-y border-e border-white/10 bg-[#100905]/96 shadow-2xl backdrop-blur-xl transition-[width,box-shadow] duration-200 ${
          expanded ? "w-72" : "w-3 md:w-3"
        }`}
        dir={ar ? "rtl" : "ltr"}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {!expanded ? (
          <button
            type="button"
            onClick={() => setTouchOpen(true)}
            className="flex h-full w-full items-center justify-center bg-white/[0.025] text-amber-300/50 hover:bg-amber-400/[0.08] hover:text-amber-200"
            aria-label={ar ? "فتح أدوات المحاسب" : "Open accountant tools"}
          >
            <span className="h-12 w-0.5 rounded-full bg-current" />
          </button>
        ) : (
          <div className="flex h-full w-72 min-w-72 flex-col text-right">
            <div className="flex shrink-0 items-start gap-2 border-b border-white/10 px-3 py-3">
              <div className="min-w-0 flex-1">
                <div className="text-[11px] font-black text-white">
                  {ar ? "أدوات المحاسب" : "Accountant tools"}
                </div>
                <div className="mt-0.5 truncate text-[8.5px] text-white/35">
                  {companyName || (ar ? "لم يتم اختيار شركة" : "No company selected")}
                  {currency ? ` · ${currency}` : ""}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setPinnedState(!pinned)}
                className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border text-sm transition ${
                  pinned
                    ? "border-amber-400/30 bg-amber-400/15 text-amber-200"
                    : "border-white/10 bg-white/[0.035] text-white/50 hover:text-white"
                }`}
                title={pinned ? (ar ? "إلغاء التثبيت" : "Unpin") : (ar ? "تثبيت العمود" : "Pin sidebar")}
                aria-pressed={pinned}
              >
                📌
              </button>
              <button
                type="button"
                onClick={() => {
                  setTouchOpen(false);
                  if (pinned) setPinnedState(false);
                }}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.035] text-white/45 transition hover:text-white md:hidden"
                aria-label={ar ? "إغلاق" : "Close"}
              >
                ×
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
              <SidebarSection title={ar ? "مساحة العمل" : "Workspace"}>
                <SidebarButton
                  active={mode === "assistant"}
                  icon="✦"
                  label={ar ? "المحاسب الذكي" : "Smart Accountant"}
                  onClick={() => onModeChange("assistant")}
                />
                <SidebarButton
                  active={mode === "sheet"}
                  icon="▦"
                  label={ar ? "الجدول" : "Spreadsheet"}
                  onClick={() => onModeChange("sheet")}
                />
              </SidebarSection>

              <SidebarSection title={ar ? "نوع القيد واليومية" : "Entry type & journal"}>
                {journalsLoading ? (
                  <div className="rounded-xl border border-white/10 bg-white/[0.025] px-3 py-3 text-[10px] text-white/35">
                    {ar ? "جاري تحميل يوميات Odoo..." : "Loading Odoo journals..."}
                  </div>
                ) : (
                  <>
                    <label className="block text-[8.5px] font-semibold text-white/40">
                      {ar ? "نوع القيد" : "Entry type"}
                    </label>
                    <select
                      value={selectedType}
                      onChange={(event) => chooseType(event.target.value)}
                      className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-[10px] font-bold text-white/80 outline-none focus:border-amber-400/35"
                      aria-label={ar ? "اختيار نوع القيد" : "Select entry type"}
                    >
                      {journalTypes.map((type) => (
                        <option key={type} value={type} className="bg-[#170b04] text-white">
                          {journalTypeLabel(type, ar)}
                        </option>
                      ))}
                    </select>

                    <label className="mt-2.5 block text-[8.5px] font-semibold text-white/40">
                      {ar ? "اليومية" : "Journal"}
                    </label>
                    <select
                      value={selectedJournalId || ""}
                      onChange={(event) => onJournalChange(event.target.value ? Number(event.target.value) : null)}
                      className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-[10px] font-semibold text-white/80 outline-none focus:border-amber-400/35"
                      aria-label={ar ? "اختيار اليومية" : "Select journal"}
                    >
                      {journalsForType.map((journal) => (
                        <option key={journal.id} value={journal.id} className="bg-[#170b04] text-white">
                          {journal.name} ({journal.code})
                        </option>
                      ))}
                    </select>
                  </>
                )}
              </SidebarSection>

              <SidebarSection title={ar ? "أوامر المحاسب" : "Accountant actions"}>
                {assistantActions.map((action) => (
                  <SidebarButton
                    key={action.key}
                    icon={action.icon}
                    label={ar ? action.ar : action.en}
                    onClick={() => chooseAssistantPrompt(ar ? action.promptAr : action.promptEn)}
                  />
                ))}
                <SidebarButton
                  icon="⌁"
                  label={ar ? "تحليل مستند" : "Analyze document"}
                  onClick={() => emitAfterAssistantMount({ type: "analyze-document" })}
                />
                <SidebarButton
                  icon="✎"
                  label={ar ? "إدخال يدوي" : "Manual entry"}
                  onClick={onManualEntry}
                />
              </SidebarSection>
            </div>

            <div className="shrink-0 border-t border-white/10 p-3">
              <button
                type="button"
                onClick={onReview}
                className="w-full rounded-xl bg-gradient-to-r from-amber-400 to-yellow-500 px-3 py-2.5 text-[10px] font-black text-black shadow-lg transition hover:brightness-110"
              >
                {ar ? "مراجعة القيد" : "Review entry"}
              </button>
              <p className="mt-2 text-center text-[8px] leading-4 text-white/25">
                {ar ? "المراجعة البشرية مطلوبة قبل الترحيل" : "Human review is required before posting"}
              </p>
            </div>
          </div>
        )}
      </div>

      <style jsx global>{`
        @media (min-width: 768px) {
          .wood-shell > main {
            transition: padding-left 200ms ease;
          }
          .wood-shell:has(> [data-smart-accountant-sidebar-pinned="true"]) > main {
            padding-left: 18rem;
          }
        }
      `}</style>
    </>
  );
}

function SidebarSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-4">
      <div className="mb-1.5 px-1 text-[8px] font-black uppercase tracking-[0.16em] text-white/25">
        {title}
      </div>
      <div className="space-y-1">{children}</div>
    </section>
  );
}

function SidebarButton({
  active = false,
  icon,
  label,
  onClick,
}: {
  active?: boolean;
  icon: string;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-2.5 rounded-xl border px-3 py-2.5 text-start text-[10px] font-bold transition ${
        active
          ? "border-amber-400/25 bg-amber-400/[0.10] text-amber-200"
          : "border-transparent bg-white/[0.02] text-white/62 hover:border-white/10 hover:bg-white/[0.055] hover:text-white"
      }`}
    >
      <span className="flex h-5 w-5 shrink-0 items-center justify-center text-amber-300/85">{icon}</span>
      <span className="min-w-0 flex-1 truncate">{label}</span>
    </button>
  );
}

function journalTypeLabel(type: string, ar: boolean) {
  const labels: Record<string, { ar: string; en: string }> = {
    general: { ar: "قيد عام", en: "General" },
    sale: { ar: "مبيعات", en: "Sales" },
    purchase: { ar: "مشتريات", en: "Purchases" },
    bank: { ar: "بنك", en: "Bank" },
    cash: { ar: "نقدية", en: "Cash" },
  };
  return labels[type]?.[ar ? "ar" : "en"] || type;
}
