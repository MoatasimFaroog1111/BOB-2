"use client";

import { useEffect, useMemo, useState } from "react";
import { API_BASE_URL } from "@/lib/api";

interface Transaction {
  date: string;
  description: string;
  main_description?: string;
  details?: string[];
  amount: number;
  debit?: number | null;
  credit?: number | null;
  row_number: number;
  suggested_action?: string;
  suggested_action_label?: string;
  confidence?: number;
  explanation?: string;
  detected_category?: string;
  ai_suggested_account?: string;
  bank_rule_suggestion?: HistoricalSuggestion;
  historical_suggestion?: HistoricalSuggestion;
}

interface Props {
  rows: Transaction[];
  isAr: boolean;
  bankAccountLabel?: string;
  companyId?: number | string | null;
  bankJournalId?: number | string | null;
  bankAccountId?: number | string | null;
}

interface LookupOption {
  id?: number | string;
  code?: string;
  name: string;
  type?: string;
  label: string;
}

interface HistoricalSuggestion {
  row_number?: number | null;
  date?: string;
  amount?: number;
  suggested_account_id?: number | null;
  suggested_account_label?: string;
  suggested_partner_id?: number | null;
  suggested_partner_label?: string;
  suggested_analytic_account_id?: number | null;
  suggested_analytic_account_label?: string;
  confidence?: number;
  reason?: string;
  historical_move_name?: string;
  historical_date?: string;
  needs_review?: boolean;
  source?: string;
}

interface SuggestedRow extends Transaction {
  suggested_account_label?: string;
  suggested_partner_label?: string;
  suggested_analytic_account_label?: string;
  suggestion_confidence?: number;
  suggestion_reason?: string;
  suggestion_source?: string;
  suggestion_needs_review?: boolean;
}

interface BankRuleLine {
  account_id?: [number, string] | number | null;
  partner_id?: [number, string] | number | null;
  analytic_account_id?: [number, string] | number | null;
  label?: string;
  name?: string;
}

interface BankRule {
  id?: number;
  name?: string;
  match_label_param?: string;
  match_note_param?: string;
  match_transaction_type?: string;
  match_amount_min?: number | string | null;
  match_amount_max?: number | string | null;
  lines?: BankRuleLine[];
}

