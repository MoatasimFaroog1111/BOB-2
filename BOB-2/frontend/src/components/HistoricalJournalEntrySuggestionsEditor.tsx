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
  label: string;
}

interface OdooSuggestion {
  row_number?: number | null;
  date?: string;
  amount?: number;
  suggested_account_label?: string;
  suggested_partner_label?: string;
  suggested_analytic_account_label?: string;
  confidence?: number;
  reason?: string;
  source?: string;
  needs_review?: boolean;
}

interface SuggestedRow extends Transaction {
  suggested_account_label: string;
  suggested_partner_label: string;
  suggested_analytic_account_label: string;
  suggestion_confidence: number;
  suggestion_reason: string;
  suggestion_source: string;
  suggestion_needs_review: boolean;
}

function selectedCompanyFromStorage() {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem("selectedCompanyId");
  const parsed = raw ? Number(raw) : NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function keyFor(row: { row_number?: number | null; date?: string | null; amount?: number | null }) {
  return `${row.row_number ?? ""}|${row.date || ""}|${Number(row.amount || 0).toFixed(2)}`;
}

function fmt(value?: number | null) {
  return Number(value || 0).toLocaleString("en-SA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pct(value?: number) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function asOptions(data: any): LookupOption[] {
  const arr = Array.isArray(data) ? data : data?.accounts || data?.partners || data?.analytic_accounts || data?.analyticAccounts || data?.items || [];
  return arr
    .map((item: any) => ({
      id: item.id,
      code: item.code || "",
      name: item.name || item.display_name || "",
      label: `${item.code || ""} ${item.name || item.display_name || ""}${item.vat ? ` - ${item.vat}` : ""}`.trim(),
    }))
    .filter((item: LookupOption) => item.label);
}

function applySuggestion(row: Transaction, suggestion?: OdooSuggestion | null): SuggestedRow {
  return {
    ...row,
    suggested_account_label: suggestion?.suggested_account_label || row.ai_suggested_account || "",
    suggested_partner_label: suggestion?.suggested_partner_label || "",
    suggested_analytic_account_label: suggestion?.suggested_analytic_account_label || "",
    suggestion_confidence: Number(suggestion?.confidence || row.confidence || 0),
    suggestion_reason: suggestion?.reason || row.explanation || "",
    suggestion_source: suggestion?.source || "odoo_historical_or_ai_review",
    suggestion_needs_review: suggestion?.needs_review ?? true,
  };
}

export default function HistoricalJournalEntrySuggestionsEditor({ rows, isAr, companyId, bankJournalId, bankAccountId }: Props) {
  const [suggestedRows, setSuggestedRows] = useState<SuggestedRow[]>(rows.map(row => applySuggestion(row)));
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

    async function loadInlineSuggestions() {
      if (!rows.length) {
        setSuggestedRows([]);
        return;
      }

      setLoading(true);
      setError("");
      setNotice("");

      try {
        const qs = effectiveCompanyId ? `?company_id=${effectiveCompanyId}` : "";
        const [accountsResponse, partnersResponse, analyticsResponse, historyResponse] = await Promise.all([
          fetch(`${API_BASE_URL}/api/v1/erp/accounts${qs}`),
          fetch(`${API_BASE_URL}/api/v1/erp/partners${qs}`),
          fetch(`${API_BASE_URL}/api/v1/erp/analytic-accounts${qs}`),
          fetch(`${API_BASE_URL}/api/v1/erp/bank-reconciliation/entry-suggestions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          }),
        ]);

        const accountsData = await accountsResponse.json().catch(() => null);
        const partnersData = await partnersResponse.json().catch(() => null);
        const analyticsData = await analyticsResponse.json().catch(() => null);
        const historyData = await historyResponse.json().catch(() => null);
        if (!historyResponse.ok) throw new Error(historyData?.detail || `Error ${historyResponse.status}`);

        const suggestions = new Map<string, OdooSuggestion>();
        (Array.isArray(historyData?.items) ? historyData.items : []).forEach((item: OdooSuggestion) => {
          suggestions.set(keyFor({ row_number: item.row_number, date: item.date, amount: item.amount }), item);
        });

        const nextRows = rows.map(row => applySuggestion(row, suggestions.get(keyFor(row))));

        if (!alive) return;
        setAccounts(accountsResponse.ok ? asOptions(accountsData) : []);
        setPartners(partnersResponse.ok ? asOptions(partnersData) : []);
        setAnalytics(analyticsResponse.ok ? asOptions(analyticsData) : []);
        setSuggestedRows(nextRows);
        const suggestedCount = nextRows.filter(row => row.suggested_account_label || row.suggested_partner_label).length;
        setNotice(isAr
          ? `تم تجهيز الحسابات والشركاء المقترحين أمام ${suggestedCount} عملية من بيانات أودو.`
          : `Suggested accounts and partners were prepared inline for ${suggestedCount} rows from Odoo data.`);
      } catch (err: any) {
        if (!alive) return;
        setSuggestedRows(rows.map(row => applySuggestion(row)));
        setError((isAr ? "تعذر تجهيز اقتراحات أودو: " : "Could not prepare Odoo suggestions: ") + (err?.message || err));
      } finally {
        if (alive) setLoading(false);
      }
    }

    loadInlineSuggestions();
    return () => { alive = false; };
  }, [payload, rows, isAr, effectiveCompanyId]);

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
            ? "كل عملية يظهر أمامها الحساب المقترح والشريك المقترح مباشرة. القيم قابلة للتعديل من بيانات أودو للشركة المختارة، ولا يوجد ترحيل من هذه الشاشة."
            : "Each transaction shows its suggested account and partner inline. Values are editable from the selected company's Odoo data, and this screen does not post entries."}
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
              const sourceLabel = row.suggestion_source === "odoo_historical_move_lines"
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
                  <td className="px-3 py-2"><input list={accountList} value={row.suggested_account_label} onChange={event => updateSuggestedRow(index, { suggested_account_label: event.target.value })} placeholder={isAr ? "اختر الحساب من أودو" : "Select Odoo account"} className="w-full rounded-lg border border-cyan-500/20 bg-black/40 px-2 py-2 text-white outline-none focus:border-cyan-400" /></td>
                  <td className="px-3 py-2"><input list={partnerList} value={row.suggested_partner_label} onChange={event => updateSuggestedRow(index, { suggested_partner_label: event.target.value })} placeholder={isAr ? "اختر الشريك" : "Select partner"} className="w-full rounded-lg border border-purple-500/20 bg-black/40 px-2 py-2 text-white outline-none focus:border-purple-400" /></td>
                  <td className="px-3 py-2"><input list={analyticList} value={row.suggested_analytic_account_label} onChange={event => updateSuggestedRow(index, { suggested_analytic_account_label: event.target.value })} placeholder={isAr ? "اختياري" : "Optional"} className="w-full rounded-lg border border-amber-500/20 bg-black/40 px-2 py-2 text-white outline-none focus:border-amber-400" /></td>
                  <td className="px-3 py-2 text-center"><span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${row.suggestion_confidence >= 0.7 ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300" : "border-amber-500/40 bg-amber-500/15 text-amber-300"}`}>{pct(row.suggestion_confidence)}</span></td>
                  <td className="px-3 py-2 text-white/55"><div className="font-bold text-cyan-200">{sourceLabel}</div><div className="mt-1 leading-relaxed">{row.suggestion_reason || (isAr ? "راجع الحساب والشريك قبل الاعتماد." : "Review the account and partner before approval.")}</div></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
