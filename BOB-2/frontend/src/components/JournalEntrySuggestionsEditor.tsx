"use client";

import { useEffect, useMemo, useState } from "react";
import { API_BASE_URL } from "@/lib/api";

const DEFAULT_BANK_CODE = "101003";
const DEFAULT_BANK_LABEL = "101003 Riyad Bank-3303280259941";

type PanelMode = "full" | "window" | "minimized";

type PostStatus = "idle" | "posting" | "success" | "error";

interface Transaction {
  date: string;
  description: string;
  main_description?: string;
  details?: string[];
  amount: number;
  debit?: number | null;
  credit?: number | null;
  row_number?: number;
  ai_suggested_account?: string;
}

interface LookupOption {
  id?: number | string;
  code?: string;
  name: string;
  type?: string;
  label: string;
}

interface EditableLine {
  account: string;
  description: string;
  partner: string;
  analytic: string;
  debit: number;
  credit: number;
}

interface EntryDraft {
  id: string;
  txn: Transaction;
  journalId: string;
  journalType: string;
  lines: EditableLine[];
  status: PostStatus;
  message: string;
  moveName?: string;
}

function fmt(value?: number | null) {
  return Number(value || 0).toLocaleString("en-SA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function clean(value?: string) {
  return (value || "")
    .toLowerCase()
    .replace(/[أإآ]/g, "ا")
    .replace(/ى/g, "ي")
    .replace(/ة/g, "ه")
    .replace(/[\-_/.,:;()\[\]{}]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function getSelectedCompanyId() {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem("selectedCompanyId");
  const n = raw ? Number(raw) : NaN;
  return Number.isFinite(n) && n > 0 ? n : null;
}

function asOptions(data: any): LookupOption[] {
  const arr = Array.isArray(data) ? data : data?.accounts || data?.partners || data?.journals || data?.analytic_accounts || data?.analyticAccounts || [];
  return arr
    .map((x: any) => ({
      id: x.id,
      code: x.code || "",
      name: x.name || x.display_name || "",
      type: x.type || x.account_type || "",
      label: `${x.code || ""} ${x.name || x.display_name || ""}${x.type ? ` (${x.type})` : ""}${x.vat ? ` - ${x.vat}` : ""}`.trim(),
    }))
    .filter((x: LookupOption) => x.label);
}

function optionByLabel(options: LookupOption[], value: string) {
  const v = clean(value);
  return (
    options.find(o => clean(o.label) === v) ||
    options.find(o => o.code && clean(value).startsWith(clean(String(o.code)))) ||
    options.find(o => clean(o.name).includes(v) || v.includes(clean(o.name)))
  );
}

function defaultBankAccount(accounts: LookupOption[]) {
  return (
    accounts.find(a => String(a.code) === DEFAULT_BANK_CODE)?.label ||
    accounts.find(a => /101003.*riyad|riyad.*3303280259941|3303280259941|رياض.*3303280259941/i.test(`${a.code} ${a.name} ${a.label}`))?.label ||
    DEFAULT_BANK_LABEL
  );
}

function isDeposit(txn: Transaction) {
  return Number(txn.amount || 0) > 0 || (Number(txn.credit || 0) > 0 && Number(txn.debit || 0) === 0);
}

function rawTxnText(txn: Transaction) {
  return `${txn.main_description || ""} ${txn.description || ""} ${(txn.details || []).join(" ")} ${txn.ai_suggested_account || ""}`;
}

function cleanTransactionDescription(txn: Transaction) {
  let text = rawTxnText(txn);
  text = text.replace(/\b(pos|mada|visa|mastercard|card|settlement|payment|transfer|debit|credit|sar|riyad bank|bank|swift|iban|fee|fees|ref|reference|txn|transaction)\b/gi, " ");
  text = text.replace(/\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b/g, " ");
  text = text.replace(/\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b/g, " ");
  text = text.replace(/[|~!@#$%^*_=+<>?؛،]/g, " ");
  text = text.replace(/\s+/g, " ").trim();
  const accountMatch = rawTxnText(txn).match(/(?:acc(?:ount)?|iban|acct|حساب)\s*[:#-]?\s*([A-Z0-9]{5,34})/i);
  const compact = text.split(" ").filter(token => token.length > 1).slice(0, 8).join(" ");
  if (accountMatch?.[1] && compact) return `${compact} - ${accountMatch[1]}`;
  return compact || txn.main_description || txn.description || "عملية من كشف البنك";
}

function termsFor(text: string) {
  const t = clean(text);
  if (/رسوم|عموله|charge|fee|commission/.test(t)) return ["مصروفات بنكية", "رسوم", "bank", "fee"];
  if (/راتب|رواتب|salary|payroll|wps/.test(t)) return ["رواتب", "اجور", "salary", "payroll"];
  if (/مورد|vendor|supplier|فاتوره|bill|purchase|سداد|sadad/.test(t)) return ["مورد", "موردون", "payable", "supplier", "vendor"];
  if (/عميل|customer|client|تحصيل|ايراد|receipt|deposit|ايداع|pos/.test(t)) return ["عميل", "عملاء", "receivable", "revenue", "customer", "settlement"];
  if (/ضريبه|vat|tax|زكاه|زكاة/.test(t)) return ["ضريبة", "vat", "tax", "زكاة"];
  if (/ايجار|rent|lease/.test(t)) return ["ايجار", "rent", "lease"];
  return ["تسوية", "وسيط", "suspense", "clearing", "related"];
}

function scoreOption(option: LookupOption, txText: string, extraTerms: string[] = []) {
  const label = clean(option.label);
  const text = clean(txText);
  let score = 0;
  [...termsFor(txText), ...extraTerms].forEach(term => {
    const t = clean(term);
    if (t && label.includes(t)) score += 12;
  });
  text.split(" ").filter(t => t.length > 3).forEach(t => {
    if (label.includes(t)) score += 2;
  });
  return score;
}

function bestOption(options: LookupOption[], txText: string, extraTerms: string[] = []) {
  let best: LookupOption | undefined;
  let bestScore = 0;
  options.forEach(option => {
    const sc = scoreOption(option, txText, extraTerms);
    if (sc > bestScore) {
      best = option;
      bestScore = sc;
    }
  });
  return bestScore >= 6 ? best : undefined;
}

function chooseDefaultJournal(journals: LookupOption[]) {
  return journals.find(j => j.type === "bank") || journals.find(j => /bank|بنك|riyad|رياض/i.test(j.label)) || journals[0];
}

function chooseCounterAccount(accounts: LookupOption[], txn: Transaction) {
  return bestOption(accounts, rawTxnText(txn))?.label || accounts.find(a => /related parties|طرف|اطراف|settlement|clearing|suspense/i.test(a.label))?.label || accounts[0]?.label || "";
}

function buildLines(txn: Transaction, bankAccount: string, counterAccount: string, partner: string, analytic: string): EditableLine[] {
  const amount = Math.abs(Number(txn.amount || txn.credit || txn.debit || 0));
  const description = cleanTransactionDescription(txn);
  const bankLine: EditableLine = { account: bankAccount, description, partner, analytic, debit: isDeposit(txn) ? amount : 0, credit: isDeposit(txn) ? 0 : amount };
  const counterLine: EditableLine = { account: counterAccount, description, partner, analytic, debit: isDeposit(txn) ? 0 : amount, credit: isDeposit(txn) ? amount : 0 };
  return isDeposit(txn) ? [bankLine, counterLine] : [counterLine, bankLine];
}

function getUploadedStatementFile() {
  if (typeof document === "undefined") return null;
  const input = document.querySelector('input[type="file"]') as HTMLInputElement | null;
  return input?.files?.[0] || null;
}

function escapeHtml(v: string) {
  return String(v || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\"/g, "&quot;");
}

function evidenceHtml(entry: EntryDraft, journalLabel: string, originalName: string) {
  const txn = entry.txn;
  const amount = Math.abs(Number(txn.amount || txn.credit || txn.debit || 0));
  return `<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"/><title>Bank Statement Evidence + Journal Entry</title><style>@media print{.page{page-break-after:always}}body{font-family:Arial,Tahoma,sans-serif;padding:24px;color:#111}.box{border:1px solid #ddd;border-radius:10px;padding:14px;margin:12px 0}.highlight{background:#fff176;border:3px solid #e53935;border-radius:6px;padding:4px 8px;font-weight:900;color:#b00020}table{width:100%;border-collapse:collapse;margin-top:12px}td,th{border:1px solid #ddd;padding:8px;text-align:right}.muted{color:#666;font-size:12px}.entry-title{background:#f5f5f5;padding:8px;border-radius:8px}</style></head><body><section class="page"><h1>المرفق: صفحة إثبات من كشف الحساب</h1><p class="muted">الملف الأصلي المرفوع: ${escapeHtml(originalName || "مرفق كشف البنك الأصلي إن كان متاحًا")}</p><p class="muted">Created move: ${escapeHtml(entry.moveName || "")}</p><div class="box"><b>نوع القيد / Journal:</b> ${escapeHtml(journalLabel)}<br/><b>تاريخ العملية:</b> ${escapeHtml(txn.date || "")}<br/><b>الوصف بعد التنظيف:</b> ${escapeHtml(cleanTransactionDescription(txn))}<br/><b>المبلغ موضوع القيد:</b> <span class="highlight">${fmt(amount)} SAR</span></div><p>هذه الصفحة تمثل الورقة/الصفحة الخاصة بالمبلغ داخل كشف الحساب لأغراض الإثبات، مع تمييز المبلغ موضوع القيد.</p></section><section><h1 class="entry-title">قيد اليومية</h1><table><thead><tr><th>الحساب</th><th>الوصف</th><th>الشريك</th><th>الحساب التحليلي</th><th>مدين</th><th>دائن</th></tr></thead><tbody>${entry.lines.map(l => `<tr><td>${escapeHtml(l.account)}</td><td>${escapeHtml(l.description)}</td><td>${escapeHtml(l.partner)}</td><td>${escapeHtml(l.analytic)}</td><td>${l.debit ? fmt(l.debit) : "—"}</td><td>${l.credit ? fmt(l.credit) : "—"}</td></tr>`).join("")}</tbody></table></section></body></html>`;
}

function printHtml(html: string) {
  const frame = document.createElement("iframe");
  frame.style.position = "fixed";
  frame.style.width = "0";
  frame.style.height = "0";
  frame.style.border = "0";
  document.body.appendChild(frame);
  const doc = frame.contentWindow?.document;
  if (!doc) return;
  doc.open();
  doc.write(html);
  doc.close();
  setTimeout(() => {
    frame.contentWindow?.focus();
    frame.contentWindow?.print();
    setTimeout(() => frame.remove(), 1200);
  }, 350);
}

async function attachToMove(moveId: number, file: File) {
  const form = new FormData();
  form.append("move_id", String(moveId));
  form.append("file", file);
  const res = await fetch(`${API_BASE_URL}/api/v1/erp/attach-document`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export default function JournalEntrySuggestionsEditor({ rows, isAr }: { rows: Transaction[]; isAr: boolean; bankAccountLabel?: string }) {
  const [mode, setMode] = useState<PanelMode>("full");
  const [autoPrint, setAutoPrint] = useState(true);
  const [attachOriginal, setAttachOriginal] = useState(true);
  const [accounts, setAccounts] = useState<LookupOption[]>([]);
  const [partners, setPartners] = useState<LookupOption[]>([]);
  const [analytics, setAnalytics] = useState<LookupOption[]>([]);
  const [journals, setJournals] = useState<LookupOption[]>([]);
  const [defaultJournalId, setDefaultJournalId] = useState("");
  const [defaultBank, setDefaultBank] = useState(DEFAULT_BANK_LABEL);
  const [defaultCounter, setDefaultCounter] = useState("");
  const [defaultPartner, setDefaultPartner] = useState("");
  const [defaultAnalytic, setDefaultAnalytic] = useState("");
  const [drafts, setDrafts] = useState<EntryDraft[]>([]);
  const [busyAll, setBusyAll] = useState(false);

  useEffect(() => {
    const savedPrint = localStorage.getItem("reconciliation_auto_print");
    if (savedPrint) setAutoPrint(savedPrint === "on");
  }, []);

  useEffect(() => {
    let alive = true;
    async function loadLookups() {
      const companyId = getSelectedCompanyId();
      const qs = companyId ? `?company_id=${companyId}` : "";
      try {
        const [accRes, partnerRes, analyticRes, journalRes] = await Promise.all([
          fetch(`${API_BASE_URL}/api/v1/erp/accounts${qs}`),
          fetch(`${API_BASE_URL}/api/v1/erp/partners${qs}`),
          fetch(`${API_BASE_URL}/api/v1/erp/analytic-accounts${qs}`),
          fetch(`${API_BASE_URL}/api/v1/erp/journals${qs}`),
        ]);
        const acc = accRes.ok ? asOptions(await accRes.json()) : [];
        const prt = partnerRes.ok ? asOptions(await partnerRes.json()) : [];
        const anl = analyticRes.ok ? asOptions(await analyticRes.json()) : [];
        const jrn = journalRes.ok ? asOptions(await journalRes.json()) : [];
        if (!alive) return;
        setAccounts(acc);
        setPartners(prt);
        setAnalytics(anl);
        setJournals(jrn);
        const bank = defaultBankAccount(acc);
        const journal = chooseDefaultJournal(jrn);
        setDefaultBank(bank);
        setDefaultJournalId(journal?.id ? String(journal.id) : "");
        setDefaultCounter(rows[0] ? chooseCounterAccount(acc, rows[0]) : acc[0]?.label || "");
      } catch (err) {
        console.warn("Failed to load posting lookups", err);
      }
    }
    loadLookups();
    return () => { alive = false; };
  }, [rows]);

  useEffect(() => {
    if (!accounts.length && !defaultCounter) return;
    setDrafts(rows.map((txn, index) => {
      const counter = chooseCounterAccount(accounts, txn) || defaultCounter;
      const partner = bestOption(partners, rawTxnText(txn))?.label || defaultPartner;
      const analytic = bestOption(analytics, rawTxnText(txn))?.label || defaultAnalytic;
      return {
        id: `${txn.row_number || index}-${txn.date}-${txn.amount}`,
        txn,
        journalId: defaultJournalId,
        journalType: journals.find(j => String(j.id) === String(defaultJournalId))?.type || "bank",
        lines: buildLines(txn, defaultBank, counter, partner, analytic),
        status: "idle",
        message: "",
      };
    }));
  }, [rows, accounts, partners, analytics, journals, defaultJournalId, defaultBank, defaultCounter, defaultPartner, defaultAnalytic]);

  const accountList = "bulk-je-account-options";
  const partnerList = "bulk-je-partner-options";
  const analyticList = "bulk-je-analytic-options";

  const containerClass = mode === "full"
    ? "fixed inset-3 z-[9999] bg-[#050505] shadow-2xl"
    : mode === "window"
      ? "fixed inset-x-8 top-16 bottom-8 z-[9999] bg-[#050505] shadow-2xl"
      : "fixed bottom-4 left-4 right-4 z-[9999] bg-[#050505] shadow-2xl";

  const updateDraft = (id: string, patch: Partial<EntryDraft>) => {
    setDrafts(prev => prev.map(d => d.id === id ? { ...d, ...patch } : d));
  };

  const updateLine = (draftId: string, lineIndex: number, key: keyof EditableLine, value: string) => {
    setDrafts(prev => prev.map(d => d.id !== draftId ? d : { ...d, lines: d.lines.map((line, i) => i === lineIndex ? { ...line, [key]: value } : line) }));
  };

  const applyDefaults = () => {
    const journal = journals.find(j => String(j.id) === String(defaultJournalId));
    setDrafts(prev => prev.map(d => ({
      ...d,
      journalId: defaultJournalId,
      journalType: journal?.type || d.journalType || "bank",
      lines: buildLines(d.txn, defaultBank, defaultCounter || chooseCounterAccount(accounts, d.txn), defaultPartner, defaultAnalytic),
      status: "idle",
      message: "",
    })));
  };

  const buildPayloadLines = (draft: EntryDraft) => draft.lines.map(line => {
    const acc = optionByLabel(accounts, line.account);
    if (!acc?.id) throw new Error(isAr ? `الحساب غير موجود في أودو أو لا يتبع الشركة المختارة: ${line.account}` : `Account not found in Odoo: ${line.account}`);
    const partner = optionByLabel(partners, line.partner);
    const analytic = optionByLabel(analytics, line.analytic);
    return {
      account_id: Number(acc.id),
      account_name: acc.name || line.account,
      account_code: acc.code || "",
      debit: Number(line.debit || 0),
      credit: Number(line.credit || 0),
      name: line.description || cleanTransactionDescription(draft.txn),
      partner_id: partner?.id ? Number(partner.id) : null,
      partner_name: partner?.label || line.partner || "",
      analytic_account_id: analytic?.id ? Number(analytic.id) : null,
      analytic_account_name: analytic?.label || line.analytic || "",
    };
  });

  const postDraft = async (draft: EntryDraft) => {
    updateDraft(draft.id, { status: "posting", message: isAr ? "جاري الترحيل..." : "Posting..." });
    try {
      const journal = journals.find(j => String(j.id) === String(draft.journalId));
      const payloadLines = buildPayloadLines(draft);
      const res = await fetch(`${API_BASE_URL}/api/v1/erp/register-bank-reconciliation-entry-v2`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company_id: getSelectedCompanyId(),
          journal_id: draft.journalId ? Number(draft.journalId) : null,
          journal_type: draft.journalType || journal?.type || "bank",
          filename: "bank_statement_reconciliation.html",
          amount: Math.abs(Number(draft.txn.amount || 0)),
          date: draft.txn.date || "",
          ref: `Bank statement reconciliation ${draft.txn.date || ""}`,
          partner_name: draft.lines.find(l => l.partner)?.partner || "",
          lines: payloadLines,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
      const moveId = Number(data.move_id);
      const moveName = data.move_name || `MOVE-${moveId}`;
      const withMove = { ...draft, moveName };
      const original = getUploadedStatementFile();
      if (attachOriginal && original) await attachToMove(moveId, original);
      const html = evidenceHtml(withMove, journal?.label || data.journal_name || draft.journalType, original?.name || "");
      const evidence = new File([html], `bank-statement-evidence-and-journal-${moveId}.html`, { type: "text/html;charset=utf-8" });
      await attachToMove(moveId, evidence);
      if (autoPrint) printHtml(html);
      updateDraft(draft.id, { status: "success", moveName, message: isAr ? `تم الترحيل والإرفاق: ${moveName}` : `Posted and attached: ${moveName}` });
      return true;
    } catch (err: any) {
      updateDraft(draft.id, { status: "error", message: (isAr ? "فشل: " : "Failed: ") + (err.message || err) });
      return false;
    }
  };

  const postAll = async () => {
    setBusyAll(true);
    for (const draft of drafts) {
      const fresh = drafts.find(d => d.id === draft.id) || draft;
      if (fresh.status === "success") continue;
      await postDraft(fresh);
    }
    setBusyAll(false);
  };

  const statusClasses: Record<PostStatus, string> = {
    idle: "border-white/10 bg-white/5 text-white/50",
    posting: "border-amber-500/30 bg-amber-500/10 text-amber-300",
    success: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    error: "border-rose-500/30 bg-rose-500/10 text-rose-300",
  };

  if (mode === "minimized") {
    return <div className={`${containerClass} rounded-2xl border border-cyan-500/30 p-3 flex items-center justify-between`}><div><p className="font-bold text-cyan-300">🧾 {isAr ? "شاشة تسجيل القيود" : "Journal posting workspace"}</p><p className="text-[10px] text-white/50">{drafts.length} {isAr ? "قيد جاهز" : "draft entries"}</p></div><button onClick={() => setMode("full")} className="rounded-xl border border-cyan-500/40 bg-cyan-500/15 px-4 py-2 text-xs font-bold text-cyan-300">⤢ {isAr ? "فتح" : "Open"}</button></div>;
  }

  return <div className={`${containerClass} rounded-2xl border border-cyan-500/30 overflow-hidden flex flex-col`}>
    <datalist id={accountList}>{accounts.map((a, i) => <option key={i} value={a.label} />)}</datalist>
    <datalist id={partnerList}>{partners.map((p, i) => <option key={i} value={p.label} />)}</datalist>
    <datalist id={analyticList}>{analytics.map((a, i) => <option key={i} value={a.label} />)}</datalist>

    <div className="p-3 border-b border-white/10 flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3 bg-black/40">
      <div>
        <h3 className="text-lg font-extrabold text-cyan-300">🧾 {isAr ? "شاشة تسجيل العمليات في الحسابات" : "Journal posting workspace"}</h3>
        <p className="text-[11px] text-white/55">{isAr ? "كل الاقتراحات تأتي من بيانات أودو للشركة المختارة: Journals، الحسابات، الشركاء، الحسابات التحليلية." : "Suggestions come from the selected company's Odoo data: journals, accounts, partners, and analytic accounts."}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <button onClick={() => setMode("full")} className="rounded-lg border border-cyan-500/40 bg-cyan-500/15 px-3 py-1.5 text-xs font-bold text-cyan-300">⛶ {isAr ? "تكبير" : "Full"}</button>
        <button onClick={() => setMode("window")} className="rounded-lg border border-amber-500/40 bg-amber-500/15 px-3 py-1.5 text-xs font-bold text-amber-300">▣ {isAr ? "تصغير" : "Window"}</button>
        <button onClick={() => setMode("minimized")} className="rounded-lg border border-white/20 bg-white/10 px-3 py-1.5 text-xs font-bold text-white/70">▁ {isAr ? "إنزال" : "Minimize"}</button>
      </div>
    </div>

    <div className="p-3 border-b border-white/10 bg-cyan-500/5 grid lg:grid-cols-6 md:grid-cols-3 grid-cols-1 gap-2">
      <div>
        <label className="block text-[10px] text-cyan-300 font-bold mb-1">{isAr ? "نوع القيد الافتراضي" : "Default Journal"}</label>
        <select value={defaultJournalId} onChange={e => setDefaultJournalId(e.target.value)} className="w-full rounded-lg border border-white/10 bg-black/50 px-2 py-2 text-xs text-white">
          <option value="">{isAr ? "اختر من أودو" : "Select from Odoo"}</option>
          {journals.map(j => <option key={String(j.id)} value={String(j.id)}>{j.label}</option>)}
        </select>
      </div>
      <div>
        <label className="block text-[10px] text-cyan-300 font-bold mb-1">{isAr ? "حساب البنك الافتراضي" : "Default Bank"}</label>
        <input list={accountList} value={defaultBank} onChange={e => setDefaultBank(e.target.value)} className="w-full rounded-lg border border-white/10 bg-black/50 px-2 py-2 text-xs text-white" />
      </div>
      <div>
        <label className="block text-[10px] text-cyan-300 font-bold mb-1">{isAr ? "الحساب المقابل الافتراضي" : "Default Counter"}</label>
        <input list={accountList} value={defaultCounter} onChange={e => setDefaultCounter(e.target.value)} className="w-full rounded-lg border border-white/10 bg-black/50 px-2 py-2 text-xs text-white" />
      </div>
      <div>
        <label className="block text-[10px] text-cyan-300 font-bold mb-1">{isAr ? "الشريك الافتراضي" : "Default Partner"}</label>
        <input list={partnerList} value={defaultPartner} onChange={e => setDefaultPartner(e.target.value)} className="w-full rounded-lg border border-white/10 bg-black/50 px-2 py-2 text-xs text-white" />
      </div>
      <div>
        <label className="block text-[10px] text-cyan-300 font-bold mb-1">{isAr ? "الحساب التحليلي الافتراضي" : "Default Analytic"}</label>
        <input list={analyticList} value={defaultAnalytic} onChange={e => setDefaultAnalytic(e.target.value)} className="w-full rounded-lg border border-white/10 bg-black/50 px-2 py-2 text-xs text-white" />
      </div>
      <div className="flex flex-col gap-2">
        <button onClick={applyDefaults} className="rounded-lg border border-amber-500/40 bg-amber-500/15 px-3 py-2 text-xs font-bold text-amber-300">⚙️ {isAr ? "تطبيق على كل القيود" : "Apply to all"}</button>
        <button onClick={postAll} disabled={busyAll || drafts.length === 0} className="rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-2 text-xs font-bold text-emerald-300 disabled:opacity-40">🚀 {busyAll ? (isAr ? "جاري تسجيل الكل..." : "Posting all...") : (isAr ? "تسجيل كل القيود دفعة واحدة" : "Post all entries")}</button>
      </div>
      <div className="lg:col-span-6 flex flex-wrap gap-2 text-[11px] text-white/60">
        <button onClick={() => { const next = !autoPrint; setAutoPrint(next); localStorage.setItem("reconciliation_auto_print", next ? "on" : "off"); }} className={`rounded-lg border px-3 py-1.5 font-bold ${autoPrint ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300" : "border-white/20 bg-black/30 text-white/50"}`}>🖨️ {isAr ? "الطباعة التلقائية" : "Auto print"}: {autoPrint ? (isAr ? "تشغيل" : "On") : (isAr ? "إيقاف" : "Off")}</button>
        <button onClick={() => setAttachOriginal(v => !v)} className={`rounded-lg border px-3 py-1.5 font-bold ${attachOriginal ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300" : "border-white/20 bg-black/30 text-white/50"}`}>📎 {isAr ? "إرفاق كشف البنك الأصلي" : "Attach original statement"}: {attachOriginal ? (isAr ? "تشغيل" : "On") : (isAr ? "إيقاف" : "Off")}</button>
      </div>
    </div>

    <div className="flex-1 min-h-0 overflow-auto p-3 space-y-3">
      {drafts.map((draft, draftIndex) => {
        const journal = journals.find(j => String(j.id) === String(draft.journalId));
        return <div key={draft.id} className="rounded-xl border border-white/10 bg-black/25 p-3 space-y-3">
          <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-3">
            <div>
              <p className="text-sm font-bold text-cyan-300">#{draftIndex + 1} — {draft.txn.date} — {cleanTransactionDescription(draft.txn)}</p>
              <p className="font-mono text-amber-300 font-bold">{fmt(Math.abs(Number(draft.txn.amount || 0)))} SAR</p>
            </div>
            <div className="grid md:grid-cols-2 gap-2 lg:w-[560px]">
              <div>
                <label className="block text-[10px] text-amber-300 font-bold mb-1">{isAr ? "نوع القيد / Journal Type" : "Journal Type"}</label>
                <select value={draft.journalId} onChange={e => { const j = journals.find(x => String(x.id) === e.target.value); updateDraft(draft.id, { journalId: e.target.value, journalType: j?.type || draft.journalType }); }} className="w-full rounded-lg border border-amber-500/30 bg-black/50 px-2 py-2 text-xs text-white">
                  <option value="">{isAr ? "اختر Journal من أودو" : "Select Odoo Journal"}</option>
                  {journals.map(j => <option key={String(j.id)} value={String(j.id)}>{j.label}</option>)}
                </select>
              </div>
              <button onClick={() => postDraft(draft)} disabled={draft.status === "posting"} className="self-end rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-2 text-xs font-bold text-emerald-300 disabled:opacity-40">🚀 {draft.status === "posting" ? (isAr ? "جاري التسجيل..." : "Posting...") : (isAr ? "تسجيل هذا القيد فقط" : "Post this entry")}</button>
            </div>
          </div>
          <div className="overflow-auto rounded-lg border border-white/10">
            <table className="w-full min-w-[1100px] text-[10px]">
              <thead className="bg-white/5 text-white/60"><tr><th className="p-2 text-right">{isAr ? "الحساب" : "Account"}</th><th className="p-2 text-right">{isAr ? "الوصف النظيف" : "Clean description"}</th><th className="p-2 text-right">{isAr ? "الشريك" : "Partner"}</th><th className="p-2 text-right">{isAr ? "الحساب التحليلي" : "Analytic"}</th><th className="p-2 text-center">{isAr ? "مدين" : "Debit"}</th><th className="p-2 text-center">{isAr ? "دائن" : "Credit"}</th></tr></thead>
              <tbody>{draft.lines.map((line, i) => <tr key={i} className="border-t border-white/5"><td className="p-2"><input list={accountList} value={line.account} onChange={e => updateLine(draft.id, i, "account", e.target.value)} className="w-full rounded bg-black/40 border border-white/10 px-2 py-1 text-white outline-none focus:border-cyan-400" /></td><td className="p-2"><input value={line.description} onChange={e => updateLine(draft.id, i, "description", e.target.value)} className="w-full rounded bg-black/40 border border-white/10 px-2 py-1 text-white outline-none focus:border-cyan-400" /></td><td className="p-2"><input list={partnerList} value={line.partner} onChange={e => updateLine(draft.id, i, "partner", e.target.value)} className="w-full rounded bg-black/40 border border-white/10 px-2 py-1 text-white outline-none focus:border-purple-400" /></td><td className="p-2"><input list={analyticList} value={line.analytic} onChange={e => updateLine(draft.id, i, "analytic", e.target.value)} className="w-full rounded bg-black/40 border border-white/10 px-2 py-1 text-white outline-none focus:border-amber-400" /></td><td className="p-2 text-center font-mono text-emerald-300">{line.debit ? fmt(line.debit) : "—"}</td><td className="p-2 text-center font-mono text-rose-300">{line.credit ? fmt(line.credit) : "—"}</td></tr>)}</tbody>
            </table>
          </div>
          <div className={`rounded-lg border p-2 text-[10px] ${statusClasses[draft.status]}`}>{draft.message || (isAr ? `جاهز للتسجيل على: ${journal?.label || "Journal من أودو"}` : `Ready to post to: ${journal?.label || "Odoo journal"}`)}</div>
        </div>;
      })}
    </div>
  </div>;
}