function selectedCompanyFromStorage() {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem("selectedCompanyId");
  const parsed = raw ? Number(raw) : NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function keyFor(row: Pick<Transaction, "row_number" | "date" | "amount">) {
  return `${row.row_number ?? ""}|${row.date || ""}|${Number(row.amount || 0).toFixed(2)}`;
}

function fmt(value?: number | null) {
  return Number(value || 0).toLocaleString("en-SA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pct(value?: number) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function m2o(value: any): { id?: number; label?: string } {
  if (Array.isArray(value) && value.length) return { id: Number(value[0]), label: String(value[1] || "") };
  if (typeof value === "number") return { id: value, label: "" };
  return {};
}

function norm(value: any) {
  return String(value || "")
    .toLowerCase()
    .replace(/[أإآ]/g, "ا")
    .replace(/ى/g, "ي")
    .replace(/ة/g, "ه")
    .replace(/[\u064B-\u065F\u0670]/g, "")
    .replace(/\b(ref|reference|txn|transaction|date|time|sar|vat|iban|swift|mada|visa|card|bank)\b/g, " ")
    .replace(/[^\w\u0600-\u06FF]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function category(text: string) {
  const t = norm(text);
  if (/رسوم|عموله|عمولة|fee|charge|commission/.test(t)) return "bank_fees";
  if (/راتب|رواتب|salary|payroll|wps/.test(t)) return "payroll";
  if (/ضريبه|ضريبة|زكاه|زكاة|vat|tax/.test(t)) return "tax";
  if (/سداد|sadad|bill|فاتوره|فاتورة|mol|government/.test(t)) return "bill_payment";
  if (/تحويل|transfer|instant payment/.test(t)) return "transfer";
  if (/pos|شبكه|شبكة|مدي|مدى|settlement/.test(t)) return "pos_settlement";
  return "general";
}

function similarity(a: string, b: string) {
  const left = norm(a);
  const right = norm(b);
  if (!left || !right) return 0;
  const leftTokens = new Set(left.split(" ").filter(x => x.length > 2));
  const rightTokens = new Set(right.split(" ").filter(x => x.length > 2));
  const intersection = [...leftTokens].filter(x => rightTokens.has(x)).length;
  const union = new Set([...leftTokens, ...rightTokens]).size || 1;
  return intersection / union;
}

function firstRuleLine(rule: BankRule) {
  return (rule.lines || []).find(line => m2o(line.account_id).id);
}

function amountOk(rule: BankRule, amount: number) {
  const value = Math.abs(Number(amount || 0));
  const min = rule.match_amount_min !== undefined && rule.match_amount_min !== null && rule.match_amount_min !== "" ? Math.abs(Number(rule.match_amount_min)) : null;
  const max = rule.match_amount_max !== undefined && rule.match_amount_max !== null && rule.match_amount_max !== "" ? Math.abs(Number(rule.match_amount_max)) : null;
  if (min === null && max === null) return 0.45;
  if (min !== null && value < min) return 0;
  if (max !== null && value > max) return 0;
  return 1;
}

function ruleText(rule: BankRule) {
  const line = firstRuleLine(rule);
  const account = m2o(line?.account_id).label || "";
  const partner = m2o(line?.partner_id).label || "";
  return [rule.name, rule.match_label_param, rule.match_note_param, rule.match_transaction_type, line?.label, line?.name, account, partner].filter(Boolean).join(" ");
}

function matchBankRule(row: Transaction, rules: BankRule[]): HistoricalSuggestion | null {
  const text = [row.description, row.main_description, ...(row.details || []), row.suggested_action_label, row.explanation, row.detected_category].filter(Boolean).join(" ");
  const rowCategory = category(text);
  let best: { score: number; rule: BankRule; line: BankRuleLine } | null = null;

  for (const rule of rules) {
    const line = firstRuleLine(rule);
    if (!line) continue;
    const rt = ruleText(rule);
    const labelHit = norm(rule.match_label_param) && norm(text).includes(norm(rule.match_label_param)) ? 1 : 0;
    const noteHit = norm(rule.match_note_param) && norm(text).includes(norm(rule.match_note_param)) ? 1 : 0;
    const textScore = Math.max(labelHit, noteHit, similarity(text, rt));
    const categoryScore = rowCategory !== "general" && rowCategory === category(rt) ? 1 : 0;
    const score = Math.min(textScore * 0.62 + categoryScore * 0.18 + amountOk(rule, row.amount) * 0.2, 1);
    if (!best || score > best.score) best = { score, rule, line };
  }

  if (!best || best.score < 0.42) return null;
  const account = m2o(best.line.account_id);
  const partner = m2o(best.line.partner_id);
  const analytic = m2o(best.line.analytic_account_id);
  return {
    row_number: row.row_number,
    date: row.date,
    amount: row.amount,
    suggested_account_id: account.id || null,
    suggested_account_label: account.label || "",
    suggested_partner_id: partner.id || null,
    suggested_partner_label: partner.label || "",
    suggested_analytic_account_id: analytic.id || null,
    suggested_analytic_account_label: analytic.label || "",
    confidence: best.score,
    reason: `Matched Odoo bank rule ${best.rule.name || best.rule.id}`,
    source: "odoo_bank_reconciliation_rule",
    needs_review: best.score < 0.7,
  };
}

function asOptions(data: any): LookupOption[] {
  const arr = Array.isArray(data) ? data : data?.accounts || data?.partners || data?.journals || data?.analytic_accounts || data?.analyticAccounts || data?.items || [];
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

function applySuggestion(row: Transaction, item: HistoricalSuggestion | null): SuggestedRow {
  return {
    ...row,
    suggested_account_label: item?.suggested_account_label || row.ai_suggested_account || "",
    suggested_partner_label: item?.suggested_partner_label || "",
    suggested_analytic_account_label: item?.suggested_analytic_account_label || "",
    suggestion_confidence: Number(item?.confidence || row.confidence || 0),
    suggestion_reason: item?.reason || row.explanation || "",
    suggestion_source: item?.source || "ai_statement_suggestion",
    suggestion_needs_review: item?.needs_review ?? true,
    bank_rule_suggestion: item?.source === "odoo_bank_reconciliation_rule" ? item : row.bank_rule_suggestion,
    historical_suggestion: item?.source === "odoo_bank_reconciliation_rule" ? row.historical_suggestion : item || row.historical_suggestion,
  };
}

export default function HistoricalJournalEntrySuggestionsEditor({ rows, isAr, companyId, bankJournalId, bankAccountId }: Props) {
  const [suggestedRows, setSuggestedRows] = useState<SuggestedRow[]>(rows);
  const [accounts, setAccounts] = useState<LookupOption[]>([]);
  const [partners, setPartners] = useState<LookupOption[]>([]);
  const [analytics, setAnalytics] = useState<LookupOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const effectiveCompanyId = companyId || selectedCompanyFromStorage();

  const payload = useMemo(() => ({
    transactions: rows,
    company_id: effectiveCompanyId || null,
    bank_journal_id: bankJournalId ? Number(bankJournalId) : null,
    bank_account_id: bankAccountId ? Number(bankAccountId) : null,
    history_limit: 600,
  }), [rows, effectiveCompanyId, bankJournalId, bankAccountId]);

  useEffect(() => {
    let alive = true;
    async function loadSuggestions() {
      if (!rows.length) {
        setSuggestedRows([]);
        return;
      }
      setLoading(true);
      setError("");
      setNotice("");
      try {
        const params = new URLSearchParams();
        if (effectiveCompanyId) params.set("company_id", String(effectiveCompanyId));
        if (bankJournalId) params.set("bank_journal_id", String(bankJournalId));
        const qs = effectiveCompanyId ? `?company_id=${effectiveCompanyId}` : "";

        const [accountsResponse, partnersResponse, analyticsResponse, rulesResponse, historyResponse] = await Promise.all([
          fetch(`${API_BASE_URL}/api/v1/erp/accounts${qs}`),
          fetch(`${API_BASE_URL}/api/v1/erp/partners${qs}`),
          fetch(`${API_BASE_URL}/api/v1/erp/analytic-accounts${qs}`),
          fetch(`${API_BASE_URL}/api/v1/erp/bank-reconciliation/bank-rules?${params.toString()}`),
          fetch(`${API_BASE_URL}/api/v1/erp/bank-reconciliation/entry-suggestions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          }),
        ]);

        const accountsData = await accountsResponse.json().catch(() => null);
        const partnersData = await partnersResponse.json().catch(() => null);
        const analyticsData = await analyticsResponse.json().catch(() => null);
        const rulesData = await rulesResponse.json().catch(() => null);
        const historyData = await historyResponse.json().catch(() => null);
        const rules: BankRule[] = rulesResponse.ok && Array.isArray(rulesData?.items) ? rulesData.items : [];
        if (!historyResponse.ok) throw new Error(historyData?.detail || `Error ${historyResponse.status}`);

        const historySuggestions = new Map<string, HistoricalSuggestion>();
        (Array.isArray(historyData?.items) ? historyData.items : []).forEach((item: HistoricalSuggestion) => {
          historySuggestions.set(keyFor({ row_number: item.row_number ?? null, date: item.date || "", amount: Number(item.amount || 0) }), item);
        });

        const nextRows = rows.map((row) => {
          const ruleItem = matchBankRule(row, rules);
          if (ruleItem?.suggested_account_label) return applySuggestion(row, ruleItem);
          return applySuggestion(row, historySuggestions.get(keyFor(row)) || null);
        });

        if (!alive) return;
        setAccounts(accountsResponse.ok ? asOptions(accountsData) : []);
        setPartners(partnersResponse.ok ? asOptions(partnersData) : []);
        setAnalytics(analyticsResponse.ok ? asOptions(analyticsData) : []);
        setSuggestedRows(nextRows);
        const ruleCount = nextRows.filter(r => r.suggestion_source === "odoo_bank_reconciliation_rule").length;
        const suggestedCount = nextRows.filter(r => r.suggested_account_label || r.suggested_partner_label).length;
        setNotice(isAr
          ? `تم إنشاء اقتراحات للحسابات والشركاء أمام ${suggestedCount} عملية. قواعد البنك: ${ruleCount}.`
          : `Account and partner suggestions were prepared for ${suggestedCount} rows. Bank rules: ${ruleCount}.`);
      } catch (err: any) {
        if (!alive) return;
        setSuggestedRows(rows.map(row => applySuggestion(row, null)));
        setError((isAr ? "تعذر قراءة قواعد البنك أو البيانات التاريخية: " : "Could not read bank rules or history: ") + (err?.message || err));
      } finally {
        if (alive) setLoading(false);
      }
    }
    loadSuggestions();
    return () => { alive = false; };
  }, [payload, rows, isAr, effectiveCompanyId, bankJournalId]);

  const accountList = "inline-odoo-account-suggestions";
  const partnerList = "inline-odoo-partner-suggestions";
  const analyticList = "inline-odoo-analytic-suggestions";

  const updateSuggestedRow = (index: number, patch: Partial<SuggestedRow>) => {
    setSuggestedRows(prev => prev.map((row, i) => i === index ? { ...row, ...patch } : row));
  };

  if (!rows.length) {
    return <p className="p-6 text-center text-gray-500">{isAr ? "لا توجد عمليات تحتاج اقتراحات." : "No rows need suggestions."}</p>;
  }

  return (
    <div className="space-y-3">
      <datalist id={accountList}>{accounts.map((account, index) => <option key={index} value={account.label} />)}</datalist>
      <datalist id={partnerList}>{partners.map((partner, index) => <option key={index} value={partner.label} />)}</datalist>
      <datalist id={analyticList}>{analytics.map((analytic, index) => <option key={index} value={analytic.label} />)}</datalist>

      <div className="rounded-xl border border-cyan-500/25 bg-cyan-500/10 px-4 py-3">
        <p className="text-sm font-bold text-cyan-200">{isAr ? "اقتراحات AI للحسابات والشركاء" : "AI account and partner suggestions"}</p>
        <p className="mt-1 text-[11px] text-white/60">
          {isAr
            ? "كل صف يعرض الحساب المقترح والشريك المقترح مباشرة أمام العملية. يمكن تعديل القيم يدويًا من بيانات أودو للشركة المختارة. لا يوجد ترحيل من هذه الشاشة."
            : "Each row shows the suggested account and partner inline. Values are editable from the selected company's Odoo data. This screen does not post journal entries."}
        </p>
      </div>

      {(loading || notice || error) && (
        <div className="flex flex-wrap gap-2 text-[11px]">
          {loading && <span className="rounded-lg border border-cyan-500/40 bg-cyan-500/15 px-3 py-1.5 font-bold text-cyan-200">{isAr ? "جاري تجهيز الاقتراحات من أودو..." : "Preparing suggestions from Odoo..."}</span>}
          {notice && <span className="rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-1.5 font-bold text-emerald-200">{notice}</span>}
          {error && <span className="rounded-lg border border-amber-500/40 bg-amber-500/15 px-3 py-1.5 font-bold text-amber-200">{error}</span>}
        </div>
      )}

      <div className="overflow-auto rounded-xl border border-white/10 bg-black/20">
        <table className="w-full min-w-[1280px] text-[11px]">
          <thead className="bg-white/5 text-white/60">
            <tr className="border-b border-white/10">
              <th className="px-3 py-2 text-center">#</th>
              <th className="px-3 py-2 text-start">{isAr ? "التاريخ" : "Date"}</th>
              <th className="px-3 py-2 text-start min-w-[300px]">{isAr ? "البيان / الوصف" : "Statement description"}</th>
              <th className="px-3 py-2 text-end">{isAr ? "المبلغ" : "Amount"}</th>
              <th className="px-3 py-2 text-start min-w-[260px]">{isAr ? "الحساب المقترح" : "Suggested account"}</th>
              <th className="px-3 py-2 text-start min-w-[220px]">{isAr ? "الشريك المقترح" : "Suggested partner"}</th>
              <th className="px-3 py-2 text-start min-w-[220px]">{isAr ? "الحساب التحليلي" : "Analytic account"}</th>
              <th className="px-3 py-2 text-center">{isAr ? "الثقة" : "Confidence"}</th>
              <th className="px-3 py-2 text-start min-w-[260px]">{isAr ? "مصدر الاقتراح" : "Suggestion source"}</th>
            </tr>
          </thead>
          <tbody>
            {suggestedRows.map((row, index) => {
              const sourceLabel = row.suggestion_source === "odoo_bank_reconciliation_rule"
                ? (isAr ? "قاعدة بنك من أودو" : "Odoo bank rule")
                : row.suggestion_source === "odoo_historical_move_lines"
                  ? (isAr ? "مطابقة تاريخية من أودو" : "Odoo historical match")
                  : (isAr ? "اقتراح AI يحتاج مراجعة" : "AI suggestion needs review");
              return (
                <tr key={`${row.row_number}-${row.date}-${row.amount}-${index}`} className="border-b border-white/5 align-top hover:bg-white/5">
                  <td className="px-3 py-2 text-center font-mono text-white/40">{row.row_number || index + 1}</td>
                  <td className="px-3 py-2 font-mono text-white/70">{row.date || "—"}</td>
                  <td className="px-3 py-2 text-white">
                    <div className="font-semibold leading-relaxed">{row.main_description || row.description || "—"}</div>
                    {row.details && row.details.length > 0 && (
                      <details className="mt-1 text-white/45">
                        <summary className="cursor-pointer text-blue-300">{isAr ? "تفاصيل" : "Details"}</summary>
                        <div className="mt-1 space-y-1">{row.details.map((detail, detailIndex) => <div key={detailIndex}>{detail}</div>)}</div>
                      </details>
                    )}
                  </td>
                  <td className="px-3 py-2 text-end font-mono font-bold text-amber-300">{fmt(row.amount)} SAR</td>
                  <td className="px-3 py-2">
                    <input list={accountList} value={row.suggested_account_label || ""} onChange={event => updateSuggestedRow(index, { suggested_account_label: event.target.value })} placeholder={isAr ? "اختر الحساب من أودو" : "Select Odoo account"} className="w-full rounded-lg border border-cyan-500/20 bg-black/40 px-2 py-2 text-white outline-none focus:border-cyan-400" />
                  </td>
                  <td className="px-3 py-2">
                    <input list={partnerList} value={row.suggested_partner_label || ""} onChange={event => updateSuggestedRow(index, { suggested_partner_label: event.target.value })} placeholder={isAr ? "اختر الشريك" : "Select partner"} className="w-full rounded-lg border border-purple-500/20 bg-black/40 px-2 py-2 text-white outline-none focus:border-purple-400" />
                  </td>
                  <td className="px-3 py-2">
                    <input list={analyticList} value={row.suggested_analytic_account_label || ""} onChange={event => updateSuggestedRow(index, { suggested_analytic_account_label: event.target.value })} placeholder={isAr ? "اختياري" : "Optional"} className="w-full rounded-lg border border-amber-500/20 bg-black/40 px-2 py-2 text-white outline-none focus:border-amber-400" />
                  </td>
                  <td className="px-3 py-2 text-center">
                    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${Number(row.suggestion_confidence || 0) >= 0.7 ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300" : "border-amber-500/40 bg-amber-500/15 text-amber-300"}`}>{pct(row.suggestion_confidence)}</span>
                  </td>
                  <td className="px-3 py-2 text-white/55">
                    <div className="font-bold text-cyan-200">{sourceLabel}</div>
                    <div className="mt-1 leading-relaxed">{row.suggestion_reason || (isAr ? "راجع الحساب والشريك قبل الاعتماد." : "Review the account and partner before approval.")}</div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
