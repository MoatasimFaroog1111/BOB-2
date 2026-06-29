"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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

interface BankAccountOption {
  id: number | string;
  code?: string;
  name: string;
  label: string;
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

function uniqueStatementRows(result: ReconciliationResult | null) {
  if (!result) return [] as Transaction[];
  const map = new Map<string, Transaction>();
  const add = (txn?: Transaction) => {
    if (!txn) return;
    const key = `${txn.row_number}-${txn.date}-${txn.amount}-${txn.description}`;
    map.set(key, txn);
  };
  result.statement_only.forEach(add);
  result.matched.forEach(pair => add(pair.statement_txn));
  result.smart_matched.forEach(pair => add(pair.statement_txn));
  return Array.from(map.values()).sort((a, b) => (a.row_number || 0) - (b.row_number || 0));
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
            <tr key={`${txn.row_number}-${idx}`} className="hover:bg-white/5 transition-colors align-top">
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
                      {txn.details.map((detail, i) => (
                        <div key={i} className="border-b border-white/5 pb-1">{detail}</div>
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
  const totalDebit = rows.reduce((sum, txn) => sum + Number(txn.debit || 0), 0);
  const totalCredit = rows.reduce((sum, txn) => sum + Number(txn.credit || 0), 0);
  const closing = rows.length ? rows[rows.length - 1].balance : null;
  const opening = rows.length && closing !== null && closing !== undefined ? Number(closing) - rows.reduce((sum, txn) => sum + txn.amount, 0) : null;

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

function MatchResults({ result, isAr }: { result: ReconciliationResult; isAr: boolean }) {
  const matchedCount = result.matched.length + result.smart_matched.length;
  const isBalanced = Math.abs(result.difference) < 0.01;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <div className="wood-card !p-3 border-emerald-500/30">
          <p className="text-[10px] text-white/50">{isAr ? "متطابق" : "Matched"}</p>
          <p className="text-2xl font-bold text-emerald-300 tabular-nums">{matchedCount}</p>
        </div>
        <div className="wood-card !p-3 border-amber-500/30">
          <p className="text-[10px] text-white/50">{isAr ? "في الكشف فقط" : "Statement Only"}</p>
          <p className="text-2xl font-bold text-amber-300 tabular-nums">{result.statement_only.length}</p>
        </div>
        <div className="wood-card !p-3 border-rose-500/30">
          <p className="text-[10px] text-white/50">{isAr ? "في Google فقط" : "Google Only"}</p>
          <p className="text-2xl font-bold text-rose-300 tabular-nums">{result.ledger_only.length}</p>
        </div>
        <div className={`wood-card !p-3 ${isBalanced ? "border-emerald-500/30" : "border-rose-500/30"}`}>
          <p className="text-[10px] text-white/50">{isAr ? "الفرق" : "Difference"}</p>
          <p className={`text-xl font-bold tabular-nums ${isBalanced ? "text-emerald-300" : "text-rose-300"}`}>{fmt(result.difference)}</p>
          <p className="text-[9px] text-white/40">SAR</p>
        </div>
      </div>

      <div className={`rounded-xl border p-3 ${isBalanced ? "border-emerald-500/30 bg-emerald-500/10" : "border-amber-500/30 bg-amber-500/10"}`}>
        <p className="font-bold text-sm text-white">
          {isBalanced ? (isAr ? "✅ نتيجة المطابقة: لا يوجد فرق" : "✅ Reconciliation result: no difference") : (isAr ? "⚠️ نتيجة المطابقة: يوجد فرق يحتاج مراجعة" : "⚠️ Reconciliation result: review needed")}
        </p>
        <p className="text-[11px] text-white/60 mt-1">
          {isAr ? "تمت مقارنة العمليات المقروءة من الملف مع بيانات الحساب البنكي المختار في Google/النظام، وتم فصل المتطابق وغير المتطابق." : "The uploaded statement rows were compared with the selected bank account records in Google/system."}
        </p>
      </div>

      {(result.matched.length > 0 || result.smart_matched.length > 0) && (
        <div className="rounded-xl border border-emerald-500/20 overflow-hidden bg-black/20">
          <div className="px-3 py-2 bg-emerald-500/10 text-emerald-300 font-bold text-xs">✅ {isAr ? "عمليات متطابقة" : "Matched transactions"}</div>
          <div className="divide-y divide-white/5">
            {result.matched.map((pair, idx) => (
              <div key={`m-${idx}`} className="grid md:grid-cols-2 gap-2 p-3 text-[11px]">
                <div><span className="text-white/40">{isAr ? "الكشف:" : "Statement:"}</span> {pair.statement_txn.date} — {pair.statement_txn.description} — <span className="font-mono text-amber-300">{fmt(pair.statement_txn.amount)}</span></div>
                <div><span className="text-white/40">Google:</span> {pair.ledger_txn.date} — {pair.ledger_txn.description} — <span className="font-mono text-amber-300">{fmt(pair.ledger_txn.amount)}</span></div>
              </div>
            ))}
            {result.smart_matched.map((pair, idx) => (
              <div key={`s-${idx}`} className="grid md:grid-cols-2 gap-2 p-3 text-[11px] bg-purple-500/5">
                <div><span className="text-purple-300">AI</span> {pair.statement_txn.date} — {pair.statement_txn.description} — <span className="font-mono text-amber-300">{fmt(pair.statement_txn.amount)}</span></div>
                <div>{pair.ledger_txn.date} — {pair.ledger_txn.description} — <span className="font-mono text-amber-300">{fmt(pair.ledger_txn.amount)}</span><div className="text-white/40 mt-1">{pair.reason}</div></div>
              </div>
            ))}
          </div>
        </div>
      )}

      {(result.statement_only.length > 0 || result.ledger_only.length > 0) && (
        <div className="grid md:grid-cols-2 gap-3">
          <div className="rounded-xl border border-amber-500/20 overflow-hidden bg-black/20">
            <div className="px-3 py-2 bg-amber-500/10 text-amber-300 font-bold text-xs">📄 {isAr ? "موجودة في الكشف فقط" : "Only in statement"}</div>
            <div className="max-h-72 overflow-auto divide-y divide-white/5">
              {result.statement_only.map((txn, idx) => (
                <div key={idx} className="p-3 text-[11px]"><div className="font-mono text-white/70">{txn.date}</div><div className="text-white">{txn.description}</div><div className="font-mono text-amber-300">{fmt(txn.amount)} SAR</div></div>
              ))}
            </div>
          </div>
          <div className="rounded-xl border border-rose-500/20 overflow-hidden bg-black/20">
            <div className="px-3 py-2 bg-rose-500/10 text-rose-300 font-bold text-xs">🟦 {isAr ? "موجودة في Google فقط" : "Only in Google"}</div>
            <div className="max-h-72 overflow-auto divide-y divide-white/5">
              {result.ledger_only.map((txn, idx) => (
                <div key={idx} className="p-3 text-[11px]"><div className="font-mono text-white/70">{txn.date}</div><div className="text-white">{txn.description}</div><div className="font-mono text-rose-300">{fmt(txn.amount)} SAR</div></div>
              ))}
            </div>
          </div>
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
  const [reading, setReading] = useState(false);
  const [matching, setMatching] = useState(false);
  const [result, setResult] = useState<ReconciliationResult | null>(null);
  const [matchAttempted, setMatchAttempted] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [bankAccounts, setBankAccounts] = useState<BankAccountOption[]>([]);
  const [selectedBankAccountId, setSelectedBankAccountId] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const statementRows = useMemo(() => uniqueStatementRows(result), [result]);

  useEffect(() => {
    let mounted = true;
    async function loadBankAccounts() {
      try {
        const res = await fetch(`${API_BASE_URL}/api/v1/erp/accounts`);
        if (!res.ok) return;
        const data = await res.json();
        const allAccounts = Array.isArray(data) ? data : [];
        const normalized: BankAccountOption[] = allAccounts.map((account: any) => ({
          id: account.id,
          code: account.code || "",
          name: account.name || "",
          label: `${account.code || ""} ${account.name || ""}`.trim(),
        }));
        const bankLike = normalized.filter(account => /bank|بنك|مصرف|riyadh|رياض|cash|نقد|101|102/i.test(`${account.code} ${account.name}`));
        const options = bankLike.length ? bankLike : normalized;
        if (!mounted) return;
        setBankAccounts(options);
        if (options[0] && !selectedBankAccountId) setSelectedBankAccountId(String(options[0].id));
      } catch (err) {
        console.warn("Failed to load bank accounts", err);
      }
    }
    loadBankAccounts();
    return () => { mounted = false; };
  }, [selectedBankAccountId]);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) {
      setFile(dropped);
      setResult(null);
      setMatchAttempted(false);
    }
  };

  const runReconciliationRequest = async (includeBankAccount: boolean) => {
    if (!file) return;
    const formData = new FormData();
    formData.append("statement", file);
    if (dateFrom) formData.append("date_from", dateFrom);
    if (dateTo) formData.append("date_to", dateTo);
    if (includeBankAccount && selectedBankAccountId) {
      formData.append("account_id", selectedBankAccountId);
      formData.append("bank_account_id", selectedBankAccountId);
      formData.append("google_account_id", selectedBankAccountId);
      formData.append("source", "google");
      formData.append("match_mode", "selected_bank_account");
    }
    const res = await fetch(`${API_BASE_URL}/api/v1/erp/bank-reconciliation`, { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || (isAr ? "فشل تنفيذ العملية" : "Operation failed"));
    setResult(data);
  };

  const handleReadFile = async () => {
    setReading(true);
    setErrorMsg("");
    setMatchAttempted(false);
    try {
      await runReconciliationRequest(false);
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setReading(false);
    }
  };

  const handleBankMatch = async () => {
    if (!selectedBankAccountId) {
      setErrorMsg(isAr ? "اختر الحساب البنكي أولاً." : "Select a bank account first.");
      return;
    }
    setMatching(true);
    setErrorMsg("");
    try {
      await runReconciliationRequest(true);
      setMatchAttempted(true);
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setMatching(false);
    }
  };

  const exportCSV = () => {
    if (!result) return;
    const header = ["#", "Gregorian Date", "Hijri Date", "Description", "Debit", "Credit", "Balance", "Details"];
    const rows = statementRows.map((row, i) => [
      i + 1,
      row.date,
      row.hijri_date || "",
      row.main_description || row.description || "",
      fmt(row.debit || 0),
      fmt(row.credit || 0),
      row.balance !== null && row.balance !== undefined ? fmt(row.balance) : "",
      (row.details || []).join(" | "),
    ]);
    const csv = [header, ...rows].map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "bank_statement_reconciliation.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="fade-in p-4 w-full h-full flex flex-col overflow-hidden text-[11px]" dir={isAr ? "rtl" : "ltr"}>
      <div className="mb-2 flex items-center justify-between gap-2 flex-wrap">
        <div>
          <Link href="/erp" className="gold-text text-[10px] tracking-widest hover:underline uppercase transition-all">← ERP</Link>
          <h1 className="mt-0.5 text-xl font-bold">{isAr ? "تقرير المطابقة البنكية" : "Bank Reconciliation Report"}</h1>
          <p className="text-[11px] text-white/50">{isAr ? "اقرأ كشف البنك أولاً، ثم اختر الحساب البنكي واضغط أيقونة التسوية لمطابقة بيانات Google." : "Read the bank statement, then choose the bank account and run Google matching."}</p>
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
          <h2 className="text-sm font-bold gold-text">{isAr ? "رفع وقراءة كشف الحساب" : "Upload and read bank statement"}</h2>
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileRef.current?.click()}
            className={`relative border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all ${dragging ? "border-amber-400 bg-amber-500/10" : file ? "border-emerald-500/50 bg-emerald-500/5" : "border-white/20 hover:border-white/40 hover:bg-white/5"}`}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.tsv,.txt,.xlsx,.xls,.xlsm,.pdf,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,.ofx,.qfx,.qif,.mt940,.sta"
              className="hidden"
              onChange={(e) => {
                if (e.target.files?.[0]) {
                  setFile(e.target.files[0]);
                  setResult(null);
                  setMatchAttempted(false);
                }
              }}
            />
            {file ? (
              <div className="space-y-1">
                <p className="text-2xl">📄</p>
                <p className="font-semibold text-white">{file.name}</p>
                <p className="text-[10px] text-white/50">{(file.size / 1024).toFixed(1)} KB • {isAr ? "جاهز للقراءة" : "Ready to read"}</p>
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

          <button onClick={handleReadFile} disabled={!file || reading} className="w-full bg-gradient-to-r from-blue-500 to-cyan-500 disabled:opacity-40 text-black font-bold py-2 rounded-xl text-xs flex items-center justify-center gap-2">
            {reading ? <><span className="w-4 h-4 border-2 border-black border-t-transparent rounded-full animate-spin" /> {isAr ? "جاري قراءة الملف..." : "Reading file..."}</> : <>📖 {isAr ? "قراءة كشف الحساب" : "Read bank statement"}</>}
          </button>
        </div>
      )}

      {result && (
        <div className="flex-1 min-h-0 flex flex-col gap-3 overflow-hidden">
          <SummaryCards rows={statementRows} result={result} isAr={isAr} />

          <div className="rounded-2xl border border-amber-500/25 bg-gradient-to-r from-amber-500/10 to-yellow-500/5 p-3">
            <div className="flex flex-col md:flex-row gap-3 md:items-end md:justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-2xl">🏦</span>
                  <div>
                    <p className="text-sm font-bold text-amber-300">{isAr ? "أيقونة التسوية البنكية" : "Bank Reconciliation"}</p>
                    <p className="text-[10px] text-white/50">{isAr ? "اختر الحساب البنكي ثم اضغط للمطابقة مع بيانات Google الخاصة بهذا الحساب." : "Choose the bank account, then match against Google records for that account."}</p>
                  </div>
                </div>
                <label className="block text-[10px] text-white/60 mb-1">{isAr ? "الحساب البنكي المختار" : "Selected bank account"}</label>
                <select value={selectedBankAccountId} onChange={(e) => setSelectedBankAccountId(e.target.value)} className="w-full bg-black/60 border border-amber-500/30 text-white px-3 py-2 rounded-xl text-xs outline-none focus:border-amber-400">
                  <option value="">{isAr ? "اختر الحساب البنكي" : "Select bank account"}</option>
                  {bankAccounts.map(account => (
                    <option key={String(account.id)} value={String(account.id)}>{account.label}</option>
                  ))}
                </select>
              </div>
              <button onClick={handleBankMatch} disabled={!file || !selectedBankAccountId || matching} className="md:w-64 bg-gradient-to-r from-amber-500 to-yellow-600 hover:from-amber-600 hover:to-yellow-700 disabled:opacity-40 text-black font-extrabold py-3 rounded-xl text-sm flex items-center justify-center gap-2 shadow-lg shadow-amber-500/10">
                {matching ? <><span className="w-4 h-4 border-2 border-black border-t-transparent rounded-full animate-spin" /> {isAr ? "جاري المطابقة..." : "Matching..."}</> : <>🔁 {isAr ? "مطابقة بنكية" : "Run match"}</>}
              </button>
            </div>
            {errorMsg && <div className="mt-3 bg-red-500/10 border border-red-500/30 p-3 rounded-xl text-red-300 text-xs">❌ {errorMsg}</div>}
          </div>

          <div className="flex justify-between items-center px-1 text-[11px] text-white/40">
            <span>{isAr ? "تم استخراج" : "Extracted"} <span className="gold-text font-bold">{statementRows.length}</span> {isAr ? "عملية من الكشف" : "statement rows"}</span>
            <span className="cursor-pointer hover:text-white/70 transition-colors" onClick={() => { setResult(null); setFile(null); setMatchAttempted(false); }}>↩ {isAr ? "ملف جديد" : "New file"}</span>
          </div>

          <div className="flex-1 min-h-0 wood-panel rounded-xl overflow-hidden flex flex-col">
            <div className="p-3 border-b border-white/10 flex items-center justify-between gap-2 flex-wrap">
              <div>
                <h3 className="text-sm font-bold gold-text">{matchAttempted ? (isAr ? "نتائج التسوية البنكية" : "Bank reconciliation results") : (isAr ? "جدول حركة الحساب البنكي" : "Bank statement table")}</h3>
                <p className="text-[10px] text-amber-400/70 mt-0.5">
                  {matchAttempted ? (isAr ? "النتائج التالية تبين المتطابق والموجود في الكشف فقط والموجود في Google فقط." : "Results show matched rows, statement-only rows, and Google-only rows.") : (isAr ? "بعد التأكد من قراءة الكشف، اختر الحساب البنكي واضغط مطابقة بنكية." : "After checking the parsed statement, choose the account and run matching.")}
                </p>
              </div>
            </div>
            <div className="flex-1 overflow-auto p-3">
              {matchAttempted ? <MatchResults result={result} isAr={isAr} /> : <BankStatementTable rows={statementRows} isAr={isAr} />}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
