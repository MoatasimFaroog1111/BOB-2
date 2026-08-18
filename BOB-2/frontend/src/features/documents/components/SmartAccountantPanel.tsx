"use client";

import React, { useMemo, useRef, useState } from "react";

import type {
  OdooAccount,
  OdooAnalyticAccount,
  OdooJournal,
  OdooPartner,
  PreviewJournalLine,
} from "@/features/documents/model/types";

type ChatMessage = { role: "user" | "assistant"; text: string };

type SmartAccountantPanelProps = Readonly<{
  language: string;
  company: { id: number; name: string; currency: string } | null;
  accounts: OdooAccount[];
  partners: OdooPartner[];
  analyticAccounts: OdooAnalyticAccount[];
  journals: OdooJournal[];
  selectedJournalId: number | null;
  previewLines: PreviewJournalLine[];
  gridData: string[][];
  chatMessages: ChatMessage[];
  chatInput: string;
  setChatInput: (value: string) => void;
  chatLoading: boolean;
  isUploading: boolean;
  chatMessagesEndRef: React.RefObject<HTMLDivElement | null>;
  chatFileInputRef: React.RefObject<HTMLInputElement | null>;
  handleSendChatMessage: (event: React.FormEvent) => void;
  handleChatFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
  onManualEntry: () => void;
  onPrepareEntry: () => void;
}>;

type CandidateLine = {
  accountCode: string;
  description: string;
  debit: number;
  credit: number;
  partnerName: string;
  analyticName: string;
};

const quickActions = [
  {
    icon: "✎",
    ar: "إنشاء قيد",
    en: "Create journal",
    promptAr: "ساعدني في إنشاء قيد محاسبي جديد من البيانات الموجودة، وتحقق من الحسابات والشريك والضريبة قبل أي تنفيذ.",
    promptEn: "Help me create a new journal entry from the available data and validate accounts, partner and tax before any execution.",
  },
  {
    icon: "⌕",
    ar: "بحث في Odoo",
    en: "Search Odoo",
    promptAr: "ابحث في بيانات Odoo الحالية عن الحساب أو الشريك المرتبط بما هو موجود في ورقة العمل واشرح أفضل نتيجة بدون تعديل البيانات.",
    promptEn: "Search current Odoo data for the account or partner related to this worksheet and explain the best result without modifying data.",
  },
  {
    icon: "▣",
    ar: "تحليل حساب",
    en: "Analyze account",
    promptAr: "حلل البيانات المحاسبية الحالية وحدد الحسابات المستخدمة والفروقات أو المخاطر التي تحتاج مراجعة، بدون تنفيذ أي تعديل.",
    promptEn: "Analyze the current accounting data and identify used accounts, variances or risks needing review without making changes.",
  },
  {
    icon: "%",
    ar: "مراجعة ضريبة",
    en: "Review tax",
    promptAr: "راجع المعالجة الضريبية للبيانات الحالية، وحدد ما يحتاج تحققاً بشرياً قبل اعتماد القيد. لا تنفذ أي ترحيل.",
    promptEn: "Review the tax treatment of the current data and identify what requires human verification before approval. Do not post anything.",
  },
] as const;

function parseAmount(value: string | undefined): number {
  if (!value) return 0;
  const normalized = value.replace(/,/g, "").trim();
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : 0;
}

function buildCandidateLines(gridData: string[][]): CandidateLine[] {
  return gridData
    .slice(1)
    .map((row) => ({
      accountCode: String(row?.[0] || "").trim(),
      description: String(row?.[1] || "").trim(),
      debit: parseAmount(row?.[2]),
      credit: parseAmount(row?.[3]),
      partnerName: String(row?.[4] || "").trim(),
      analyticName: String(row?.[5] || "").trim(),
    }))
    .filter((line) =>
      Boolean(
        line.accountCode ||
          line.description ||
          line.debit ||
          line.credit ||
          line.partnerName ||
          line.analyticName,
      ),
    );
}

