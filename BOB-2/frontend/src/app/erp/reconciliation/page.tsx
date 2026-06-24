"use client";

import { useState, useRef } from "react";
import Link from "next/link";
import { API_BASE_URL } from "@/lib/api";
import { useLanguage } from "@/lib/LanguageContext";

interface Transaction {
  date: string;
  description: string;
  amount: number;
  row_number: number;
}

interface MatchedPair {
  statement_txn: Transaction;
  ledger_txn: Transaction;
}

interface SmartMatch {
  statement_txn: Transaction;
  ledger_txn: Transaction;
  confidence: number;
  reason: string;
}

interface ReconciliationResult {
  statement_only: Transaction[];
  ledger_only: Transaction[];
  matched: MatchedPair[];
  smart_matched: SmartMatch[];
  statement_total: number;
  ledger_total: number;
  difference: number;
  statement_count: number;
  ledger_count: number;
}

function fmtAmount(n: number, currency = "SAR") {
  const abs = Math.abs(n).toLocaleString("en-SA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${n < 0 ? "-" : "+"}${abs} ${currency}`;
}

function AmountCell({ amount, currency = "SAR" }: { amount: number; currency?: string }) {
  const abs = Math.abs(amount).toLocaleString("en-SA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return (
    <span className={`font-mono font-semibold tabular-nums ${
      amount > 0 ? "text-green-400" : amount < 0 ? "text-red-400" : "text-white/50"
    }`}>
      {amount < 0 ? "-" : ""}{abs}
    </span>
  );
}

export default function ReconciliationPage() {
  const { t, language } = useLanguage();
  const isAr = language === "ar";

  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [journalId, setJournalId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ReconciliationResult | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [activeSection, setActiveSection] = useState<"matched" | "stmt_only" | "ledger_only" | "smart">("matched");
  const fileRef = useRef<HTMLInputElement>(null);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) setFile(dropped);
  };

  const handleRun = async () => {
    if (!file) return;
    setLoading(true);
    setErrorMsg("");
    setResult(null);

    const formData = new FormData();
    formData.append("statement_file", file);
    if (journalId) formData.append("journal_id", journalId);
    if (dateFrom) formData.append("date_from", dateFrom);
    if (dateTo) formData.append("date_to", dateTo);

    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/erp/reconcile`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || (isAr ? "فشل تنفيذ التسوية" : "Reconciliation failed"));
      setResult(data);
      setActiveSection("matched");
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  const sectionTabs = [
    {
      key: "matched" as const,
      label: isAr ? "متطابق" : "Matched",
      count: result ? result.matched.length : 0,
      color: "text-green-400",
      activeBg: "bg-green-500/15 border-green-500/40",
    },
    {
      key: "smart" as const,
      label: isAr ? "ذكاء اصطناعي" : "AI Matched",
      count: result ? (result.smart_matched?.length || 0) : 0,
      color: "text-purple-400",
      activeBg: "bg-purple-500/15 border-purple-500/40",
    },
    {
      key: "stmt_only" as const,
      label: isAr ? "في الكشف فقط" : "Statement Only",
      count: result ? result.statement_only.length : 0,
      color: "text-amber-400",
      activeBg: "bg-amber-500/15 border-amber-500/40",
    },
    {
      key: "ledger_only" as const,
      label: isAr ? "في أودو فقط" : "Odoo Only",
      count: result ? result.ledger_only.length : 0,
      color: "text-red-400",
      activeBg: "bg-red-500/15 border-red-500/40",
    },
  ];

  return (
    <div className="fade-in p-4 w-full h-full flex flex-col overflow-hidden text-[11px]" dir={isAr ? "rtl" : "ltr"}>

      {/* ── Header ── */}
      <div className="mb-2 flex items-center justify-between">
        <div>
          <Link href="/erp" className="gold-text text-[10px] tracking-widest hover:underline uppercase transition-all">
            {isAr ? "← ERP" : "← ERP"}
          </Link>
          <h1 className="mt-0.5 text-xl font-bold">
            {isAr ? "التسوية البنكية" : "Bank Reconciliation"}
          </h1>
          <p className="text-[11px] text-white/60">
            {isAr ? "قارن كشف الحساب البنكي مع دفاتر أودو واكتشف الفروقات" : "Match your bank statement against Odoo ledger and surface discrepancies"}
          </p>
        </div>

        {result && (
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-xl border backdrop-blur-sm ${
            Math.abs(result.difference) < 0.01
              ? "bg-green-500/10 border-green-500/30"
              : "bg-red-500/10 border-red-500/30"
          }`}>
            <div className={`w-2 h-2 rounded-full ${
              Math.abs(result.difference) < 0.01 ? "bg-green-400" : "bg-red-400 animate-pulse"
            }`} />
            <div>
              <p className="text-[10px] text-white/50">{isAr ? "الفرق" : "Difference"}</p>
              <p className={`font-bold text-sm tabular-nums ${
                Math.abs(result.difference) < 0.01 ? "text-green-400" : "text-red-400"
              }`}>
                {result.difference >= 0 ? "+" : ""}{result.difference.toLocaleString("en-SA", { minimumFractionDigits: 2 })} SAR
              </p>
            </div>
          </div>
        )}
      </div>

      <div className="gold-divider mb-3" />

      {/* ── Upload Panel ── */}
      {!result && (
        <div className="wood-panel !p-4 rounded-[16px] mb-3 space-y-3">
          <h2 className="text-sm font-bold gold-text">{isAr ? "رفع كشف الحساب" : "Upload Bank Statement"}</h2>

          {/* Drop Zone */}
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileRef.current?.click()}
            className={`relative border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all ${
              dragging
                ? "border-amber-400 bg-amber-500/10"
                : file
                ? "border-green-500/50 bg-green-500/5"
                : "border-white/20 hover:border-white/40 hover:bg-white/5"
            }`}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.xlsx,.xls"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && setFile(e.target.files[0])}
            />
            {file ? (
              <div className="space-y-1">
                <p className="text-2xl">📄</p>
                <p className="font-semibold text-white">{file.name}</p>
                <p className="text-[10px] text-white/50">{(file.size / 1024).toFixed(1)} KB • {isAr ? "جاهز للتشغيل" : "Ready to run"}</p>
              </div>
            ) : (
              <div className="space-y-1">
                <p className="text-3xl">📂</p>
                <p className="text-white/70 font-medium">{isAr ? "اسحب الملف هنا أو انقر للاختيار" : "Drag file here or click to browse"}</p>
                <p className="text-[10px] text-white/40">CSV · XLSX · XLS</p>
              </div>
            )}
          </div>

          {/* Filters Row */}
          <div className="grid grid-cols-3 gap-2">
            <div className="space-y-0.5">
              <label className="block text-[10px] font-medium gold-text">{isAr ? "رقم دفتر اليومية" : "Journal ID"}</label>
              <input
                type="text"
                placeholder={isAr ? "اختياري" : "optional"}
                value={journalId}
                onChange={(e) => setJournalId(e.target.value)}
                className="w-full bg-black/40 border border-white/20 text-white px-2 py-1 text-xs rounded-lg outline-none focus:border-yellow-500 transition-colors"
              />
            </div>
            <div className="space-y-0.5">
              <label className="block text-[10px] font-medium gold-text">{isAr ? "من تاريخ" : "Date From"}</label>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="w-full bg-black/40 border border-white/20 text-white px-2 py-1 text-xs rounded-lg outline-none focus:border-yellow-500 transition-colors"
              />
            </div>
            <div className="space-y-0.5">
              <label className="block text-[10px] font-medium gold-text">{isAr ? "إلى تاريخ" : "Date To"}</label>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="w-full bg-black/40 border border-white/20 text-white px-2 py-1 text-xs rounded-lg outline-none focus:border-yellow-500 transition-colors"
              />
            </div>
          </div>

          {errorMsg && (
            <div className="bg-red-500/10 border border-red-500/30 p-3 rounded-xl text-red-300 text-xs">❌ {errorMsg}</div>
          )}

          <button
            onClick={handleRun}
            disabled={!file || loading}
            className="w-full cursor-pointer bg-gradient-to-r from-amber-500 to-yellow-600 hover:from-amber-600 hover:to-yellow-700 disabled:opacity-40 text-black font-bold py-2 rounded-xl text-xs transition-all shadow-lg active:scale-[0.98] flex items-center justify-center gap-2"
          >
            {loading ? (
              <><span className="w-4 h-4 border-2 border-black border-t-transparent rounded-full animate-spin" />{isAr ? "جاري المقارنة..." : "Running reconciliation..."}</>
            ) : (
              isAr ? "▶ تشغيل التسوية" : "▶ Run Reconciliation"
            )}
          </button>
        </div>
      )}

      {/* ── Results ── */}
      {result && (
        <div className="flex-1 min-h-0 flex flex-col gap-3 overflow-hidden">

          {/* KPI Summary Bar */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <div className="wood-card !p-2.5 border-green-500/20">
              <p className="text-[10px] text-white/50">{isAr ? "متطابق" : "Matched"}</p>
              <p className="text-2xl font-bold text-green-400 mt-0.5 tabular-nums">{result.matched.length}</p>
              <p className="text-[9px] text-white/40 mt-0.5">{isAr ? "عملية" : "transactions"}</p>
            </div>
            <div className="wood-card !p-2.5 border-amber-500/20">
              <p className="text-[10px] text-white/50">{isAr ? "في الكشف فقط" : "Statement Only"}</p>
              <p className="text-2xl font-bold text-amber-400 mt-0.5 tabular-nums">{result.statement_only.length}</p>
              <p className="text-[9px] text-white/40 mt-0.5">{isAr ? "غير مطابق" : "unmatched"}</p>
            </div>
            <div className="wood-card !p-2.5 border-red-500/20">
              <p className="text-[10px] text-white/50">{isAr ? "في أودو فقط" : "Odoo Only"}</p>
              <p className="text-2xl font-bold text-red-400 mt-0.5 tabular-nums">{result.ledger_only.length}</p>
              <p className="text-[9px] text-white/40 mt-0.5">{isAr ? "غير مطابق" : "unmatched"}</p>
            </div>
            <div className={`wood-card !p-2.5 ${
              Math.abs(result.difference) < 0.01 ? "border-green-500/30" : "border-red-500/30"
            }`}>
              <p className="text-[10px] text-white/50">{isAr ? "الفرق الإجمالي" : "Net Difference"}</p>
              <p className={`text-xl font-bold mt-0.5 tabular-nums ${
                Math.abs(result.difference) < 0.01 ? "text-green-400" : "text-red-400"
              }`}>
                {result.difference >= 0 ? "+" : ""}{result.difference.toLocaleString("en-SA", { minimumFractionDigits: 2 })}
              </p>
              <p className="text-[9px] text-white/40 mt-0.5">SAR</p>
            </div>
          </div>

          {/* Totals row */}
          <div className="flex flex-wrap gap-2 text-[11px] text-white/60 px-1">
            <span>{isAr ? "إجمالي الكشف:" : "Statement total:"} <span className="gold-text font-semibold tabular-nums">{result.statement_total.toLocaleString("en-SA", { minimumFractionDigits: 2 })} SAR</span></span>
            <span className="text-white/20">|</span>
            <span>{isAr ? "إجمالي أودو:" : "Odoo total:"} <span className="gold-text font-semibold tabular-nums">{result.ledger_total.toLocaleString("en-SA", { minimumFractionDigits: 2 })} SAR</span></span>
            <span className="text-white/20">|</span>
            <span className="text-white/40 text-[10px] cursor-pointer hover:text-white/70 transition-colors" onClick={() => { setResult(null); setFile(null); }}>↩ {isAr ? "تسوية جديدة" : "New reconciliation"}</span>
          </div>

          {/* Section Tabs */}
          <div className="flex flex-wrap gap-1.5 bg-black/30 p-2 rounded-xl border border-white/5">
            {sectionTabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveSection(tab.key)}
                className={`px-3 py-1 rounded-lg text-xs font-semibold border transition-all ${
                  activeSection === tab.key
                    ? tab.activeBg
                    : "border-transparent text-white/50 hover:text-white hover:bg-white/5"
                } ${tab.color}`}
              >
                {tab.label}
                <span className="ml-1.5 bg-black/30 px-1.5 py-0.5 rounded-full text-[10px]">{tab.count}</span>
              </button>
            ))}
          </div>

          {/* Table Area */}
          <div className="flex-1 min-h-0 wood-panel rounded-xl overflow-hidden flex flex-col">

            {/* ── MATCHED ── */}
            {activeSection === "matched" && (
              <>
                <div className="p-3 border-b border-white/10 flex justify-between items-center">
                  <h3 className="text-sm font-bold gold-text">{isAr ? "المعاملات المتطابقة" : "Matched Transactions"}</h3>
                  <span className="text-[10px] text-white/40">{result.matched.length} {isAr ? "زوج" : "pairs"}</span>
                </div>
                <div className="flex-1 overflow-auto">
                  {/* Column headers */}
                  <div className="grid grid-cols-2 gap-0 border-b border-white/10">
                    <div className="bg-black/40 px-4 py-2 flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-blue-400" />
                      <span className="text-[10px] font-semibold text-white/60 uppercase tracking-wider">{isAr ? "كشف الحساب البنكي" : "Bank Statement"}</span>
                    </div>
                    <div className="bg-black/40 px-4 py-2 flex items-center gap-2 border-l border-white/10">
                      <span className="w-2 h-2 rounded-full bg-purple-400" />
                      <span className="text-[10px] font-semibold text-white/60 uppercase tracking-wider">{isAr ? "دفتر أودو" : "Odoo Ledger"}</span>
                    </div>
                  </div>
                  {result.matched.length === 0 ? (
                    <div className="p-10 text-center text-white/30 italic">{isAr ? "لا توجد مطابقات" : "No matches found"}</div>
                  ) : (
                    result.matched.map((pair, idx) => (
                      <div key={idx} className={`grid grid-cols-2 gap-0 border-b border-white/5 hover:bg-white/3 transition-colors ${
                        idx % 2 === 0 ? "" : "bg-white/[0.015]"
                      }`}>
                        {/* Statement side */}
                        <div className="px-4 py-2.5 flex items-center justify-between">
                          <div className="flex flex-col gap-0.5 min-w-0">
                            <p className="text-xs font-medium text-white truncate max-w-[200px]">{pair.statement_txn.description || "—"}</p>
                            <p className="text-[10px] text-white/40 font-mono">{pair.statement_txn.date}</p>
                          </div>
                          <AmountCell amount={pair.statement_txn.amount} />
                        </div>
                        {/* Ledger side */}
                        <div className="px-4 py-2.5 flex items-center justify-between border-l border-white/10">
                          <div className="flex flex-col gap-0.5 min-w-0">
                            <p className="text-xs font-medium text-white truncate max-w-[200px]">{pair.ledger_txn.description || "—"}</p>
                            <p className="text-[10px] text-white/40 font-mono">{pair.ledger_txn.date}</p>
                          </div>
                          <div className="flex items-center gap-2">
                            <AmountCell amount={pair.ledger_txn.amount} />
                            <span className="text-green-400 text-xs">✓</span>
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </>
            )}

            {/* ── AI SMART MATCHES ── */}
            {activeSection === "smart" && (
              <>
                <div className="p-3 border-b border-white/10 flex justify-between items-center">
                  <h3 className="text-sm font-bold gold-text">{isAr ? "مطابقات الذكاء الاصطناعي" : "AI Smart Matches"}</h3>
                  <span className="text-[10px] text-white/40">{result.smart_matched?.length || 0} {isAr ? "مقترح" : "suggestions"}</span>
                </div>
                <div className="flex-1 overflow-auto">
                  <div className="grid grid-cols-2 gap-0 border-b border-white/10">
                    <div className="bg-black/40 px-4 py-2 flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-blue-400" />
                      <span className="text-[10px] font-semibold text-white/60 uppercase tracking-wider">{isAr ? "كشف الحساب" : "Statement"}</span>
                    </div>
                    <div className="bg-black/40 px-4 py-2 flex items-center gap-2 border-l border-white/10">
                      <span className="w-2 h-2 rounded-full bg-purple-400" />
                      <span className="text-[10px] font-semibold text-white/60 uppercase tracking-wider">{isAr ? "أودو + الثقة" : "Odoo + Confidence"}</span>
                    </div>
                  </div>
                  {(!result.smart_matched || result.smart_matched.length === 0) ? (
                    <div className="p-10 text-center text-white/30 italic">{isAr ? "لا توجد مقترحات AI" : "No AI suggestions"}</div>
                  ) : (
                    result.smart_matched.map((sm, idx) => (
                      <div key={idx} className={`grid grid-cols-2 gap-0 border-b border-white/5 hover:bg-white/3 transition-colors ${
                        idx % 2 === 0 ? "" : "bg-white/[0.015]"
                      }`}>
                        <div className="px-4 py-2.5 flex items-center justify-between">
                          <div className="flex flex-col gap-0.5 min-w-0">
                            <p className="text-xs font-medium text-white truncate max-w-[200px]">{sm.statement_txn.description || "—"}</p>
                            <p className="text-[10px] text-white/40 font-mono">{sm.statement_txn.date}</p>
                          </div>
                          <AmountCell amount={sm.statement_txn.amount} />
                        </div>
                        <div className="px-4 py-2.5 flex items-center justify-between border-l border-white/10">
                          <div className="flex flex-col gap-0.5 min-w-0">
                            <p className="text-xs font-medium text-white truncate max-w-[160px]">{sm.ledger_txn.description || "—"}</p>
                            <p className="text-[10px] text-purple-400/70 italic truncate max-w-[160px]" title={sm.reason}>{sm.reason}</p>
                          </div>
                          <div className="flex items-center gap-1.5 shrink-0">
                            <AmountCell amount={sm.ledger_txn.amount} />
                            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full border ${
                              sm.confidence >= 0.8
                                ? "text-green-400 border-green-500/30 bg-green-500/10"
                                : sm.confidence >= 0.6
                                ? "text-amber-400 border-amber-500/30 bg-amber-500/10"
                                : "text-white/50 border-white/20 bg-white/5"
                            }`}>
                              {Math.round(sm.confidence * 100)}%
                            </span>
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </>
            )}

            {/* ── STATEMENT ONLY ── */}
            {activeSection === "stmt_only" && (
              <>
                <div className="p-3 border-b border-white/10 flex justify-between items-center">
                  <div>
                    <h3 className="text-sm font-bold gold-text">{isAr ? "في الكشف البنكي فقط" : "Statement Only"}</h3>
                    <p className="text-[10px] text-amber-400/70 mt-0.5">{isAr ? "هذه العمليات موجودة في البنك لكن غير مسجلة في أودو" : "Present in bank but not recorded in Odoo"}</p>
                  </div>
                  <span className="text-amber-400 font-bold text-sm">{result.statement_only.length}</span>
                </div>
                <div className="flex-1 overflow-auto">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="bg-black/30 text-white/40 uppercase tracking-wider text-[10px] border-b border-white/10">
                        <th className="px-4 py-2 font-semibold">{isAr ? "التاريخ" : "Date"}</th>
                        <th className="px-4 py-2 font-semibold">{isAr ? "الوصف" : "Description"}</th>
                        <th className="px-4 py-2 font-semibold text-right">{isAr ? "المبلغ" : "Amount"}</th>
                        <th className="px-4 py-2 font-semibold text-center">{isAr ? "الحالة" : "Status"}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                      {result.statement_only.length === 0 ? (
                        <tr><td colSpan={4} className="p-8 text-center text-white/30 italic">{isAr ? "لا توجد فروقات" : "No discrepancies"}</td></tr>
                      ) : (
                        result.statement_only.map((txn, idx) => (
                          <tr key={idx} className="hover:bg-white/5 transition-colors">
                            <td className="px-4 py-2.5 font-mono text-[11px] text-white/60">{txn.date}</td>
                            <td className="px-4 py-2.5 text-xs text-white max-w-[280px]">
                              <p className="truncate">{txn.description || "—"}</p>
                            </td>
                            <td className="px-4 py-2.5 text-right"><AmountCell amount={txn.amount} /></td>
                            <td className="px-4 py-2.5 text-center">
                              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full border bg-amber-500/10 text-amber-300 border-amber-500/30">
                                {isAr ? "غير مسجل" : "Unrecorded"}
                              </span>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {/* ── LEDGER ONLY ── */}
            {activeSection === "ledger_only" && (
              <>
                <div className="p-3 border-b border-white/10 flex justify-between items-center">
                  <div>
                    <h3 className="text-sm font-bold gold-text">{isAr ? "في أودو فقط" : "Odoo Ledger Only"}</h3>
                    <p className="text-[10px] text-red-400/70 mt-0.5">{isAr ? "هذه العمليات مسجلة في أودو لكن لا تظهر في الكشف البنكي" : "Recorded in Odoo but absent from the bank statement"}</p>
                  </div>
                  <span className="text-red-400 font-bold text-sm">{result.ledger_only.length}</span>
                </div>
                <div className="flex-1 overflow-auto">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="bg-black/30 text-white/40 uppercase tracking-wider text-[10px] border-b border-white/10">
                        <th className="px-4 py-2 font-semibold">{isAr ? "التاريخ" : "Date"}</th>
                        <th className="px-4 py-2 font-semibold">{isAr ? "الوصف" : "Description"}</th>
                        <th className="px-4 py-2 font-semibold text-right">{isAr ? "المبلغ" : "Amount"}</th>
                        <th className="px-4 py-2 font-semibold text-center">{isAr ? "الحالة" : "Status"}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                      {result.ledger_only.length === 0 ? (
                        <tr><td colSpan={4} className="p-8 text-center text-white/30 italic">{isAr ? "لا توجد فروقات" : "No discrepancies"}</td></tr>
                      ) : (
                        result.ledger_only.map((txn, idx) => (
                          <tr key={idx} className="hover:bg-white/5 transition-colors">
                            <td className="px-4 py-2.5 font-mono text-[11px] text-white/60">{txn.date}</td>
                            <td className="px-4 py-2.5 text-xs text-white max-w-[280px]">
                              <p className="truncate">{txn.description || "—"}</p>
                            </td>
                            <td className="px-4 py-2.5 text-right"><AmountCell amount={txn.amount} /></td>
                            <td className="px-4 py-2.5 text-center">
                              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full border bg-red-500/10 text-red-300 border-red-500/30">
                                {isAr ? "في أودو فقط" : "Odoo Only"}
                              </span>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </>
            )}

          </div>
        </div>
      )}
    </div>
  );
}
