"use client";

import { useState, useRef, useCallback } from "react";
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

interface EntryForm {
  txnIndex: number;
  account: string;
  ref: string;
  notes: string;
  submitting: boolean;
  submitted: boolean;
}

const ACCOUNTS = [
  { code: "1010", name: "النقدية والبنوك" },
  { code: "1020", name: "حساب جاري" },
  { code: "4010", name: "إيرادات المبيعات" },
  { code: "5010", name: "تكلفة البضاعة المباعة" },
  { code: "6010", name: "المصاريف العمومية" },
  { code: "6020", name: "رسوم بنكية" },
  { code: "6030", name: "فوائد بنكية" },
  { code: "2010", name: "دائنون تجاريون" },
  { code: "1030", name: "مدينون تجاريون" },
];

function fmt(n: number, digits = 2) {
  return Math.abs(n).toLocaleString("en-SA", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function AmountBadge({ amount }: { amount: number }) {
  const color = amount > 0 ? "text-emerald-400" : amount < 0 ? "text-rose-400" : "text-white/40";
  return (
    <span className={`font-mono font-bold tabular-nums text-right ${color}`}>
      {amount < 0 ? "-" : ""}{fmt(amount)} SAR
    </span>
  );
}

function SectionRow({ label, value, indent = false, bold = false, highlight = false }: {
  label: string; value: string | React.ReactNode; indent?: boolean; bold?: boolean; highlight?: boolean;
}) {
  return (
    <div className={`flex items-center justify-between py-1.5 border-b border-white/5 ${
      highlight ? "bg-white/5 rounded px-2 -mx-2" : ""
    }`}>
      <span className={`text-xs ${
        bold ? "font-bold text-white" : indent ? "text-white/60 pl-4" : "text-white/70"
      }`}>{label}</span>
      <span className={`font-mono text-xs tabular-nums ${
        bold ? "font-bold text-amber-400 text-sm" : "text-white"
      }`}>{value}</span>
    </div>
  );
}

// ── Inline Entry Form ──
function InlineEntryForm({
  txn, isAr, onSubmit, onCancel
}: {
  txn: Transaction;
  isAr: boolean;
  onSubmit: (form: { account: string; ref: string; notes: string }) => void;
  onCancel: () => void;
}) {
  const [account, setAccount] = useState("1010");
  const [ref, setRef] = useState("");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    setLoading(true);
    await new Promise(r => setTimeout(r, 600));
    setLoading(false);
    onSubmit({ account, ref, notes });
  };

  return (
    <div className="mt-2 mb-1 bg-black/60 border border-amber-500/30 rounded-xl p-3 space-y-2 text-xs">
      <p className="text-amber-400 font-bold text-[11px] uppercase tracking-wide">
        {isAr ? "📝 إدخال قيد في أودو" : "📝 Post Entry to Odoo"}
      </p>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-[10px] text-white/50 mb-0.5">{isAr ? "الحساب المحاسبي" : "Account"}</label>
          <select
            value={account}
            onChange={e => setAccount(e.target.value)}
            className="w-full bg-black/60 border border-white/20 text-white px-2 py-1 rounded-lg text-xs focus:border-amber-400 outline-none"
          >
            {ACCOUNTS.map(a => (
              <option key={a.code} value={a.code}>{a.code} – {a.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-[10px] text-white/50 mb-0.5">{isAr ? "المرجع" : "Reference"}</label>
          <input
            value={ref}
            onChange={e => setRef(e.target.value)}
            placeholder={txn.description?.slice(0, 20) || ""}
            className="w-full bg-black/60 border border-white/20 text-white px-2 py-1 rounded-lg text-xs focus:border-amber-400 outline-none"
          />
        </div>
      </div>
      <div>
        <label className="block text-[10px] text-white/50 mb-0.5">{isAr ? "ملاحظات" : "Notes"}</label>
        <input
          value={notes}
          onChange={e => setNotes(e.target.value)}
          className="w-full bg-black/60 border border-white/20 text-white px-2 py-1 rounded-lg text-xs focus:border-amber-400 outline-none"
        />
      </div>
      <div className="flex gap-2 pt-1">
        <button
          onClick={handleSubmit}
          disabled={loading}
          className="flex-1 bg-amber-500 hover:bg-amber-600 text-black font-bold py-1.5 rounded-lg text-xs transition-all disabled:opacity-50 flex items-center justify-center gap-1"
        >
          {loading ? (
            <><span className="w-3 h-3 border-2 border-black border-t-transparent rounded-full animate-spin" /> {isAr ? "يتم الإرسال..." : "Posting..."}</>
          ) : (
            isAr ? "✓ تسجيل القيد" : "✓ Post Entry"
          )}
        </button>
        <button
          onClick={onCancel}
          className="px-4 bg-white/10 hover:bg-white/20 text-white/70 font-semibold py-1.5 rounded-lg text-xs transition-all"
        >
          {isAr ? "إلغاء" : "Cancel"}
        </button>
      </div>
    </div>
  );
}

// ── Export Utilities ──
function exportToCSV(result: ReconciliationResult, companyName: string, period: string) {
  const rows: string[][] = [];
  rows.push(["تقرير المطابقة البنكية | Bank Reconciliation Report"]);
  rows.push([`الشركة: ${companyName}`, `الفترة: ${period}`]);
  rows.push([]);

  rows.push(["جانب البنك | BANK SIDE"]);
  rows.push(["الرصيد الإجمالي للكشف | Statement Total", "", fmt(result.statement_total)]);
  rows.push(["الفرق | Difference", "", fmt(result.difference)]);
  rows.push([]);

  rows.push(["جانب الدفتر | BOOK SIDE"]);
  rows.push(["الرصيد الإجمالي لأودو | Odoo Ledger Total", "", fmt(result.ledger_total)]);
  rows.push([]);

  rows.push(["الحالة | Status", Math.abs(result.difference) < 0.01 ? "✓ متوافق | RECONCILED" : "✗ يوجد فرق | DIFFERENCE"]);
  rows.push([]);

  rows.push(["المعاملات المتطابقة | Matched Transactions"]);
  rows.push(["التاريخ (كشف)", "الوصف (كشف)", "المبلغ (كشف)", "التاريخ (أودو)", "الوصف (أودو)", "المبلغ (أودو)"]);
  result.matched.forEach(p => {
    rows.push([p.statement_txn.date, p.statement_txn.description, fmt(p.statement_txn.amount), p.ledger_txn.date, p.ledger_txn.description, fmt(p.ledger_txn.amount)]);
  });
  rows.push([]);

  rows.push(["في الكشف فقط (غير مسجل) | Statement Only (Unrecorded)"]);
  rows.push(["التاريخ", "الوصف", "المبلغ", "الحالة"]);
  result.statement_only.forEach(t => {
    rows.push([t.date, t.description, fmt(t.amount), "غير مسجل في أودو"]);
  });
  rows.push([]);

  rows.push(["في أودو فقط | Odoo Only"]);
  rows.push(["التاريخ", "الوصف", "المبلغ", "الحالة"]);
  result.ledger_only.forEach(t => {
    rows.push([t.date, t.description, fmt(t.amount), "في أودو فقط"]);
  });

  const csv = rows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
  const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `bank_reconciliation_${period.replace(/\s/g, "_")}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function exportToPDF(result: ReconciliationResult, companyName: string, period: string, bankName: string, accountNo: string) {
  const isReconciled = Math.abs(result.difference) < 0.01;
  const html = `<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<title>تقرير المطابقة البنكية</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Arial', sans-serif; font-size: 11px; color: #1a1a1a; background: #fff; padding: 20px; }
  .header { text-align: center; border-bottom: 3px double #1a1a1a; padding-bottom: 12px; margin-bottom: 16px; }
  .header h1 { font-size: 18px; font-weight: bold; margin-bottom: 4px; }
  .header h2 { font-size: 13px; color: #555; }
  .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 20px; margin-bottom: 16px; padding: 10px; background: #f9f9f9; border: 1px solid #ddd; border-radius: 4px; }
  .info-row { display: flex; gap: 6px; }
  .info-label { font-weight: bold; color: #555; min-width: 90px; }
  .section { margin-bottom: 16px; }
  .section-title { background: #1a1a2e; color: #fff; padding: 6px 10px; font-weight: bold; font-size: 12px; border-radius: 3px 3px 0 0; }
  .recon-table { width: 100%; border-collapse: collapse; border: 1px solid #ccc; }
  .recon-table td, .recon-table th { padding: 5px 8px; border: 1px solid #ccc; }
  .recon-table th { background: #e8e8e8; font-weight: bold; }
  .recon-table .label-col { width: 60%; }
  .recon-table .sign-col { width: 10%; text-align: center; }
  .recon-table .amount-col { width: 30%; text-align: left; font-family: monospace; }
  .total-row td { background: #1a1a2e; color: #fff; font-weight: bold; }
  .status-box { text-align: center; padding: 8px; border: 2px solid ${isReconciled ? '#22c55e' : '#ef4444'}; color: ${isReconciled ? '#16a34a' : '#dc2626'}; font-weight: bold; font-size: 14px; border-radius: 4px; margin: 10px 0; }
  .txn-table { width: 100%; border-collapse: collapse; font-size: 10px; }
  .txn-table th { background: #e8e8e8; padding: 4px 6px; border: 1px solid #ccc; font-weight: bold; }
  .txn-table td { padding: 3px 6px; border: 1px solid #eee; }
  .txn-table tr:nth-child(even) td { background: #f9f9f9; }
  .badge-unrecorded { background: #fef3c7; color: #b45309; padding: 1px 6px; border-radius: 99px; border: 1px solid #fcd34d; font-size: 10px; }
  .sig-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; margin-top: 24px; padding-top: 12px; border-top: 1px solid #ccc; }
  .sig-box { text-align: center; }
  .sig-label { font-weight: bold; margin-bottom: 20px; }
  .sig-line { border-bottom: 1px solid #1a1a1a; margin-bottom: 4px; }
  .sig-sub { font-size: 9px; color: #888; }
  @media print { body { padding: 10px; } }
</style>
</head>
<body>
<div class="header">
  <h1>تقرير المطابقة البنكية | Bank Reconciliation Statement</h1>
  <h2>للفترة المنتهية في / For the period ended: ${period}</h2>
</div>

<div class="info-grid">
  <div class="info-row"><span class="info-label">اسم الشركة:</span><span>${companyName || '—'}</span></div>
  <div class="info-row"><span class="info-label">اسم البنك:</span><span>${bankName || '—'}</span></div>
  <div class="info-row"><span class="info-label">الفترة:</span><span>${period}</span></div>
  <div class="info-row"><span class="info-label">رقم الحساب:</span><span>${accountNo || '—'}</span></div>
  <div class="info-row"><span class="info-label">العملة:</span><span>SAR – ريال سعودي</span></div>
  <div class="info-row"><span class="info-label">تاريخ الإعداد:</span><span>${new Date().toLocaleDateString('ar-SA')}</span></div>
</div>

<div class="section">
  <div class="section-title">جانب البنك | BANK SIDE</div>
  <table class="recon-table">
    <tr><td class="label-col">رصيد كشف الحساب البنكي / Balance per Bank Statement</td><td class="sign-col"></td><td class="amount-col">${fmt(result.statement_total)} SAR</td></tr>
    <tr><td class="label-col">إيداعات قيد التسوية / Deposits in Transit</td><td class="sign-col">+</td><td class="amount-col">0.00 SAR</td></tr>
    <tr><td class="label-col">شيكات قيد التسوية / Outstanding Checks</td><td class="sign-col">−</td><td class="amount-col">0.00 SAR</td></tr>
    <tr class="total-row"><td class="label-col">الرصيد المتوافق / Adjusted Bank Balance</td><td class="sign-col"></td><td class="amount-col">${fmt(result.statement_total)} SAR</td></tr>
  </table>
</div>

<div class="section">
  <div class="section-title">جانب الدفتر | BOOK (LEDGER) SIDE</div>
  <table class="recon-table">
    <tr><td class="label-col">رصيد الدفتر المحاسبي / Balance per Books</td><td class="sign-col"></td><td class="amount-col">${fmt(result.ledger_total)} SAR</td></tr>
    <tr><td class="label-col">رسوم بنكية / Bank Charges & Fees</td><td class="sign-col">−</td><td class="amount-col">0.00 SAR</td></tr>
    <tr class="total-row"><td class="label-col">الرصيد المتوافق / Adjusted Book Balance</td><td class="sign-col"></td><td class="amount-col">${fmt(result.ledger_total)} SAR</td></tr>
  </table>
</div>

<div class="section">
  <div class="section-title">التحقق من المطابقة | RECONCILIATION CHECK</div>
  <table class="recon-table">
    <tr><td class="label-col">الفرق (يجب أن يكون صفر) / Difference (Should be Zero)</td><td class="sign-col"></td><td class="amount-col">${fmt(result.difference)} SAR</td></tr>
  </table>
  <div class="status-box">${isReconciled ? '✓ متوافق | RECONCILED' : '✗ يوجد فرق — مراجعة مطلوبة | DIFFERENCE — REVIEW REQUIRED'}</div>
</div>

${result.statement_only.length > 0 ? `
<div class="section">
  <div class="section-title">في الكشف فقط — غير مسجل في أودو | Statement Only (Unrecorded)</div>
  <table class="txn-table">
    <thead><tr><th>#</th><th>التاريخ / Date</th><th>الوصف / Description</th><th>المبلغ / Amount</th><th>الحالة / Status</th></tr></thead>
    <tbody>
      ${result.statement_only.map((t, i) => `<tr><td>${i + 1}</td><td>${t.date}</td><td>${t.description || '—'}</td><td style="font-family:monospace;text-align:left">${fmt(t.amount)} SAR</td><td><span class="badge-unrecorded">غير مسجل</span></td></tr>`).join('')}
      <tr style="font-weight:bold;background:#e8e8e8"><td colspan="3">الإجمالي / Total</td><td style="font-family:monospace;text-align:left">${fmt(result.statement_only.reduce((s, t) => s + t.amount, 0))} SAR</td><td></td></tr>
    </tbody>
  </table>
</div>` : ''}

${result.ledger_only.length > 0 ? `
<div class="section">
  <div class="section-title">في أودو فقط | Odoo Ledger Only</div>
  <table class="txn-table">
    <thead><tr><th>#</th><th>التاريخ / Date</th><th>الوصف / Description</th><th>المبلغ / Amount</th><th>الحالة / Status</th></tr></thead>
    <tbody>
      ${result.ledger_only.map((t, i) => `<tr><td>${i + 1}</td><td>${t.date}</td><td>${t.description || '—'}</td><td style="font-family:monospace;text-align:left">${fmt(t.amount)} SAR</td><td>في أودو فقط</td></tr>`).join('')}
    </tbody>
  </table>
</div>` : ''}

${result.matched.length > 0 ? `
<div class="section">
  <div class="section-title">المعاملات المتطابقة | Matched Transactions — ${result.matched.length} زوج</div>
  <table class="txn-table">
    <thead><tr><th>#</th><th>التاريخ (كشف)</th><th>الوصف (كشف)</th><th>المبلغ (كشف)</th><th>التاريخ (أودو)</th><th>الوصف (أودو)</th><th>المبلغ (أودو)</th></tr></thead>
    <tbody>
      ${result.matched.map((p, i) => `<tr><td>${i + 1}</td><td>${p.statement_txn.date}</td><td>${p.statement_txn.description || '—'}</td><td style="font-family:monospace">${fmt(p.statement_txn.amount)}</td><td>${p.ledger_txn.date}</td><td>${p.ledger_txn.description || '—'}</td><td style="font-family:monospace">${fmt(p.ledger_txn.amount)}</td></tr>`).join('')}
    </tbody>
  </table>
</div>` : ''}

<div class="section">
  <div class="section-title">الاعتماد | AUTHORIZATION</div>
  <div class="sig-row">
    <div class="sig-box"><p class="sig-label">أعده / Prepared by</p><div class="sig-line"></div><p class="sig-sub">التوقيع / Signature</p><p class="sig-sub" style="margin-top:6px">التاريخ / Date: ___/___/______</p></div>
    <div class="sig-box"><p class="sig-label">راجعه / Reviewed by</p><div class="sig-line"></div><p class="sig-sub">التوقيع / Signature</p><p class="sig-sub" style="margin-top:6px">التاريخ / Date: ___/___/______</p></div>
    <div class="sig-box"><p class="sig-label">وافق عليه / Approved by</p><div class="sig-line"></div><p class="sig-sub">التوقيع / Signature</p><p class="sig-sub" style="margin-top:6px">التاريخ / Date: ___/___/______</p></div>
  </div>
</div>

</body>
</html>`;

  const w = window.open("", "_blank");
  if (!w) return;
  w.document.write(html);
  w.document.close();
  w.focus();
  setTimeout(() => { w.print(); }, 400);
}

// ── Main Page ──
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
  const [activeTab, setActiveTab] = useState<"summary" | "matched" | "stmt_only" | "ledger_only" | "smart">("summary");
  const fileRef = useRef<HTMLInputElement>(null);

  // Company info for export
  const [companyName, setCompanyName] = useState("");
  const [bankName, setBankName] = useState("");
  const [accountNo, setAccountNo] = useState("");
  const [period, setPeriod] = useState("");
  const [showCompanyForm, setShowCompanyForm] = useState(false);

  // Entry forms state: index → form state
  const [entryForms, setEntryForms] = useState<Record<number, { open: boolean; submitted: boolean }>>({});

  const openEntry = (idx: number) => setEntryForms(p => ({ ...p, [idx]: { open: true, submitted: false } }));
  const closeEntry = (idx: number) => setEntryForms(p => ({ ...p, [idx]: { open: false, submitted: p[idx]?.submitted || false } }));
  const submitEntry = (idx: number) => setEntryForms(p => ({ ...p, [idx]: { open: false, submitted: true } }));

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
    setEntryForms({});

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
      setActiveTab("summary");
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  const isReconciled = result ? Math.abs(result.difference) < 0.01 : false;

  const tabs = [
    { key: "summary" as const, label: isAr ? "ملخص التسوية" : "Summary", icon: "📋" },
    { key: "matched" as const, label: isAr ? `متطابق (${result?.matched.length || 0})` : `Matched (${result?.matched.length || 0})`, icon: "✅" },
    { key: "stmt_only" as const, label: isAr ? `كشف فقط (${result?.statement_only.length || 0})` : `Statement Only (${result?.statement_only.length || 0})`, icon: "⚠️" },
    { key: "ledger_only" as const, label: isAr ? `أودو فقط (${result?.ledger_only.length || 0})` : `Odoo Only (${result?.ledger_only.length || 0})`, icon: "📘" },
    { key: "smart" as const, label: isAr ? `AI (${result?.smart_matched?.length || 0})` : `AI (${result?.smart_matched?.length || 0})`, icon: "🤖" },
  ];

  return (
    <div className="fade-in p-4 w-full h-full flex flex-col overflow-hidden text-[11px]" dir={isAr ? "rtl" : "ltr"}>

      {/* ── Header ── */}
      <div className="mb-2 flex items-center justify-between gap-2 flex-wrap">
        <div>
          <Link href="/erp" className="gold-text text-[10px] tracking-widest hover:underline uppercase transition-all">
            {isAr ? "← ERP" : "← ERP"}
          </Link>
          <h1 className="mt-0.5 text-xl font-bold">
            {isAr ? "تقرير المطابقة البنكية" : "Bank Reconciliation Report"}
          </h1>
          <p className="text-[11px] text-white/50">
            {isAr ? "تسوية كشف الحساب البنكي مع دفاتر أودو" : "Bank statement vs Odoo ledger reconciliation"}
          </p>
        </div>

        {result && (
          <div className="flex items-center gap-2">
            {/* Export Buttons */}
            <button
              onClick={() => exportToCSV(result, companyName, period || new Date().toLocaleDateString("ar-SA"))}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/15 border border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/25 rounded-lg text-xs font-semibold transition-all"
            >
              📊 {isAr ? "تصدير Excel" : "Export Excel"}
            </button>
            <button
              onClick={() => exportToPDF(result, companyName, period || new Date().toLocaleDateString("ar-SA"), bankName, accountNo)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-rose-500/15 border border-rose-500/40 text-rose-400 hover:bg-rose-500/25 rounded-lg text-xs font-semibold transition-all"
            >
              🖨️ {isAr ? "طباعة / PDF" : "Print / PDF"}
            </button>
            {/* Status badge */}
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-xl border ${
              isReconciled ? "bg-emerald-500/10 border-emerald-500/30" : "bg-rose-500/10 border-rose-500/30"
            }`}>
              <div className={`w-2 h-2 rounded-full ${
                isReconciled ? "bg-emerald-400" : "bg-rose-400 animate-pulse"
              }`} />
              <p className={`font-bold text-xs tabular-nums ${
                isReconciled ? "text-emerald-400" : "text-rose-400"
              }`}>
                {isReconciled
                  ? (isAr ? "✓ متوافق" : "✓ RECONCILED")
                  : `${result.difference >= 0 ? "+" : ""}${fmt(result.difference)} SAR`
                }
              </p>
            </div>
          </div>
        )}
      </div>

      <div className="gold-divider mb-3" />

      {/* ── Company Info Banner (for export) ── */}
      {result && (
        <div className="mb-3">
          <button
            onClick={() => setShowCompanyForm(v => !v)}
            className="text-[10px] text-white/40 hover:text-amber-400 transition-colors flex items-center gap-1"
          >
            ⚙️ {isAr ? (showCompanyForm ? "إخفاء بيانات الشركة" : "تحديد بيانات الشركة للتقرير") : (showCompanyForm ? "Hide company info" : "Set company info for report")}
          </button>
          {showCompanyForm && (
            <div className="mt-2 grid grid-cols-2 md:grid-cols-4 gap-2 bg-black/40 border border-white/10 p-3 rounded-xl">
              {[
                { label: isAr ? "اسم الشركة" : "Company Name", val: companyName, set: setCompanyName },
                { label: isAr ? "اسم البنك" : "Bank Name", val: bankName, set: setBankName },
                { label: isAr ? "رقم الحساب" : "Account No.", val: accountNo, set: setAccountNo },
                { label: isAr ? "الفترة" : "Period", val: period, set: setPeriod, placeholder: isAr ? "مثال: يونيو 2026" : "e.g. June 2026" },
              ].map(f => (
                <div key={f.label}>
                  <label className="block text-[10px] text-white/50 mb-0.5">{f.label}</label>
                  <input
                    value={f.val}
                    onChange={e => f.set(e.target.value)}
                    placeholder={(f as any).placeholder || ""}
                    className="w-full bg-black/60 border border-white/20 text-white px-2 py-1 rounded-lg text-xs focus:border-amber-400 outline-none"
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Upload Panel ── */}
      {!result && (
        <div className="wood-panel !p-4 rounded-[16px] mb-3 space-y-3">
          <h2 className="text-sm font-bold gold-text">{isAr ? "رفع كشف الحساب" : "Upload Bank Statement"}</h2>

          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileRef.current?.click()}
            className={`relative border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all ${
              dragging ? "border-amber-400 bg-amber-500/10"
                : file ? "border-emerald-500/50 bg-emerald-500/5"
                : "border-white/20 hover:border-white/40 hover:bg-white/5"
            }`}
          >
            <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" className="hidden"
              onChange={(e) => e.target.files?.[0] && setFile(e.target.files[0])} />
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

          <div className="grid grid-cols-3 gap-2">
            {[
              { label: isAr ? "رقم دفتر اليومية" : "Journal ID", val: journalId, set: setJournalId, type: "text", placeholder: isAr ? "اختياري" : "optional" },
              { label: isAr ? "من تاريخ" : "Date From", val: dateFrom, set: setDateFrom, type: "date" },
              { label: isAr ? "إلى تاريخ" : "Date To", val: dateTo, set: setDateTo, type: "date" },
            ].map(f => (
              <div key={f.label} className="space-y-0.5">
                <label className="block text-[10px] font-medium gold-text">{f.label}</label>
                <input type={f.type} placeholder={(f as any).placeholder || ""} value={f.val}
                  onChange={(e) => f.set(e.target.value)}
                  className="w-full bg-black/40 border border-white/20 text-white px-2 py-1 text-xs rounded-lg outline-none focus:border-yellow-500 transition-colors" />
              </div>
            ))}
          </div>

          {errorMsg && (
            <div className="bg-red-500/10 border border-red-500/30 p-3 rounded-xl text-red-300 text-xs">❌ {errorMsg}</div>
          )}

          <button onClick={handleRun} disabled={!file || loading}
            className="w-full cursor-pointer bg-gradient-to-r from-amber-500 to-yellow-600 hover:from-amber-600 hover:to-yellow-700 disabled:opacity-40 text-black font-bold py-2 rounded-xl text-xs transition-all shadow-lg active:scale-[0.98] flex items-center justify-center gap-2">
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
        <div className="flex-1 min-h-0 flex flex-col gap-2 overflow-hidden">

          {/* KPI Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <div className="wood-card !p-2.5 border-emerald-500/20">
              <p className="text-[10px] text-white/50">{isAr ? "متطابق" : "Matched"}</p>
              <p className="text-2xl font-bold text-emerald-400 tabular-nums">{result.matched.length}</p>
              <p className="text-[9px] text-white/40">{isAr ? "عملية" : "transactions"}</p>
            </div>
            <div className="wood-card !p-2.5 border-amber-500/20">
              <p className="text-[10px] text-white/50">{isAr ? "في الكشف فقط" : "Statement Only"}</p>
              <p className="text-2xl font-bold text-amber-400 tabular-nums">{result.statement_only.length}</p>
              <p className="text-[9px] text-amber-400/60">{isAr ? "تحتاج قيود" : "need entries"}</p>
            </div>
            <div className="wood-card !p-2.5 border-rose-500/20">
              <p className="text-[10px] text-white/50">{isAr ? "في أودو فقط" : "Odoo Only"}</p>
              <p className="text-2xl font-bold text-rose-400 tabular-nums">{result.ledger_only.length}</p>
              <p className="text-[9px] text-white/40">{isAr ? "غير مطابق" : "unmatched"}</p>
            </div>
            <div className={`wood-card !p-2.5 ${isReconciled ? "border-emerald-500/30" : "border-rose-500/30"}`}>
              <p className="text-[10px] text-white/50">{isAr ? "الفرق الإجمالي" : "Net Difference"}</p>
              <p className={`text-xl font-bold tabular-nums ${isReconciled ? "text-emerald-400" : "text-rose-400"}`}>
                {result.difference >= 0 ? "+" : ""}{fmt(result.difference)}
              </p>
              <p className="text-[9px] text-white/40">SAR</p>
            </div>
          </div>

          {/* Reset link */}
          <div className="flex justify-between items-center px-1 text-[11px] text-white/40">
            <span>
              {isAr ? "إجمالي الكشف:" : "Statement:"} <span className="gold-text tabular-nums">{fmt(result.statement_total)} SAR</span>
              <span className="mx-2 text-white/20">|</span>
              {isAr ? "إجمالي أودو:" : "Odoo:"} <span className="gold-text tabular-nums">{fmt(result.ledger_total)} SAR</span>
            </span>
            <span className="cursor-pointer hover:text-white/70 transition-colors" onClick={() => { setResult(null); setFile(null); }}>↩ {isAr ? "تسوية جديدة" : "New"}</span>
          </div>

          {/* Tabs */}
          <div className="flex flex-wrap gap-1 bg-black/30 px-2 py-1.5 rounded-xl border border-white/5">
            {tabs.map(tab => (
              <button key={tab.key} onClick={() => setActiveTab(tab.key)}
                className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold border transition-all ${
                  activeTab === tab.key
                    ? "bg-amber-500/20 border-amber-500/40 text-amber-300"
                    : "border-transparent text-white/50 hover:text-white hover:bg-white/5"
                }`}>
                {tab.icon} {tab.label}
              </button>
            ))}
          </div>

          {/* Tab Content */}
          <div className="flex-1 min-h-0 wood-panel rounded-xl overflow-hidden flex flex-col">

            {/* ── SUMMARY TAB ── */}
            {activeTab === "summary" && (
              <div className="flex-1 overflow-auto p-4 space-y-4">
                <h3 className="text-sm font-bold gold-text border-b border-white/10 pb-2">
                  {isAr ? "تقرير المطابقة البنكية" : "Bank Reconciliation Statement"}
                </h3>

                {/* Bank Side */}
                <div className="bg-black/30 rounded-xl p-3 border border-white/10">
                  <p className="text-xs font-bold text-blue-300 mb-2 uppercase tracking-wide">🏦 {isAr ? "جانب البنك | BANK SIDE" : "BANK SIDE"}</p>
                  <div className="space-y-0.5">
                    <SectionRow label={isAr ? "رصيد كشف الحساب البنكي / Balance per Bank Statement" : "Balance per Bank Statement"} value={<><span className="gold-text tabular-nums">{fmt(result.statement_total)} SAR</span></>} />
                    <SectionRow label={isAr ? "(+) إيداعات قيد التسوية / Deposits in Transit" : "(+) Deposits in Transit"} value="0.00 SAR" indent />
                    <SectionRow label={isAr ? "(-) شيكات قيد التسوية / Outstanding Checks" : "(-) Outstanding Checks"} value="0.00 SAR" indent />
                    <SectionRow label={isAr ? "(±) أخطاء البنك / Bank Errors" : "(±) Bank Errors"} value="0.00 SAR" indent />
                    <SectionRow label={isAr ? "الرصيد المتوافق / Adjusted Bank Balance" : "Adjusted Bank Balance"} value={<span className="text-amber-400 font-bold tabular-nums">{fmt(result.statement_total)} SAR</span>} bold />
                  </div>
                </div>

                {/* Book Side */}
                <div className="bg-black/30 rounded-xl p-3 border border-white/10">
                  <p className="text-xs font-bold text-purple-300 mb-2 uppercase tracking-wide">📒 {isAr ? "جانب الدفتر | BOOK (LEDGER) SIDE" : "BOOK (LEDGER) SIDE"}</p>
                  <div className="space-y-0.5">
                    <SectionRow label={isAr ? "رصيد الدفتر المحاسبي / Balance per Books" : "Balance per Books (Odoo)"} value={<span className="gold-text tabular-nums">{fmt(result.ledger_total)} SAR</span>} />
                    <SectionRow label={isAr ? "(+) فوائد بنكية / Interest Earned" : "(+) Interest Earned"} value="0.00 SAR" indent />
                    <SectionRow label={isAr ? "(-) رسوم بنكية / Bank Charges" : "(-) Bank Charges & Fees"} value="0.00 SAR" indent />
                    <SectionRow label={isAr ? "(-) شيكات بدون رصيد (NSF) / NSF Checks" : "(-) NSF Checks"} value="0.00 SAR" indent />
                    <SectionRow label={isAr ? "(±) أخطاء الدفتر / Book Errors" : "(±) Book Errors"} value="0.00 SAR" indent />
                    <SectionRow label={isAr ? "الرصيد المتوافق / Adjusted Book Balance" : "Adjusted Book Balance"} value={<span className="text-amber-400 font-bold tabular-nums">{fmt(result.ledger_total)} SAR</span>} bold />
                  </div>
                </div>

                {/* Reconciliation Check */}
                <div className={`rounded-xl p-3 border ${
                  isReconciled ? "bg-emerald-500/10 border-emerald-500/30" : "bg-rose-500/10 border-rose-500/30"
                }`}>
                  <p className="text-xs font-bold text-white/70 mb-2 uppercase tracking-wide">📋 {isAr ? "التحقق من المطابقة | RECONCILIATION CHECK" : "RECONCILIATION CHECK"}</p>
                  <SectionRow
                    label={isAr ? "الفرق (يجب أن يكون صفر) / Difference" : "Difference (Should be Zero)"}
                    value={<span className={`font-bold tabular-nums ${isReconciled ? "text-emerald-400" : "text-rose-400"}`}>{result.difference >= 0 ? "+" : ""}{fmt(result.difference)} SAR</span>}
                    bold
                  />
                  <div className={`mt-3 text-center py-2 rounded-lg font-bold text-sm ${
                    isReconciled ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300"
                  }`}>
                    {isReconciled
                      ? (isAr ? "✓ متوافق | RECONCILED" : "✓ RECONCILED")
                      : (isAr ? "✗ يوجد فرق — مراجعة مطلوبة" : "✗ DIFFERENCE — REVIEW REQUIRED")
                    }
                  </div>
                </div>

                {/* Summary Metrics */}
                <div className="bg-black/20 rounded-xl p-3 border border-white/10">
                  <p className="text-xs font-bold text-white/50 mb-2 uppercase tracking-wide">{isAr ? "ملخص المؤشرات | SUMMARY METRICS" : "SUMMARY METRICS"}</p>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
                    <SectionRow label={isAr ? "عدد المتطابقات" : "Matched Count"} value={String(result.matched.length)} />
                    <SectionRow label={isAr ? "إجمالي عمليات الكشف" : "Statement Transactions"} value={String(result.statement_count)} />
                    <SectionRow label={isAr ? "في الكشف فقط" : "Statement Only"} value={String(result.statement_only.length)} />
                    <SectionRow label={isAr ? "إجمالي عمليات أودو" : "Odoo Transactions"} value={String(result.ledger_count)} />
                    <SectionRow label={isAr ? "في أودو فقط" : "Odoo Only"} value={String(result.ledger_only.length)} />
                    <SectionRow label={isAr ? "مقترحات AI" : "AI Suggestions"} value={String(result.smart_matched?.length || 0)} />
                  </div>
                </div>

                {/* Authorization */}
                <div className="bg-black/20 rounded-xl p-3 border border-white/10">
                  <p className="text-xs font-bold text-white/50 mb-3 uppercase tracking-wide">{isAr ? "الاعتماد | AUTHORIZATION" : "AUTHORIZATION"}</p>
                  <div className="grid grid-cols-3 gap-4">
                    {[
                      isAr ? "أعده / Prepared by" : "Prepared by",
                      isAr ? "راجعه / Reviewed by" : "Reviewed by",
                      isAr ? "وافق عليه / Approved by" : "Approved by",
                    ].map(label => (
                      <div key={label} className="text-center space-y-2">
                        <p className="text-[10px] font-bold text-white/70">{label}</p>
                        <div className="border-b border-white/20 pb-4" />
                        <p className="text-[9px] text-white/30">{isAr ? "التوقيع" : "Signature"}</p>
                        <p className="text-[9px] text-white/30 mt-1">{isAr ? "التاريخ: ___/___/______" : "Date: ___/___/______"}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* ── MATCHED TAB ── */}
            {activeTab === "matched" && (
              <>
                <div className="p-3 border-b border-white/10 flex justify-between items-center">
                  <h3 className="text-sm font-bold gold-text">{isAr ? "المعاملات المتطابقة" : "Matched Transactions"}</h3>
                  <span className="text-[10px] text-white/40">{result.matched.length} {isAr ? "زوج" : "pairs"}</span>
                </div>
                <div className="flex-1 overflow-auto">
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
                        <div className="px-4 py-2.5 flex items-center justify-between">
                          <div className="flex flex-col gap-0.5 min-w-0">
                            <p className="text-xs font-medium text-white truncate max-w-[200px]">{pair.statement_txn.description || "—"}</p>
                            <p className="text-[10px] text-white/40 font-mono">{pair.statement_txn.date}</p>
                          </div>
                          <AmountBadge amount={pair.statement_txn.amount} />
                        </div>
                        <div className="px-4 py-2.5 flex items-center justify-between border-l border-white/10">
                          <div className="flex flex-col gap-0.5 min-w-0">
                            <p className="text-xs font-medium text-white truncate max-w-[200px]">{pair.ledger_txn.description || "—"}</p>
                            <p className="text-[10px] text-white/40 font-mono">{pair.ledger_txn.date}</p>
                          </div>
                          <div className="flex items-center gap-2">
                            <AmountBadge amount={pair.ledger_txn.amount} />
                            <span className="text-emerald-400 text-sm">✓</span>
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </>
            )}

            {/* ── STATEMENT ONLY TAB ── */}
            {activeTab === "stmt_only" && (
              <>
                <div className="p-3 border-b border-white/10">
                  <h3 className="text-sm font-bold gold-text">{isAr ? "في الكشف البنكي فقط" : "Statement Only"}</h3>
                  <p className="text-[10px] text-amber-400/70 mt-0.5">
                    {isAr
                      ? "هذه العمليات موجودة في البنك لكن غير مسجلة في أودو — يمكنك إدخالها مباشرة"
                      : "Present in bank but not recorded in Odoo — you can post entries directly"}
                  </p>
                </div>
                <div className="flex-1 overflow-auto">
                  {result.statement_only.length === 0 ? (
                    <div className="p-10 text-center text-white/30 italic">{isAr ? "لا توجد فروقات" : "No discrepancies"}</div>
                  ) : (
                    <div className="divide-y divide-white/5">
                      {result.statement_only.map((txn, idx) => {
                        const state = entryForms[idx];
                        const isSubmitted = state?.submitted;
                        const isOpen = state?.open;
                        return (
                          <div key={idx} className={`px-4 py-3 transition-colors ${
                            isSubmitted ? "bg-emerald-500/5" : "hover:bg-white/3"
                          }`}>
                            <div className="flex items-center justify-between gap-3">
                              <div className="flex items-center gap-3 min-w-0">
                                <span className="text-[10px] font-mono text-white/40 shrink-0">{idx + 1}</span>
                                <div className="min-w-0">
                                  <p className="text-xs font-medium text-white truncate">{txn.description || "—"}</p>
                                  <p className="text-[10px] text-white/40 font-mono">{txn.date}</p>
                                </div>
                              </div>
                              <div className="flex items-center gap-2 shrink-0">
                                <AmountBadge amount={txn.amount} />
                                {isSubmitted ? (
                                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                                    ✓ {isAr ? "تم التسجيل" : "Posted"}
                                  </span>
                                ) : (
                                  <>
                                    <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/30">
                                      {isAr ? "غير مسجل" : "Unrecorded"}
                                    </span>
                                    <button
                                      onClick={() => isOpen ? closeEntry(idx) : openEntry(idx)}
                                      className={`text-[10px] font-bold px-2 py-0.5 rounded-full border transition-all ${
                                        isOpen
                                          ? "bg-white/10 border-white/20 text-white/60"
                                          : "bg-blue-500/15 border-blue-500/40 text-blue-300 hover:bg-blue-500/25"
                                      }`}
                                    >
                                      {isOpen ? (isAr ? "↑ إغلاق" : "↑ Close") : (isAr ? "+ إدخال قيد" : "+ Post Entry")}
                                    </button>
                                  </>
                                )}
                              </div>
                            </div>
                            {isOpen && !isSubmitted && (
                              <InlineEntryForm
                                txn={txn}
                                isAr={isAr}
                                onSubmit={() => submitEntry(idx)}
                                onCancel={() => closeEntry(idx)}
                              />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
                {result.statement_only.length > 0 && (
                  <div className="p-3 border-t border-white/10 flex justify-between items-center">
                    <span className="text-[10px] text-white/40">
                      {isAr ? "تم تسجيل" : "Posted"}: <span className="text-emerald-400 font-bold">{Object.values(entryForms).filter(f => f.submitted).length}</span> / {result.statement_only.length}
                    </span>
                    <span className="text-[10px] tabular-nums text-white/60">
                      {isAr ? "الإجمالي:" : "Total:"} <span className="gold-text font-bold">{fmt(result.statement_only.reduce((s, t) => s + t.amount, 0))} SAR</span>
                    </span>
                  </div>
                )}
              </>
            )}

            {/* ── LEDGER ONLY TAB ── */}
            {activeTab === "ledger_only" && (
              <>
                <div className="p-3 border-b border-white/10">
                  <h3 className="text-sm font-bold gold-text">{isAr ? "في أودو فقط" : "Odoo Ledger Only"}</h3>
                  <p className="text-[10px] text-rose-400/70 mt-0.5">{isAr ? "مسجلة في أودو لكن لا تظهر في الكشف البنكي" : "Recorded in Odoo but absent from the bank statement"}</p>
                </div>
                <div className="flex-1 overflow-auto">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="bg-black/30 text-white/40 uppercase tracking-wider text-[10px] border-b border-white/10">
                        <th className="px-4 py-2">#</th>
                        <th className="px-4 py-2">{isAr ? "التاريخ" : "Date"}</th>
                        <th className="px-4 py-2">{isAr ? "الوصف" : "Description"}</th>
                        <th className="px-4 py-2 text-right">{isAr ? "المبلغ" : "Amount"}</th>
                        <th className="px-4 py-2 text-center">{isAr ? "الحالة" : "Status"}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                      {result.ledger_only.length === 0 ? (
                        <tr><td colSpan={5} className="p-8 text-center text-white/30 italic">{isAr ? "لا توجد فروقات" : "No discrepancies"}</td></tr>
                      ) : (
                        result.ledger_only.map((txn, idx) => (
                          <tr key={idx} className="hover:bg-white/5 transition-colors">
                            <td className="px-4 py-2.5 text-[10px] text-white/30">{idx + 1}</td>
                            <td className="px-4 py-2.5 font-mono text-[11px] text-white/60">{txn.date}</td>
                            <td className="px-4 py-2.5 text-xs text-white max-w-[280px]"><p className="truncate">{txn.description || "—"}</p></td>
                            <td className="px-4 py-2.5 text-right"><AmountBadge amount={txn.amount} /></td>
                            <td className="px-4 py-2.5 text-center">
                              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full border bg-rose-500/10 text-rose-300 border-rose-500/30">
                                {isAr ? "في أودو فقط" : "Odoo Only"}
                              </span>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
                {result.ledger_only.length > 0 && (
                  <div className="p-3 border-t border-white/10 text-right">
                    <span className="text-[10px] text-white/40">{isAr ? "الإجمالي:" : "Total:"} <span className="gold-text font-bold tabular-nums">{fmt(result.ledger_only.reduce((s, t) => s + t.amount, 0))} SAR</span></span>
                  </div>
                )}
              </>
            )}

            {/* ── AI SMART MATCHES TAB ── */}
            {activeTab === "smart" && (
              <>
                <div className="p-3 border-b border-white/10 flex justify-between items-center">
                  <div>
                    <h3 className="text-sm font-bold gold-text">{isAr ? "مطابقات الذكاء الاصطناعي" : "AI Smart Matches"}</h3>
                    <p className="text-[10px] text-purple-400/70 mt-0.5">{isAr ? "مقترحات بنسبة ثقة عالية" : "High-confidence suggestions"}</p>
                  </div>
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
                          <AmountBadge amount={sm.statement_txn.amount} />
                        </div>
                        <div className="px-4 py-2.5 flex items-center justify-between border-l border-white/10">
                          <div className="flex flex-col gap-0.5 min-w-0">
                            <p className="text-xs font-medium text-white truncate max-w-[160px]">{sm.ledger_txn.description || "—"}</p>
                            <p className="text-[10px] text-purple-400/70 italic truncate max-w-[160px]" title={sm.reason}>{sm.reason}</p>
                          </div>
                          <div className="flex items-center gap-1.5 shrink-0">
                            <AmountBadge amount={sm.ledger_txn.amount} />
                            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full border ${
                              sm.confidence >= 0.8 ? "text-emerald-400 border-emerald-500/30 bg-emerald-500/10"
                              : sm.confidence >= 0.6 ? "text-amber-400 border-amber-500/30 bg-amber-500/10"
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

          </div>
        </div>
      )}
    </div>
  );
}