function formatMoney(value: number, currency: string) {
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${currency}`;
}

export function SmartAccountantPanel({
  language,
  company,
  accounts,
  partners,
  analyticAccounts,
  journals,
  selectedJournalId,
  previewLines,
  gridData,
  chatMessages,
  chatInput,
  setChatInput,
  chatLoading,
  isUploading,
  chatMessagesEndRef,
  chatFileInputRef,
  handleSendChatMessage,
  handleChatFileChange,
  onManualEntry,
  onPrepareEntry,
}: SmartAccountantPanelProps) {
  const ar = language === "ar";
  const inputRef = useRef<HTMLInputElement>(null);
  const [activeView, setActiveView] = useState<"chat" | "context">("chat");

  const selectedJournal = journals.find((journal) => journal.id === selectedJournalId) || null;
  const gridLines = useMemo(() => buildCandidateLines(gridData), [gridData]);
  const effectiveLines = previewLines.length > 0
    ? previewLines.map((line) => ({
        accountCode: line.account_code,
        description: line.name,
        debit: line.debit,
        credit: line.credit,
        partnerName: line.partner_name,
        analyticName: line.analytic_account_name,
      }))
    : gridLines;

  const debitTotal = effectiveLines.reduce((sum, line) => sum + line.debit, 0);
  const creditTotal = effectiveLines.reduce((sum, line) => sum + line.credit, 0);
  const balanced = effectiveLines.length >= 2 && Math.abs(debitTotal - creditTotal) <= 0.01;
  const rowsWithKnownAccounts = effectiveLines.filter((line) =>
    line.accountCode && accounts.some((account) => account.code === line.accountCode),
  ).length;
  const partnerNames = effectiveLines.map((line) => line.partnerName).filter(Boolean);
  const rowsWithKnownPartners = partnerNames.filter((name) =>
    partners.some((partner) => partner.name.trim().toLocaleLowerCase() === name.trim().toLocaleLowerCase()),
  ).length;
  const analyticNames = effectiveLines.map((line) => line.analyticName).filter(Boolean);
  const rowsWithKnownAnalytics = analyticNames.filter((name) =>
    analyticAccounts.some((analytic) => analytic.name.trim().toLocaleLowerCase() === name.trim().toLocaleLowerCase()),
  ).length;

  const verificationChecks = [
    Boolean(company),
    Boolean(selectedJournal),
    effectiveLines.length >= 2,
    balanced,
    effectiveLines.length > 0 && rowsWithKnownAccounts === effectiveLines.filter((line) => line.accountCode).length,
  ];
  const verificationScore = Math.round(
    (verificationChecks.filter(Boolean).length / verificationChecks.length) * 100,
  );

  const chooseQuickAction = (prompt: string) => {
    setChatInput(prompt);
    setActiveView("chat");
    window.requestAnimationFrame(() => inputRef.current?.focus());
  };

  const currency = company?.currency || "SAR";

  return (
    <aside
      className="flex h-full w-[22rem] shrink-0 flex-col overflow-hidden rounded-2xl border border-white/10 bg-black/35 text-right shadow-2xl backdrop-blur-md xl:w-[25rem]"
      dir={ar ? "rtl" : "ltr"}
    >
      <div className="border-b border-white/10 px-4 pb-3 pt-4">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-400 shadow-[0_0_9px_rgba(52,211,153,0.9)]" />
              <h2 className="truncate text-sm font-bold text-white">
                {ar ? "المحاسب الذكي" : "Smart Accountant"}
              </h2>
            </div>
            <p className="mt-1 truncate text-[9.5px] text-white/45">
              {company
                ? `${company.name} · ${company.currency}`
                : ar
                  ? "اختر شركة لربط السياق المحاسبي"
                  : "Select a company for accounting context"}
            </p>
          </div>
          <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2 py-1 text-[8px] font-bold text-emerald-300">
            HUMAN REVIEW
          </span>
        </div>

        <div className="mt-3 grid grid-cols-2 gap-1.5">
          {quickActions.map((action) => (
            <button
              key={action.en}
              type="button"
              onClick={() => chooseQuickAction(ar ? action.promptAr : action.promptEn)}
              disabled={chatLoading || isUploading}
              className="flex min-h-9 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.035] px-2.5 py-2 text-[9.5px] font-semibold text-white/75 transition hover:border-amber-400/30 hover:bg-amber-400/[0.07] hover:text-amber-200 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <span className="text-amber-300">{action.icon}</span>
              <span>{ar ? action.ar : action.en}</span>
            </button>
          ))}
        </div>

        <div className="mt-2 flex gap-1.5">
          <button
            type="button"
            onClick={() => chatFileInputRef.current?.click()}
            disabled={chatLoading || isUploading}
            className="flex-1 rounded-lg border border-amber-400/20 bg-amber-400/[0.07] px-2 py-1.5 text-[9.5px] font-bold text-amber-200 hover:bg-amber-400/10 disabled:opacity-40"
          >
            {ar ? "📎 تحليل مستند" : "📎 Analyze document"}
          </button>
          <button
            type="button"
            onClick={onManualEntry}
            className="flex-1 rounded-lg border border-white/10 bg-white/[0.035] px-2 py-1.5 text-[9.5px] font-bold text-white/70 hover:bg-white/[0.06]"
          >
            {ar ? "✎ إدخال يدوي" : "✎ Manual entry"}
          </button>
        </div>
      </div>

      <div className="flex border-b border-white/10 bg-black/20 px-3 pt-2">
        {(["chat", "context"] as const).map((view) => (
          <button
            key={view}
            type="button"
            onClick={() => setActiveView(view)}
            className={`flex-1 border-b-2 px-2 pb-2 text-[10px] font-bold transition ${
              activeView === view
                ? "border-amber-400 text-amber-300"
                : "border-transparent text-white/45 hover:text-white/70"
            }`}
          >
            {view === "chat"
              ? (ar ? "المحادثة" : "Chat")
              : (ar ? "السياق والأدلة" : "Context & Evidence")}
          </button>
        ))}
      </div>

      {activeView === "chat" ? (
        <>
          <div className="flex-1 overflow-y-auto px-3 py-3">
            <div className="mb-3 rounded-xl border border-white/10 bg-white/[0.025] p-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[9px] font-bold text-white/55">
                  {ar ? "القيد الحالي" : "Current journal"}
                </span>
                <span className={`rounded-full px-2 py-0.5 text-[8px] font-bold ${
                  balanced ? "bg-emerald-400/10 text-emerald-300" : "bg-amber-400/10 text-amber-300"
                }`}>
                  {balanced
                    ? (ar ? "متوازن" : "Balanced")
                    : (ar ? "يحتاج مراجعة" : "Needs review")}
                </span>
              </div>
              <div className="mt-2 grid grid-cols-3 gap-1 text-center">
                <div className="rounded-lg bg-black/25 p-1.5">
                  <div className="text-[8px] text-white/40">{ar ? "السطور" : "Lines"}</div>
                  <div className="mt-0.5 text-[10px] font-bold text-white/80">{effectiveLines.length}</div>
                </div>
                <div className="rounded-lg bg-black/25 p-1.5">
                  <div className="text-[8px] text-white/40">{ar ? "مدين" : "Debit"}</div>
                  <div className="mt-0.5 truncate text-[9px] font-bold text-white/80">{formatMoney(debitTotal, currency)}</div>
                </div>
                <div className="rounded-lg bg-black/25 p-1.5">
                  <div className="text-[8px] text-white/40">{ar ? "دائن" : "Credit"}</div>
                  <div className="mt-0.5 truncate text-[9px] font-bold text-white/80">{formatMoney(creditTotal, currency)}</div>
                </div>
              </div>
            </div>

            <div className="flex flex-col gap-3">
              {chatMessages.map((msg, idx) => (
                <div
                  key={`${msg.role}-${idx}`}
                  className={`max-w-[88%] rounded-2xl border p-3 text-[11px] leading-relaxed shadow-sm ${
                    msg.role === "user"
                      ? "self-end rounded-br-none border-emerald-400/20 bg-emerald-400/10 text-white"
                      : "self-start rounded-bl-none border-white/5 bg-white/[0.07] text-white/90"
                  }`}
                >
                  <div className="whitespace-pre-line">{msg.text}</div>
                </div>
              ))}
              {chatLoading && (
                <div className="max-w-[88%] self-start rounded-2xl rounded-bl-none border border-white/5 bg-white/[0.05] p-3 text-[10px] text-white/60">
                  <span className="animate-pulse">
                    {ar ? "جاري التحليل والتحقق..." : "Analyzing and validating..."}
                  </span>
                </div>
              )}
              <div ref={chatMessagesEndRef} />
            </div>
          </div>

          <div className="border-t border-white/10 p-3">
            <input
              type="file"
              ref={chatFileInputRef}
              onChange={handleChatFileChange}
              accept=".pdf,.png,.jpg,.jpeg,.xlsx,.xls,.csv"
              className="hidden"
            />
            <form
              onSubmit={handleSendChatMessage}
              className="flex gap-2 rounded-xl border border-white/10 bg-black/35 p-1.5 focus-within:border-emerald-400/30"
            >
              <button
                type="button"
                onClick={() => chatFileInputRef.current?.click()}
                disabled={chatLoading || isUploading}
                className="h-8 w-8 shrink-0 rounded-lg border border-amber-400/20 text-sm text-amber-300 hover:bg-amber-400/10 disabled:opacity-40"
                aria-label={ar ? "إرفاق مستند" : "Attach document"}
              >
                📎
              </button>
              <input
                ref={inputRef}
                type="text"
                value={chatInput}
                onChange={(event) => setChatInput(event.target.value)}
                placeholder={ar ? "اسأل، حلل، أو اطلب إجراء محاسبياً..." : "Ask, analyze, or request an accounting action..."}
                disabled={chatLoading || isUploading}
                className="min-w-0 flex-1 bg-transparent px-1 text-[11px] text-white outline-none placeholder:text-white/30"
                dir={ar ? "rtl" : "ltr"}
              />
              <button
                type="submit"
                disabled={chatLoading || isUploading || !chatInput.trim()}
                className="h-8 rounded-lg bg-emerald-600 px-3 text-[10px] font-bold text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {ar ? "أرسل" : "Send"}
              </button>
            </form>
            <p className="mt-1.5 px-1 text-[8.5px] leading-relaxed text-white/35">
              {ar
                ? "الأسئلة التحليلية لا تعدّل البيانات. أوامر التنفيذ تمر عبر مسار الأوامر والمراجعة قبل الترحيل."
                : "Analytical questions do not modify data. Execution requests go through the command and review pipeline before posting."}
            </p>
          </div>
        </>
      ) : (
        <div className="flex-1 overflow-y-auto p-3">
          <section className="rounded-xl border border-white/10 bg-white/[0.025] p-3">
            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="text-[9px] font-bold text-white/50">
                  {ar ? "درجة التحقق" : "Verification score"}
                </div>
                <div className="mt-1 text-2xl font-black text-white">{verificationScore}%</div>
              </div>
              <div className="text-left text-[8px] leading-relaxed text-white/35">
                {ar ? "ليست ثقة نموذج\nبل تحقق من بيانات فعلية" : "Not model confidence\nVerified data checks"}
              </div>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10">
              <div className="h-full rounded-full bg-emerald-400" style={{ width: `${verificationScore}%` }} />
            </div>
          </section>

          <section className="mt-3 rounded-xl border border-white/10 bg-white/[0.025] p-3">
            <h3 className="text-[10px] font-bold text-white/75">{ar ? "السياق المحاسبي" : "Accounting context"}</h3>
            <dl className="mt-2 space-y-2 text-[9.5px]">
              <div className="flex items-center justify-between gap-3">
                <dt className="text-white/40">{ar ? "الشركة" : "Company"}</dt>
                <dd className="max-w-[65%] truncate font-semibold text-white/75">{company?.name || "—"}</dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-white/40">{ar ? "اليومية" : "Journal"}</dt>
                <dd className="max-w-[65%] truncate font-semibold text-white/75">
                  {selectedJournal ? `${selectedJournal.name} (${selectedJournal.code})` : "—"}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-white/40">{ar ? "شجرة الحسابات" : "Accounts"}</dt>
                <dd className="font-semibold text-white/75">{accounts.length.toLocaleString()}</dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-white/40">{ar ? "الشركاء" : "Partners"}</dt>
                <dd className="font-semibold text-white/75">{partners.length.toLocaleString()}</dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-white/40">{ar ? "مراكز التكلفة" : "Analytic accounts"}</dt>
                <dd className="font-semibold text-white/75">{analyticAccounts.length.toLocaleString()}</dd>
              </div>
            </dl>
          </section>

          <section className="mt-3 rounded-xl border border-white/10 bg-white/[0.025] p-3">
            <h3 className="text-[10px] font-bold text-white/75">{ar ? "أدلة التحقق" : "Verification evidence"}</h3>
            <div className="mt-2 space-y-1.5 text-[9px]">
              <EvidenceRow ok={Boolean(company)} text={ar ? "شركة محددة في السياق" : "Company selected in context"} />
              <EvidenceRow ok={Boolean(selectedJournal)} text={ar ? "يومية Odoo محددة" : "Odoo journal selected"} />
              <EvidenceRow ok={effectiveLines.length >= 2} text={ar ? "يوجد سطران محاسبيان على الأقل" : "At least two accounting lines"} />
              <EvidenceRow ok={balanced} text={ar ? "إجمالي المدين يساوي الدائن" : "Debit equals credit"} />
              <EvidenceRow
                ok={effectiveLines.length > 0 && rowsWithKnownAccounts === effectiveLines.filter((line) => line.accountCode).length}
                text={ar ? `${rowsWithKnownAccounts} حساب مطابق لشجرة Odoo` : `${rowsWithKnownAccounts} account codes matched in Odoo`}
              />
              {partnerNames.length > 0 && (
                <EvidenceRow
                  ok={rowsWithKnownPartners === partnerNames.length}
                  text={ar ? `${rowsWithKnownPartners}/${partnerNames.length} شركاء مطابقون` : `${rowsWithKnownPartners}/${partnerNames.length} partners matched`}
                />
              )}
              {analyticNames.length > 0 && (
                <EvidenceRow
                  ok={rowsWithKnownAnalytics === analyticNames.length}
                  text={ar ? `${rowsWithKnownAnalytics}/${analyticNames.length} مراكز تكلفة مطابقة` : `${rowsWithKnownAnalytics}/${analyticNames.length} analytic accounts matched`}
                />
              )}
            </div>
          </section>

          <section className="mt-3 rounded-xl border border-white/10 bg-white/[0.025] p-3">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-[10px] font-bold text-white/75">{ar ? "معاينة القيد" : "Journal preview"}</h3>
              <span className="text-[8px] text-white/35">{effectiveLines.length} {ar ? "سطور" : "lines"}</span>
            </div>
            <div className="mt-2 space-y-1.5">
              {effectiveLines.slice(0, 4).map((line, index) => (
                <div key={`${line.accountCode}-${index}`} className="rounded-lg border border-white/5 bg-black/20 p-2">
                  <div className="flex items-center justify-between gap-2 text-[9px]">
                    <span className="truncate font-bold text-white/75">{line.accountCode || (ar ? "غير محدد" : "Unresolved")}</span>
                    <span className={line.debit > 0 ? "text-emerald-300" : "text-amber-300"}>
                      {formatMoney(line.debit || line.credit, currency)}
                    </span>
                  </div>
                  <div className="mt-1 truncate text-[8.5px] text-white/40">{line.description || line.partnerName || "—"}</div>
                </div>
              ))}
              {effectiveLines.length === 0 && (
                <p className="rounded-lg border border-dashed border-white/10 p-3 text-center text-[9px] text-white/35">
                  {ar ? "أدخل أو ارفع بيانات لعرض المعاينة والأدلة." : "Enter or upload data to show preview and evidence."}
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={onPrepareEntry}
              className="mt-2 w-full rounded-lg bg-gradient-to-r from-amber-500 to-yellow-500 px-3 py-2 text-[9.5px] font-black text-black transition hover:from-amber-400 hover:to-yellow-400"
            >
              {ar ? "مراجعة القيد قبل التسجيل" : "Review entry before registration"}
            </button>
          </section>
        </div>
      )}
    </aside>
  );
}

function EvidenceRow({ ok, text }: { ok: boolean; text: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg bg-black/15 px-2 py-1.5">
      <span className={ok ? "text-emerald-300" : "text-amber-300"}>{ok ? "✓" : "!"}</span>
      <span className={ok ? "text-white/65" : "text-amber-200/75"}>{text}</span>
    </div>
  );
}
