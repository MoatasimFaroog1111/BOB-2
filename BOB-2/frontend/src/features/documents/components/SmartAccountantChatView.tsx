"use client";

import React from "react";

import { formatAccountingMoney } from "@/features/documents/model/smartAccountantWorkspace";

type ChatMessage = { role: "user" | "assistant"; text: string };

export function SmartAccountantChatView({
  language,
  currency,
  lineCount,
  debitTotal,
  creditTotal,
  balanced,
  chatMessages,
  chatInput,
  setChatInput,
  chatLoading,
  isUploading,
  chatMessagesEndRef,
  chatFileInputRef,
  handleSendChatMessage,
  handleChatFileChange,
  inputRef,
}: Readonly<{
  language: string;
  currency: string;
  lineCount: number;
  debitTotal: number;
  creditTotal: number;
  balanced: boolean;
  chatMessages: ChatMessage[];
  chatInput: string;
  setChatInput: (value: string) => void;
  chatLoading: boolean;
  isUploading: boolean;
  chatMessagesEndRef: React.RefObject<HTMLDivElement | null>;
  chatFileInputRef: React.RefObject<HTMLInputElement | null>;
  handleSendChatMessage: (event: React.FormEvent) => void;
  handleChatFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
  inputRef: React.RefObject<HTMLInputElement | null>;
}>) {
  const ar = language === "ar";

  return (
    <>
      <div className="flex-1 overflow-y-auto px-3 py-3">
        <div className="mb-3 rounded-xl border border-white/10 bg-white/[0.025] p-2.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[9px] font-bold text-white/55">
              {ar ? "القيد الحالي" : "Current journal"}
            </span>
            <span
              className={`rounded-full px-2 py-0.5 text-[8px] font-bold ${
                balanced ? "bg-emerald-400/10 text-emerald-300" : "bg-amber-400/10 text-amber-300"
              }`}
            >
              {balanced
                ? (ar ? "متوازن" : "Balanced")
                : (ar ? "يحتاج مراجعة" : "Needs review")}
            </span>
          </div>
          <div className="mt-2 grid grid-cols-3 gap-1 text-center">
            <SummaryCell label={ar ? "السطور" : "Lines"} value={String(lineCount)} />
            <SummaryCell label={ar ? "مدين" : "Debit"} value={formatAccountingMoney(debitTotal, currency)} />
            <SummaryCell label={ar ? "دائن" : "Credit"} value={formatAccountingMoney(creditTotal, currency)} />
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
              <div className="whitespace-pre-line">
                {idx === 0 && msg.role === "assistant"
                  ? (ar
                      ? "مرحباً! أنا المحاسب الذكي. أستطيع تحليل البيانات والمستندات، البحث في Odoo، تجهيز القيود، ومراجعة المعالجة قبل أي ترحيل."
                      : "Hello! I am your Smart Accountant. I can analyze data and documents, search Odoo, prepare journal entries, and review treatment before any posting.")
                  : msg.text}
              </div>
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
  );
}

function SummaryCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-black/25 p-1.5">
      <div className="text-[8px] text-white/40">{label}</div>
      <div className="mt-0.5 truncate text-[9px] font-bold text-white/80">{value}</div>
    </div>
  );
}
