"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { API_BASE_URL } from "@/lib/api";
import { useLanguage } from "@/lib/LanguageContext";

interface Transaction {
  date: string;
  display_date?: string;
  hijri_date?: string;
  description: string;
  main_description?: string;
  details?: string[];
  amount: number;
  debit?: number | null;
  credit?: number | null;
  balance?: number | null;
  row_number: number;
  ai_suggested_account?: string;
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

function fmt(value?: number | null) {
  const n = Number(value || 0);
  return n.toLocaleString("en-SA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function amountColor(value?: number | null) {
  const n = Number(value || 0);
  if (n > 0) return "text-emerald-400";
  if (n < 0) return "text-rose-400";
  return "text-white/50";
}

function BankStatementTable({ rows, isAr }: { rows: Transaction[]; isAr: boolean }) {
  return (
    <div className="overflow-auto rounded-xl border border-white/10 bg-black/20">
      <table className="w-full min-w-[980px] text-[11px] border-collapse">
        <thead className="sticky top-0 z-10 bg-amber-500/15 text-amber-300">
          <tr className="border-b border-amber-500/30">
            <th className="px-3 py-2 text-center w-10">#</th>
            <th className="px-3 py-2 text-center">{isAr ? "التاريخ الميلادي" : "Gregorian Date"}</th>
            <th className="px-3 py-2 text-center">{isAr ? "التاريخ الهجري" : "Hijri Date"}</th>
            <th className="px-3 py-2 text-right min-w-[320px]">{isAr ? "وصف الحركة" : "Description"}</th>
            <th className="px-3 py-2 text-left">{isAr ? "مدين" : "Debit"}</th>
            <th className="px-3 py-2 text-left">{isAr ? "دائن" : "Credit"}</th>
            <th className="px-3 py-2 text-left">{isAr ? "الرصيد" : "Balance"}</th>
            <th className="px-3 py-2 text-right min-w-[340px]">{isAr ? "تفاصيل العملية" : "Details"}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-white/5">
          {rows.map((txn, idx) => (
            <tr key={idx} className="hover:bg-white/5 transition-colors align-top">
              <td className="px-3 py-2 text-center text-white/40 font-mono">{idx + 1}</td>
              <td className="px-3 py-2 text-center font-mono text-white/80">{txn.date || "—"}</td>
              <td className="px-3 py-2 text-center font-mono text-white/60">{txn.hijri_date || "—"}</td>
              <td className="px-3 py-2 text-right">
                <div className="font-bold text-white">{txn.main_description || txn.description || "—"}</div>
                <div className={`mt-1 font-mono ${amountColor(txn.amount)}`}>
                  {txn.amount >= 0 ? "+" : "-"} {fmt(Math.abs(txn.amount))} SAR
                </div>
              </td>
              <td className="px-3 py-2 text-left font-mono tabular-nums text-rose-300">{txn.debit ? fmt(txn.debit) : "0.00"}</td>
              <td className="px-3 py-2 text-left font-mono tabular-nums text-emerald-300">{txn.credit ? fmt(txn.credit) : "0.00"}</td>
              <td className="px-3 py-2 text-left font-mono tabular-nums text-amber-300">{txn.balance !== null && txn.balance !== undefined ? fmt(txn.balance) : "—"}</td>
              <td className="px-3 py-2 text-right text-white/65 leading-relaxed">
                {txn.details && txn.details.length > 0 ? (
                  <details>
                    <summary className="cursor-pointer text-blue-300 font-semibold">{isAr ? "عرض التفاصيل" : "Show details"}</summary>
                    <div className="mt-2 space-y-1">
                      {txn.details.map((d, i) => (
                        <div key={i} className="border-b border-white/5 pb-1">{d}</div>
                      ))}
                    </div>
                  </details>
                ) : (
                  <span className="text-white/30">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SummaryCards({ rows, result, isAr }: { rows: Transaction[]; result: ReconciliationResult; isAr: boolean }) {
  const totalDebit = rows.reduce((sum, t) => sum + Number(t.debit || 0), 0);
  const totalCredit = rows.reduce((sum, t) => sum + Number(t.credit || 0), 0);
  const closing = rows.length ? rows[rows.length - 1].balance : null;
  const opening = rows.length && closing !== null && closing !== undefined ? Number(closing) - rows.reduce((sum, t) => sum + t.amount, 0) : null;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
      <div className="wood-card !p-3 border-blue-500/20">
        <p className="text-[10px] text-white/50">{isAr ? "عدد عمليات الكشف" : "Statement Rows"}</p>
        <p className="text-2xl font-bold text-blue-300 tabular-nums">{rows.length}</p>
      </div>
      <div className="wood-card !p-3 border-emerald-500/20">
        <p className="text-[10px] text-white/50">{isAr ? "إجمالي الدائن / الإيداعات" : "Total Credit"}</p>
        <p className="text-xl font-bold text-emerald-300 tabular-nums">{fmt(totalCredit)}</p>
        <p className="text-[9px] text-white/40">SAR</p>
      </div>
      <div className="wood-card !p-3 border-rose-500/20">
        <p className="text-[10px] text-white/50">{isAr ? "إجمالي المدين / السحوبات" : "Total Debit"}</p>
        <p className="text-xl font-bold text-rose-300 tabular-nums">{fmt(totalDebit)}</p>
        <p className="text-[9px] text-white/40">SAR</p>
      </div>
      <div className="wood-card !p-3 border-amber-500/20">
        <p className="text-[10px] text-white/50">{isAr ? "الرصيد الختامي" : "Closing Balance"}</p>
        <p className="text-xl font-bold text-amber-300 tabular-nums">{closing !== null && closing !== undefined ? fmt(closing) : fmt(result.statement_total)}</p>
        <p className="text-[9px] text-white/40">SAR</p>
      </div>
      {opening !== null && opening !== undefined && (
        <div className="col-span-2 md:col-span-4 rounded-xl border border-white/10 bg-black/20 p-2 text-[11px] text-white/60">
          {isAr ? "الرصيد الافتتاحي المحسوب من الكشف:" : "Calculated opening balance:"}
          <span className="ms-2 font-mono text-amber-300">{fmt(opening)} SAR</span>
        </div>
      )}
    </div>
  );
}

export default function ReconciliationPage() {
  const { language } = useLanguage();
  const isAr = language === "ar";
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ReconciliationResult | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const statementRows = result ? [...result.statement_only, ...result.matched.map(m => m.statement_txn)] : [];

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
    formData.append("statement", file);
    if (dateFrom) formData.append("date_from", dateFrom);
    if (dateTo) formData.append("date_to", dateTo);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/erp/bank-reconciliation`, { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || (isAr ? "فشل تنفيذ التسوية" : "Reconciliation failed"));
      setResult(data);
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  const exportCSV = () => {
    if (!result) return;
    const header = ["#", "Gregorian Date", "Hijri Date", "Description", "Debit", "Credit", "Balance", "Details"];
    const rows = statementRows.map((r, i) => [
      i + 1,
      r.date,
      r.hijri_date || "",
      r.main_description || r.description || "",
      fmt(r.debit || 0),
      fmt(r.credit || 0),
      r.balance !== null && r.balance !== undefined ? fmt(r.balance) : "",
      (r.details || []).join(" | "),
    ]);
    const csv = [header, ...rows].map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "bank_statement_table.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="fade-in p-4 w-full h-full flex flex-col overflow-hidden text-[11px]" dir={isAr ? "rtl" : "ltr"}>
      <div className="mb-2 flex items-center justify-between gap-2 flex-wrap">
        <div>
          <Link href="/erp" className="gold-text text-[10px] tracking-widest hover:underline uppercase transition-all">← ERP</Link>
          <h1 className="mt-0.5 text-xl font-bold">{isAr ? "تقرير المطابقة البنكية" : "Bank Reconciliation Report"}</h1>
          <p className="text-[11px] text-white/50">{isAr ? "قراءة كشف البنك كجدول مطابق لأعمدته ثم مطابقته مع أودو" : "Read the statement as a table, then reconcile with Odoo"}</p>
        </div>
        {result && (
          <div className="flex gap-2">
            <button onClick={exportCSV} className="px-3 py-1.5 bg-emerald-500/15 border border-emerald-500/40 text-emerald-400 rounded-lg text-xs font-semibold">
              📊 {isAr ? "تصدير Excel" : "Export CSV"}
            </button>
            <button onClick={() => window.print()} className="px-3 py-1.5 bg-rose-500/15 border border-rose-500/40 text-rose-400 rounded-lg text-xs font-semibold">
              🖨️ {isAr ? "طباعة / PDF" : "Print / PDF"}
            </button>
          </div>
        )}
      </div>

      <div className="gold-divider mb-3" />

      {!result && (
        <div className="wood-panel !p-4 rounded-[16px] mb-3 space-y-3">
          <h2 className="text-sm font-bold gold-text">{isAr ? "رفع كشف الحساب" : "Upload Bank Statement"}</h2>
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileRef.current?.click()}
            className={`relative border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all ${
              dragging ? "border-amber-400 bg-amber-500/10" : file ? "border-emerald-500/50 bg-emerald-500/5" : "border-white/20 hover:border-white/40 hover:bg-white/5"
            }`}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.tsv,.txt,.xlsx,.xls,.xlsm,.pdf,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,.ofx,.qfx,.qif,.mt940,.sta"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && setFile(e.target.files[0])}
            />
            {file ? (
              <div className="space-y-1">
                <p className="text-2xl">📄</p>
                <p className="font-semibold text-white">{file.name}</p>
                <p className="text-[10px] text-white/50">{(file.size / 1024).toFixed(1)} KB • {isAr ? "جاهز للتشغيل" : "Ready"}</p>
              </div>
            ) : (
              <div className="space-y-1">
                <p className="text-3xl">📂</p>
                <p className="text-white/70 font-medium">{isAr ? "اسحب الملف هنا أو انقر للاختيار" : "Drag file here or click to browse"}</p>
                <p className="text-[10px] text-white/40">Excel · CSV · PDF · Images · OFX/QIF/MT940</p>
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-[10px] font-medium gold-text">{isAr ? "من تاريخ" : "Date From"}</label>
              <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="w-full bg-black/40 border border-white/20 text-white px-2 py-1 text-xs rounded-lg outline-none" />
            </div>
            <div>
              <label className="block text-[10px] font-medium gold-text">{isAr ? "إلى تاريخ" : "Date To"}</label>
              <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="w-full bg-black/40 border border-white/20 text-white px-2 py-1 text-xs rounded-lg outline-none" />
            </div>
          </div>

          {errorMsg && <div className="bg-red-500/10 border border-red-500/30 p-3 rounded-xl text-red-300 text-xs">❌ {errorMsg}</div>}

          <button onClick={handleRun} disabled={!file || loading} className="w-full bg-gradient-to-r from-amber-500 to-yellow-600 disabled:opacity-40 text-black font-bold py-2 rounded-xl text-xs">
            {loading ? (isAr ? "جاري قراءة الكشف..." : "Reading statement...") : (isAr ? "▶ تشغيل التسوية" : "▶ Run Reconciliation")}
          </button>
        </div>
      )}

      {result && (
        <div className="flex-1 min-h-0 flex flex-col gap-3 overflow-hidden">
          <SummaryCards rows={statementRows} result={result} isAr={isAr} />

          <div className="flex justify-between items-center px-1 text-[11px] text-white/40">
            <span>{isAr ? "تم استخراج" : "Extracted"} <span className="gold-text font-bold">{statementRows.length}</span> {isAr ? "عملية من الكشف" : "statement rows"}</span>
            <span className="cursor-pointer hover:text-white/70 transition-colors" onClick={() => { setResult(null); setFile(null); }}>↩ {isAr ? "تسوية جديدة" : "New"}</span>
          </div>

          <div className="flex-1 min-h-0 wood-panel rounded-xl overflow-hidden flex flex-col">
            <div className="p-3 border-b border-white/10">
              <h3 className="text-sm font-bold gold-text">{isAr ? "جدول حركة الحساب البنكي" : "Bank Statement Table"}</h3>
              <p className="text-[10px] text-amber-400/70 mt-0.5">
                {isAr ? "يعرض الكشف بنفس أعمدته: التاريخ، الوصف، مدين، دائن، الرصيد، والتفاصيل" : "Shows the statement columns: dates, description, debit, credit, balance, and details"}
              </p>
            </div>
            <div className="flex-1 overflow-auto p-3">
              <BankStatementTable rows={statementRows} isAr={isAr} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
