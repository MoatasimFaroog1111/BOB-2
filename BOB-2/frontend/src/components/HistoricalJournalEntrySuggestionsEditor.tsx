"use client";

import { useEffect, useMemo, useState } from "react";
import { API_BASE_URL } from "@/lib/api";
import JournalEntrySuggestionsEditor from "@/components/JournalEntrySuggestionsEditor";

interface Transaction {
  date: string;
  description: string;
  amount: number;
  row_number: number;
  suggested_action?: string;
  suggested_action_label?: string;
  confidence?: number;
  explanation?: string;
  detected_category?: string;
  ai_suggested_account?: string;
  bank_rule_suggestion?: any;
  historical_suggestion?: any;
}

interface Props {
  rows: Transaction[];
  isAr: boolean;
  bankAccountLabel?: string;
  companyId?: number | null;
  bankJournalId?: number | string | null;
  bankAccountId?: number | null;
}

interface HistoricalSuggestion {
  row_number?: number | null;
  date?: string;
  amount?: number;
  suggested_account_label?: string;
  suggested_partner_label?: string;
  suggested_analytic_account_label?: string;
  confidence?: number;
  reason?: string;
  historical_move_name?: string;
  historical_date?: string;
  needs_review?: boolean;
  source?: string;
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

function keyFor(row: Pick<Transaction, "row_number" | "date" | "amount">) {
  return `${row.row_number ?? ""}|${row.date || ""}|${Number(row.amount || 0).toFixed(2)}`;
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
  const text = [row.description, row.suggested_action_label, row.explanation, row.detected_category].filter(Boolean).join(" ");
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
    suggested_account_label: account.label,
    suggested_partner_label: partner.label,
    suggested_analytic_account_label: analytic.label,
    confidence: best.score,
    reason: `Matched Odoo bank rule ${best.rule.name || best.rule.id}`,
    source: "odoo_bank_reconciliation_rule",
    needs_review: best.score < 0.7,
  };
}

function enrichRow(row: Transaction, item: HistoricalSuggestion | null, isAr: boolean) {
  if (!item || !item.suggested_account_label) return row;
  const parts = [item.suggested_account_label, item.suggested_partner_label, item.suggested_analytic_account_label].filter(Boolean);
  const isRule = item.source === "odoo_bank_reconciliation_rule";
  const label = isRule ? (isAr ? "اقتراح من قاعدة البنك" : "Bank rule suggestion") : (isAr ? "اقتراح تاريخي من أودو" : "Historical Odoo suggestion");
  return {
    ...row,
    ai_suggested_account: parts.join(" | "),
    bank_rule_suggestion: isRule ? item : row.bank_rule_suggestion,
    historical_suggestion: isRule ? row.historical_suggestion : item,
    confidence: Math.max(Number(row.confidence || 0), Number(item.confidence || 0)),
    suggested_action_label: item.needs_review ? (row.suggested_action_label || (isAr ? "يحتاج مراجعة" : "Needs review")) : `${label} ${pct(item.confidence)}`,
    explanation: `${row.explanation || ""}${row.explanation ? " | " : ""}${item.reason || label}`,
  };
}

export default function HistoricalJournalEntrySuggestionsEditor({ rows, isAr, bankAccountLabel = "", companyId, bankJournalId, bankAccountId }: Props) {
  const [enhancedRows, setEnhancedRows] = useState<Transaction[]>(rows);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const payload = useMemo(() => ({
    transactions: rows,
    company_id: companyId || null,
    bank_journal_id: bankJournalId ? Number(bankJournalId) : null,
    bank_account_id: bankAccountId || null,
    history_limit: 600,
  }), [rows, companyId, bankJournalId, bankAccountId]);

  useEffect(() => {
    let alive = true;
    async function loadSuggestions() {
      if (!rows.length) {
        setEnhancedRows([]);
        return;
      }
      setLoading(true);
      setError("");
      setNotice("");
      try {
        const params = new URLSearchParams();
        if (companyId) params.set("company_id", String(companyId));
        if (bankJournalId) params.set("bank_journal_id", String(bankJournalId));
        const [rulesResponse, historyResponse] = await Promise.all([
          fetch(`${API_BASE_URL}/api/v1/erp/bank-reconciliation/bank-rules?${params.toString()}`),
          fetch(`${API_BASE_URL}/api/v1/erp/bank-reconciliation/entry-suggestions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          }),
        ]);

        const rulesData = await rulesResponse.json().catch(() => null);
        const historyData = await historyResponse.json().catch(() => null);
        const rules: BankRule[] = rulesResponse.ok && Array.isArray(rulesData?.items) ? rulesData.items : [];
        if (!historyResponse.ok) throw new Error(historyData?.detail || `Error ${historyResponse.status}`);

        const historySuggestions = new Map<string, HistoricalSuggestion>();
        (Array.isArray(historyData?.items) ? historyData.items : []).forEach((item: HistoricalSuggestion) => {
          historySuggestions.set(keyFor({ row_number: Number(item.row_number || "", amount: Number(item.amount || 0) }), item);
        });

        const nextRows = rows.map((row) => {
          const ruleItem = matchBankRule(row, rules);
          if (ruleItem?.suggested_account_label) return enrichRow(row, ruleItem, isAr);
          const historyItem = historySuggestions.get(keyFor(row));
          return enrichRow(row, historyItem || null, isAr);
        });

        if (!alive) return;
        setEnhancedRows(nextRows);
        const ruleCount = nextRows.filter(r => r.bank_rule_suggestion).length;
        setNotice(isAr
          ? `تم تطبيق ${ruleCount} اقتراح من قواعد البنك، والباقي من البيانات التاريخية عند الحاجة.`
          : `${ruleCount} suggestions came from bank rules; remaining rows used history when needed.`);
      } catch (err: any) {
        if (!alive) return;
        setEnhancedRows(rows);
        setError((isAr ? "تعذر قراءة قواعد البنك أو البيانات التاريخية: " : "Could not read bank rules or history: ") + (err?.message || err));
      } finally {
        if (alive) setLoading(false);
      }
    }
    loadSuggestions();
    return () => { alive = false; };
  }, [payload, rows, isAr, companyId, bankJournalId]);

  return (
    <>
      <div className="fixed top-5 right-5 z-[10001] max-w-xl space-y-2 text-xs">
        {loading && <div className="rounded-xl border border-cyan-500/40 bg-cyan-500/15 px-4 py-2 font-bold text-cyan-200 shadow-2xl">{isAr ? "جاري قراءة قواعد البنك والبيانات التاريخية من أودو..." : "Reading Odoo bank rules and historical entries..."}</div>}
        {notice && <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/15 px-4 py-2 font-bold text-emerald-200 shadow-2xl">{notice}</div>}
        {error && <div className="rounded-xl border border-amber-500/40 bg-amber-500/15 px-4 py-2 font-bold text-amber-200 shadow-2xl">{error}</div>}
      </div>
      <JournalEntrySuggestionsEditor rows={enhancedRows} isAr={isAr} bankAccountLabel={bankAccountLabel} />
    </>
  );
}
