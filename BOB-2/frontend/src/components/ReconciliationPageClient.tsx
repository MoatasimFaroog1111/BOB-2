"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { API_BASE_URL } from "@/lib/api";
import { useLanguage } from "@/lib/LanguageContext";
import { useCompany } from "@/lib/CompanyContext";
import ReconciliationResultsPanel from "@/components/ReconciliationResultsPanel";

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

interface PartnerOption {
  id: number | string;
  name: string;
  customer_rank?: number;
  supplier_rank?: number;
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

function downloadCSV(filename: string, rows: string[][]) {
  const csv = rows.map(row => row.map(cell => `"${String(cell ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
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
                <div className={`mt-1 font-mono ${amountColor(txn.amount)}`}>{txn.amount >= 0 ? "+" : "-"} {fmt(Math.abs(txn.amount))} SAR</div>
              </td>
              <td className="px-3 py-2 text-left font-mono tabular-nums text-rose-300">{txn.debit ? fmt(txn.debit) : "0.00"}</td>
              <td className="px-3 py-2 text-left font-mono tabular-nums text-emerald-300">{txn.credit ? fmt(txn.credit) : "0.00"}</td>
              <td className="px-3 py-2 text-left font-mono tabular-nums text-amber-300">{txn.balance !== null && txn.balance !== undefined ? fmt(txn.balance) : "—"}</td>
              <td className="px-3 py-2 text-right text-white/65 leading-relaxed">
                {txn.details && txn.details.length > 0 ? (
                  <details>
                    <summary className="cursor-pointer text-blue-300 font-semibold">{isAr ? "عرض التفاصيل" : "Show details"}</summary>
                    <div className="mt-2 space-y-1">{txn.details.map((detail, i) => <div key={i} className="border-b border-white/5 pb-1">{detail}</div>)}</div>
                  </details>
                ) : <span className="text-white/30">—</span>}
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
      <div className="wood-card !p-3 border-blue-500/20"><p className="text-[10px] text-white/50">{isAr ? "عدد عمليات الكشف" : "Statement Rows"}</p><p className="text-2xl font-bold text-blue-300 tabular-nums">{rows.length}</p></div>
      <div className="wood-card !p-3 border-emerald-500/20"><p className="text-[10px] text-white/50">{isAr ? "إجمالي الدائن / الإيداعات" : "Total Credit"}</p><p className="text-xl font-bold text-emerald-300 tabular-nums">{fmt(totalCredit)}</p><p className="text-[9px] text-white/40">SAR</p></div>
      <div className="wood-card !p-3 border-rose-500/20"><p className="text-[10px] text-white/50">{isAr ? "إجمالي المدين / السحوبات" : "Total Debit"}</p><p className="text-xl font-bold text-rose-300 tabular-nums">{fmt(totalDebit)}</p><p className="text-[9px] text-white/40">SAR</p></div>
      <div className="wood-card !p-3 border-amber-500/20"><p className="text-[10px] text-white/50">{isAr ? "الرصيد الختامي" : "Closing Balance"}</p><p className="text-xl font-bold text-amber-300 tabular-nums">{closing !== null && closing !== undefined ? fmt(closing) : fmt(result.statement_total)}</p><p className="text-[9px] text-white/40">SAR</p></div>
      {opening !== null && opening !== undefined && <div className="col-span-2 md:col-span-4 rounded-xl border border-white/10 bg-black/20 p-2 text-[11px] text-white/60">{isAr ? "الرصيد الافتتاحي المحسوب من الكشف:" : "Calculated opening balance:"}<span className="ms-2 font-mono text-amber-300">{fmt(opening)} SAR</span></div>}
    </div>
  );
}

export default function ReconciliationPageClient() {
  const { language } = useLanguage();
  const { selectedCompanyId, selectedCompany } = useCompany();
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
  const [partners, setPartners] = useState<PartnerOption[]>([]);
  const [selectedPartnerId, setSelectedPartnerId] = useState("");
  const [loadingPartners, setLoadingPartners] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const statementRows = useMemo(() => uniqueStatementRows(result), [result]);

  useEffect(() => {
    let mounted = true;
    async function loadBankAccounts() {
      if (!selectedCompanyId) {
        setBankAccounts([]);
        setSelectedBankAccountId("");
        return;
      }
      try {
        const params = new URLSearchParams({ company_id: String(selectedCompanyId) });
        const res = await fetch(`${API_BASE_URL}/api/v1/erp/accounts?${params.toString()}`);
        if (!res.ok) return;
        const data = await res.json();
        const normalized: BankAccountOption[] = (Array.isArray(data) ? data : []).map((account: any) => ({ id: account.id, code: account.code || "", name: account.name || "", label: `${account.code || ""} ${account.name || ""}`.trim() }));
        const bankLike = normalized.filter(account => /bank|بنك|مصرف|riyadh|رياض|cash|نقد|101|102/i.test(`${account.code} ${account.name}`));
        const options = bankLike.length ? bankLike : normalized;
        if (!mounted) return;
        setBankAccounts(options);
        setSelectedBankAccountId(prev => prev && options.some(option => String(option.id) === String(prev)) ? prev : options[0] ? String(options[0].id) : "");
      } catch (err) {
        console.warn("Failed to load bank accounts", err);
      }
    }
    loadBankAccounts();
    return () => { mounted = false; };
  }, [selectedCompanyId]);

  useEffect(() => {
    let mounted = true;
    async function loadPartners() {
      if (!selectedCompanyId) {
        setPartners([]);
        setSelectedPartnerId("");
        return;
      }
      setLoadingPartners(true);
      try {
        const params = new URLSearchParams({ company_id: String(selectedCompanyId) });
        const res = await fetch(`${API_BASE_URL}/api/v1/erp/partners?${params.toString()}`);
        if (!res.ok) return;
        const data = await res.json();
        const normalized: PartnerOption[] = (Array.isArray(data) ? data : []).map((partner: any) => {
          const customerRank = Number(partner.customer_rank || 0);
          const supplierRank = Number(partner.supplier_rank || 0);
          const typeLabel = customerRank > 0 && supplierRank > 0 ? (isAr ? "عميل ومورد" : "Customer & Vendor") : customerRank > 0 ? (isAr ? "عميل" : "Customer") : supplierRank > 0 ? (isAr ? "مورد" : "Vendor") : "";
          const name = partner.name || "";
          return { id: partner.id, name, customer_rank: customerRank, supplier_rank: supplierRank, label: typeLabel ? `${name} • ${typeLabel}` : name };
        }).filter((partner: PartnerOption) => partner.id && partner.name).sort((a: PartnerOption, b: PartnerOption) => a.name.localeCompare(b.name));
        const customerSupplierOnly = normalized.filter(partner => Number(partner.customer_rank || 0) > 0 || Number(partner.supplier_rank || 0) > 0);
        const options = customerSupplierOnly.length ? customerSupplierOnly : normalized;
        if (!mounted) return;
        setPartners(options);
        setSelectedPartnerId(prev => prev && options.some(option => String(option.id) === String(prev)) ? prev : "");
      } catch (err) {
        console.warn("Failed to load partners", err);
        if (mounted) setPartners([]);
      } finally {
        if (mounted) setLoadingPartners(false);
      }
    }
    loadPartners();
    return () => { mounted = false; };
  }, [selectedCompanyId, isAr]);

  const runReconciliationRequest = async (includeBankAccount: boolean) => {
    if (!file) return;
    const formData = new FormData();
    formData.append("statement", file);
    if (selectedCompanyId) formData.append("company_id", String(selectedCompanyId));
    if (dateFrom) formData.append("date_from", dateFrom);
    if (dateTo) formData.append("date_to", dateTo);

    // If includeBankAccount=false, use the parse-only endpoint (no Odoo connection needed)
    if (!includeBankAccount) {
      const res = await fetch(`${API_BASE_URL}/api/v1/erp/bank-statement-parse`, { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || (isAr ? "فشل قراءة الملف" : "Failed to parse file"));
      setResult(data);
      return;
    }

    // If includeBankAccount=true, use the full endpoint with Odoo matching
    if (selectedPartnerId) {
      formData.append("partner_id", selectedPartnerId);
      formData.append("selected_partner_id", selectedPartnerId);
      formData.append("odoo_partner_id", selectedPartnerId);
    }
    if (selectedBankAccountId) {
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
    if (!selectedCompanyId) { setErrorMsg(isAr ? "اختر الشركة أولاً حتى تتم قراءة البيانات ضمن الشركة الصحيحة." : "Select a company first."); return; }
    setReading(true); setErrorMsg(""); setMatchAttempted(false);
    try { await runReconciliationRequest(false); } catch (err: any) { setErrorMsg(err.message); } finally { setReading(false); }
  };

  const handleBankMatch = async () => {
    if (!selectedCompanyId) { setErrorMsg(isAr ? "اختر الشركة أولاً." : "Select a company first."); return; }
    if (!selectedBankAccountId) { setErrorMsg(isAr ? "اختر الحساب البنكي أولاً." : "Select a bank account first."); return; }
    setMatching(true); setErrorMsg("");
    try { await runReconciliationRequest(true); setMatchAttempted(true); } catch (err: any) { setErrorMsg(err.message); } finally { setMatching(false); }
  };

  const exportCSV = () => {
    if (!result) return;
    const header = ["#", "Gregorian Date", "Hijri Date", "Description", "Debit", "Credit", "Balance", "Details"];
    const rows = statementRows.map((row, i) => [String(i + 1), row.date, row.hijri_date || "", row.main_description || row.description || "", fmt(row.debit || 0), fmt(row.credit || 0), row.balance !== null && row.balance !== undefined ? fmt(row.balance) : "", (row.details || []).join(" | ")]);
    downloadCSV("bank_statement_reconciliation.csv", [header, ...rows]);
  };

  return (
    <div className="fade-in p-4 w-full h-full flex flex-col overflow-hidden text-[11px]" dir={isAr ? "rtl" : "ltr"}>
      <div className="mb-2 flex items-center justify-between gap-2 flex-wrap">
        <div>
          <Link href="/erp" className="gold-text text-[10px] tracking-widest hover:underline uppercase transition-all">← ERP</Link>
          <h1 className="mt-0.5 text-xl font-bold">{isAr ? "تقرير المطابقة البنكية" : "Bank Reconciliation Report"}</h1>
          <p className="text-[11px] text-white/50">{isAr ? "اقرأ كشف البنك أولاً، ثم اختر الحساب البنكي والمورد أو العميل واضغط أيقونة التسوية للمطابقة." : "Read the bank statement, then choose the bank account and customer/vendor before running matching."}</p>
          <p className="mt-1 text-[10px] text-amber-300/80">{isAr ? "الشركة الحالية:" : "Current company:"} <span className="font-bold">{selectedCompany?.name || (isAr ? "لم يتم اختيار شركة" : "No company selected")}</span></p>
        </div>
        {result && <div className="flex gap-2"><button onClick={exportCSV} className="px-3 py-1.5 bg-emerald-500/15 border border-emerald-500/40 text-emerald-400 rounded-lg text-xs font-semibold">📊 {isAr ? "تصدير Excel" : "Export CSV"}</button><button onClick={() => window.print()} className="px-3 py-1.5 bg-rose-500/15 border border-rose-500/40 text-rose-400 rounded-lg text-xs font-semibold">🖨️ {isAr ? "طباعة / PDF" : "Print / PDF"}</button></div>}
      </div>

      <div className="gold-divider mb-3" />

      {!result && <div className="wood-panel !p-4 rounded-[16px] mb-3 space-y-3">
        <h2 className="text-sm font-bold gold-text">{isAr ? "رفع وقراءة كشف الحساب" : "Upload and read bank statement"}</h2>
        <div onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(e) => { e.preventDefault(); setDragging(false); const dropped = e.dataTransfer.files[0]; if (dropped) { setFile(dropped); setResult(null); setMatchAttempted(false); } }} onClick={() => fileRef.current?.click()} className={`relative border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all ${dragging ? "border-amber-400 bg-amber-500/10" : file ? "border-emerald-500/50 bg-emerald-500/5" : "border-white/20 hover:border-white/40 hover:bg-white/5"}`}>
          <input ref={fileRef} type="file" accept=".csv,.tsv,.txt,.xlsx,.xls,.xlsm,.pdf,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,.ofx,.qfx,.qif,.mt940,.sta" className="hidden" onChange={(e) => { if (e.target.files?.[0]) { setFile(e.target.files[0]); setResult(null); setMatchAttempted(false); } }} />
          {file ? <div className="space-y-1"><p className="text-2xl">📄</p><p className="font-semibold text-white">{file.name}</p><p className="text-[10px] text-white/50">{(file.size / 1024).toFixed(1)} KB • {isAr ? "جاهز للقراءة" : "Ready to read"}</p></div> : <div className="space-y-1"><p className="text-3xl">📂</p><p className="text-white/70 font-medium">{isAr ? "اسحب الملف هنا أو انقر للاختيار" : "Drag file here or click to browse"}</p><p className="text-[10px] text-white/40">Excel · CSV · PDF · Images · OFX/QIF/MT940</p></div>}
        </div>
        <div className="grid grid-cols-2 gap-2"><div><label className="block text-[10px] font-medium gold-text">{isAr ? "من تاريخ" : "Date From"}</label><input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="w-full bg-black/40 border border-white/20 text-white px-2 py-1 text-xs rounded-lg outline-none" /></div><div><label className="block text-[10px] font-medium gold-text">{isAr ? "إلى تاريخ" : "Date To"}</label><input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="w-full bg-black/40 border border-white/20 text-white px-2 py-1 text-xs rounded-lg outline-none" /></div></div>
        {errorMsg && <div className="bg-red-500/10 border border-red-500/30 p-3 rounded-xl text-red-300 text-xs">❌ {errorMsg}</div>}
        <button onClick={handleReadFile} disabled={!file || reading || !selectedCompanyId} className="w-full bg-gradient-to-r from-blue-500 to-cyan-500 disabled:opacity-40 text-black font-bold py-2 rounded-xl text-xs flex items-center justify-center gap-2">{reading ? <><span className="w-4 h-4 border-2 border-black border-t-transparent rounded-full animate-spin" /> {isAr ? "جاري قراءة الملف..." : "Reading file..."}</> : <>📖 {isAr ? "قراءة كشف الحساب" : "Read bank statement"}</>}</button>
      </div>}

      {result && <div className="flex-1 min-h-0 flex flex-col gap-3 overflow-hidden">
        <SummaryCards rows={statementRows} result={result} isAr={isAr} />
        <div className="rounded-2xl border border-amber-500/25 bg-gradient-to-r from-amber-500/10 to-yellow-500/5 p-3"><div className="flex flex-col md:flex-row gap-3 md:items-end md:justify-between"><div className="flex-1"><div className="flex items-center gap-2 mb-1"><span className="text-2xl">🏦</span><div><p className="text-sm font-bold text-amber-300">{isAr ? "أيقونة التسوية البنكية" : "Bank Reconciliation"}</p><p className="text-[10px] text-white/50">{isAr ? "الحسابات والعملاء والموردون المعروضون أدناه تابعون للشركة المختارة فقط." : "The accounts, customers, and vendors below belong only to the selected company."}</p><p className="text-[10px] text-amber-300/80 mt-0.5">{selectedCompany?.name || "—"}</p></div></div><div className="grid grid-cols-1 lg:grid-cols-2 gap-2"><div><label className="block text-[10px] text-white/60 mb-1">{isAr ? "الحساب البنكي المختار" : "Selected bank account"}</label><select value={selectedBankAccountId} onChange={(e) => setSelectedBankAccountId(e.target.value)} className="w-full bg-black/60 border border-amber-500/30 text-white px-3 py-2 rounded-xl text-xs outline-none focus:border-amber-400"><option value="">{isAr ? "اختر الحساب البنكي" : "Select bank account"}</option>{bankAccounts.map(account => <option key={String(account.id)} value={String(account.id)}>{account.label}</option>)}</select>{bankAccounts.length === 0 && <p className="mt-2 text-[10px] text-rose-300">{isAr ? "لا توجد حسابات ظاهرة لهذه الشركة. تأكد من اختيار الشركة الصحيحة أو صلاحيات Odoo." : "No accounts are visible for this company."}</p>}</div><div><label className="block text-[10px] text-white/60 mb-1">{isAr ? "المورد / العميل" : "Vendor / Customer"}</label><select value={selectedPartnerId} onChange={(e) => setSelectedPartnerId(e.target.value)} disabled={loadingPartners || !selectedCompanyId} className="w-full bg-black/60 border border-amber-500/30 text-white px-3 py-2 rounded-xl text-xs outline-none focus:border-amber-400"><option value="">{loadingPartners ? (isAr ? "جاري تحميل العملاء والموردين..." : "Loading customers and vendors...") : (isAr ? "كل العملاء والموردين" : "All customers and vendors")}</option>{partners.map(partner => <option key={String(partner.id)} value={String(partner.id)}>{partner.label}</option>)}</select>{partners.length === 0 && !loadingPartners && <p className="mt-2 text-[10px] text-amber-300/80">{isAr ? "لم يتم العثور على عملاء أو موردين لهذه الشركة." : "No customers or vendors were found for this company."}</p>}</div></div></div><button onClick={handleBankMatch} disabled={!file || !selectedCompanyId || !selectedBankAccountId || matching} className="md:w-64 bg-gradient-to-r from-amber-500 to-yellow-600 hover:from-amber-600 hover:to-yellow-700 disabled:opacity-40 text-black font-extrabold py-3 rounded-xl text-sm flex items-center justify-center gap-2 shadow-lg shadow-amber-500/10">{matching ? <><span className="w-4 h-4 border-2 border-black border-t-transparent rounded-full animate-spin" /> {isAr ? "جاري المطابقة..." : "Matching..."}</> : <>🔁 {isAr ? "مطابقة بنكية" : "Run match"}</>}</button></div>{errorMsg && <div className="mt-3 bg-red-500/10 border border-red-500/30 p-3 rounded-xl text-red-300 text-xs">❌ {errorMsg}</div>}</div>
        <div className="flex justify-between items-center px-1 text-[11px] text-white/40"><span>{isAr ? "تم استخراج" : "Extracted"} <span className="gold-text font-bold">{statementRows.length}</span> {isAr ? "عملية من الكشف" : "statement rows"}</span><span className="cursor-pointer hover:text-white/70 transition-colors" onClick={() => { setResult(null); setFile(null); setMatchAttempted(false); }}>↩ {isAr ? "ملف جديد" : "New file"}</span></div>
        <div className="flex-1 min-h-0 wood-panel rounded-xl overflow-hidden flex flex-col"><div className="p-3 border-b border-white/10 flex items-center justify-between gap-2 flex-wrap"><div><h3 className="text-sm font-bold gold-text">{matchAttempted ? (isAr ? "نتائج التسوية البنكية" : "Bank reconciliation results") : (isAr ? "جدول حركة الحساب البنكي" : "Bank statement table")}</h3><p className="text-[10px] text-amber-400/70 mt-0.5">{matchAttempted ? (isAr ? "اضغط على بطاقات النتائج لفتح تفاصيلها ومعالجتها." : "Click result cards to open their details and processing actions.") : (isAr ? "بعد التأكد من قراءة الكشف، اختر الحساب البنكي والمورد أو العميل واضغط مطابقة بنكية." : "After checking the parsed statement, choose the account and customer/vendor, then run matching.")}</p></div></div><div className="flex-1 overflow-auto p-3">{matchAttempted ? <ReconciliationResultsPanel result={result} isAr={isAr} /> : <BankStatementTable rows={statementRows} isAr={isAr} />}</div></div>
      </div>}
    </div>
  );
}
